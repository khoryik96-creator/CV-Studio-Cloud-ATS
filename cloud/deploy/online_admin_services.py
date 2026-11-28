"""Account/usage adapters for function-only restricted backend role.

No password creation/reset, invitations or direct table SQL. These adapters
remain unmounted until the separate role installer and integration tests pass.
"""
from uuid import uuid4
from cloud.account_admin import AccountAdminError, AccountStatus, _revision
from cloud.documents_jobs import ScopeError, uid

KNOWN_ERRORS=frozenset(("account_admin_denied","account_conflict","account_limit_exceeded",
    "invalid_action","invalid_role_change","invalid_state_change"))

def _translate(error):
    # Map only fixed SQL function errors, never return arbitrary DB details.
    if getattr(error,"sqlstate",None)=="P0001":
        message=getattr(getattr(error,"diag",None),"message_primary",None)
        if message in KNOWN_ERRORS:
            raise AccountAdminError(message) from None
    raise error

class OnlineAccountAdmin:
    def __init__(self,repository):
        self.repository=repository

    def list_accounts(self,principal):
        try:
            with self.repository.scoped(principal) as (conn,_,__):
                rows=conn.execute("SELECT * FROM cvcloud.admin_list_accounts()").fetchall()
                return tuple(AccountStatus(*row) for row in rows)
        except Exception as error:
            _translate(error)

    def change(self,principal,*,user_id,expected_revision,action,value=None):
        if action not in ("role_change","suspend","reactivate","revoke_sessions"):
            raise AccountAdminError("invalid_action")
        if action=="role_change" and value not in ("admin","recruiter"):
            raise AccountAdminError("invalid_role_change")
        if action!="role_change" and value is not None:
            raise AccountAdminError("invalid_action")
        try:
            with self.repository.scoped(principal) as (conn,_,__):
                row=conn.execute("SELECT * FROM cvcloud.admin_change_account(%s::uuid,%s::bigint,%s::text,%s::text,%s::uuid)",
                    (uid(user_id),_revision(expected_revision),action,value,str(uuid4()))).fetchone()
                if row is None:
                    raise AccountAdminError("account_conflict")
                return AccountStatus(*row)
        except Exception as error:
            _translate(error)

class OnlineAIUsage:
    def __init__(self,repository):
        self.repository=repository
    def snapshot(self,principal):
        try:
            with self.repository.scoped(principal) as (conn,_,__):
                row=conn.execute("SELECT * FROM cvcloud.admin_usage_snapshot()").fetchone()
                if row is None:
                    return {"configured":False}
                limit,reserved,spent=row
                committed=reserved+spent
                return {"configured":True,"limit_microusd":str(limit),"reserved_microusd":str(reserved),
                    "spent_microusd":str(spent),"remaining_microusd":str(max(0,limit-committed)),
                    "over_limit_microusd":str(max(0,committed-limit))}
        except Exception as error:
            try:
                _translate(error)
            except AccountAdminError:
                raise ScopeError("Usage unavailable") from None
