"""Tenant-scoped provider configuration and worker-only credential resolution.

No HTTP endpoints, browser secrets, default prices, production grants or paid
requests. The deployment composition root injects a verified price/limit
catalogue, keyring and dedicated database access. Do not expose resolve()
or ciphertext to HTTP clients.
"""
from dataclasses import dataclass
from cloud.ai_budget import model_id,amount
from cloud.ai_dispatch import ModelPolicy,_tokens
from cloud.ai_secrets import Envelope,SecretCipher
from cloud.deepseek import DeepSeekTransport

class ProviderConfigError(ValueError):
    pass

@dataclass(frozen=True)
class ProviderStatus:
    revision: int
    provider: str
    model: str
    enabled: bool

def _revision(value):
    if type(value) is not int or not 0<=value<2**63-1:
        raise ProviderConfigError("invalid_revision")
    return value

class ProviderCatalogue:
    def __init__(self,policies):
        if not isinstance(policies,(list,tuple)) or not 1<=len(policies)<=100:
            raise ProviderConfigError("trusted_catalogue_required")
        self._policies={}
        for p in policies:
            if not isinstance(p,ModelPolicy) or p.provider!="deepseek":
                raise ProviderConfigError("unsupported_provider")
            key=model_id(p.provider,p.model)
            if key in self._policies:
                raise ProviderConfigError("duplicate_model")
            amount(p.input_rate,allow_zero=True)
            amount(p.output_rate,allow_zero=True)
            if not (p.input_rate or p.output_rate) or not 1<=_tokens(p.max_input_tokens) or not 1<=_tokens(p.max_output_tokens):
                raise ProviderConfigError("invalid_policy")
            self._policies[key]=p

    def get(self,provider,model):
        key=model_id(provider,model)
        try:
            return self._policies[key]
        except KeyError:
            raise ProviderConfigError("model_not_approved") from None

class ProviderConfig:
    def __init__(self,repository,cipher,catalogue,*,transport_factory=DeepSeekTransport):
        if not isinstance(cipher,SecretCipher) or not isinstance(catalogue,ProviderCatalogue) or not callable(transport_factory):
            raise ProviderConfigError("invalid_server_configuration")
        self.repository,self.cipher,self.catalogue=repository,cipher,catalogue
        self.transport_factory=transport_factory

    @staticmethod
    def _authorize(conn,tenant,user,*,admin=False):
        # Do not trust a cached role or caller-supplied role alone. Hold the
        # account and tenant status stable through the configuration operation.
        row=conn.execute("""SELECT u.role FROM cvcloud.users u JOIN cvcloud.tenants t ON t.id=u.tenant_id
            WHERE u.tenant_id=%s AND u.id=%s AND u.active AND t.active
            FOR SHARE OF u,t""",(tenant,user)).fetchone()
        if not row or (admin and row[0] not in ("owner","admin")):
            raise ProviderConfigError("provider_access_denied")

    def status(self,principal):
        # Administrative status only, never key version, nonce or ciphertext.
        with self.repository.scoped(principal) as (conn,tenant,user):
            self._authorize(conn,tenant,user,admin=True)
            row=conn.execute("""SELECT revision,provider,model,enabled FROM cvcloud.provider_config
                WHERE tenant_id=%s""",(tenant,)).fetchone()
            return ProviderStatus(*row) if row else None

    def configure(self,principal,*,provider,model,secret,expected_revision):
        expected=_revision(expected_revision)
        self.catalogue.get(provider,model)
        with self.repository.scoped(principal) as (conn,tenant,user):
            self._authorize(conn,tenant,user,admin=True)
            envelope=self.cipher.encrypt(tenant,provider,secret)
            if expected==0:
                row=conn.execute("""INSERT INTO cvcloud.provider_config
                    (tenant_id,revision,provider,model,enabled,key_version,nonce,ciphertext,updated_by)
                    VALUES (%s,1,%s,%s,true,%s,%s,%s,%s)
                    ON CONFLICT DO NOTHING RETURNING revision""",
                    (tenant,provider,model,envelope.key_version,envelope.nonce,envelope.ciphertext,user)).fetchone()
            else:
                row=conn.execute("""UPDATE cvcloud.provider_config SET revision=revision+1,
                    provider=%s,model=%s,enabled=true,key_version=%s,nonce=%s,ciphertext=%s,
                    updated_by=%s,updated_at=clock_timestamp()
                    WHERE tenant_id=%s AND revision=%s RETURNING revision""",
                    (provider,model,envelope.key_version,envelope.nonce,envelope.ciphertext,user,tenant,expected)).fetchone()
            if not row:
                raise ProviderConfigError("configuration_conflict")
            return ProviderStatus(row[0],provider,model,True)

    def disable(self,principal,*,expected_revision):
        expected=_revision(expected_revision)
        with self.repository.scoped(principal) as (conn,tenant,user):
            self._authorize(conn,tenant,user,admin=True)
            row=conn.execute("""UPDATE cvcloud.provider_config SET revision=revision+1,enabled=false,
                key_version=NULL,nonce=NULL,ciphertext=NULL,updated_by=%s,updated_at=clock_timestamp()
                WHERE tenant_id=%s AND revision=%s AND enabled
                RETURNING revision,provider,model,enabled""",(user,tenant,expected)).fetchone()
            if not row:
                raise ProviderConfigError("configuration_conflict")
            return ProviderStatus(*row)

    def resolve(self,principal):
        """Trusted worker resolver; returns policy and a revision-fenced transport."""
        with self.repository.scoped(principal) as (conn,tenant,user):
            self._authorize(conn,tenant,user)
            row=conn.execute("""SELECT revision,provider,model,key_version,nonce,ciphertext
                FROM cvcloud.provider_config WHERE tenant_id=%s AND enabled""",(tenant,)).fetchone()
            if not row:
                raise ProviderConfigError("provider_not_configured")
            revision,provider,model,version,nonce,ciphertext=row
            policy=self.catalogue.get(provider,model)
        # Resolve credential only at dispatch, not during queue admission.
        def transport(request_provider,request_model,system,prompt,limit):
            if (request_provider,request_model)!=(provider,model):
                raise ProviderConfigError("provider_policy_mismatch")
            with self.repository.scoped(principal) as (conn,tenant,user):
                self._authorize(conn,tenant,user)
                current=conn.execute("""SELECT key_version,nonce,ciphertext
                    FROM cvcloud.provider_config WHERE tenant_id=%s AND enabled AND revision=%s
                    AND provider=%s AND model=%s""",(tenant,revision,provider,model)).fetchone()
                if not current:
                    raise ProviderConfigError("provider_configuration_changed")
                secret=self.cipher.decrypt(tenant,provider,Envelope(*current))
            # Never hold a transaction over a network call. A rotation after
            # this check cannot recall an already authorized in-flight request.
            return self.transport_factory(secret)(provider,model,system,prompt,limit)
        return policy,transport
