"""Authenticated encryption primitive for server-managed AI keys.

No key material is stored in the repo, database or logs by this module.
A caller must resolve authorization and tenant from a trusted principal.
Keyring is injected by a future server secret manager, not HTTP payloads.
"""
from dataclasses import dataclass
from secrets import token_bytes
from uuid import UUID
import re
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.exceptions import InvalidTag
from cloud.ai_budget import PROVIDERS

VERSION = re.compile(r"[a-zA-Z0-9_-]{1,32}")

class SecretError(ValueError):
    pass

@dataclass(frozen=True, repr=False)
class Envelope:
    key_version: str
    nonce: bytes
    ciphertext: bytes

def _aad(tenant, provider, version):
    if not isinstance(provider,str) or provider not in PROVIDERS or not isinstance(version,str) or not VERSION.fullmatch(version):
        raise SecretError("Invalid key context")
    return ("cvcloud.ai-key.v1:" + str(UUID(str(tenant))) + ":" + provider + ":" + version).encode("ascii")

class SecretCipher:
    def __init__(self, keys, active_version):
        if not isinstance(active_version,str) or active_version not in keys or any(not isinstance(v,str) or not VERSION.fullmatch(v) or type(k) is not bytes or len(k)!=32 for v,k in keys.items()):
            raise SecretError("Invalid keyring")
        self._keys=dict(keys)
        self._active=active_version

    def encrypt(self, tenant, provider, secret):
        if not isinstance(secret,str) or not 1 <= len(secret) <= 4096 or not secret.isascii() or any(ord(c)<33 or ord(c)>126 for c in secret):
            raise SecretError("Invalid provider secret")
        version=self._active
        nonce=token_bytes(12)
        encrypted=AESGCM(self._keys[version]).encrypt(nonce,secret.encode("ascii"),_aad(tenant,provider,version))
        return Envelope(version,nonce,encrypted)

    def decrypt(self, tenant, provider, envelope):
        if not isinstance(envelope,Envelope) or not isinstance(envelope.key_version,str) or envelope.key_version not in self._keys or type(envelope.nonce) is not bytes or len(envelope.nonce)!=12 or type(envelope.ciphertext) is not bytes or not 17 <= len(envelope.ciphertext) <= 4112:
            raise SecretError("Invalid encrypted credential")
        try:
            return AESGCM(self._keys[envelope.key_version]).decrypt(envelope.nonce,envelope.ciphertext,_aad(tenant,provider,envelope.key_version)).decode("ascii")
        except (InvalidTag,UnicodeError) as exc:
            raise SecretError("Credential authentication failed") from exc
