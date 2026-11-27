"""Read-only tenant budget snapshot. No reservation rows, provider invoices or writes."""
from flask import jsonify,request
from cloud.documents_jobs import ScopeError

class AIUsage:
    def __init__(self,repository):
        self.repository=repository

    def snapshot(self,principal):
        with self.repository.scoped(principal) as (conn,tenant,user):
            actor=conn.execute("""SELECT u.role FROM cvcloud.users u JOIN cvcloud.tenants t ON t.id=u.tenant_id
                WHERE u.tenant_id=%s AND u.id=%s AND u.active AND t.active FOR SHARE OF u,t""",(tenant,user)).fetchone()
            if not actor or actor[0] not in ("owner","admin"):
                raise ScopeError("Usage unavailable")
            row=conn.execute("""SELECT limit_microusd,reserved_microusd,spent_microusd
                FROM cvcloud.ai_budgets WHERE tenant_id=%s""",(tenant,)).fetchone()
            if row is None:
                return {"configured":False}
            limit,reserved,spent=row
            committed=reserved+spent
            return {"configured":True,"limit_microusd":str(limit),"reserved_microusd":str(reserved),
                "spent_microusd":str(spent),"remaining_microusd":str(max(0,limit-committed)),
                "over_limit_microusd":str(max(0,committed-limit))}

def register(app,auth,cookie,service):
    if not callable(getattr(service,"snapshot",None)):
        raise ValueError("AI usage service required")
    @app.get("/api/admin/ai-usage")
    def usage():
        principal=auth.principal(request.cookies.get(cookie))
        if principal is None:
            return jsonify(error="unauthorized"),401
        if principal.role not in ("owner","admin"):
            return jsonify(error="forbidden"),403
        if request.args:
            return jsonify(error="invalid_request"),400
        try:
            return jsonify(service.snapshot(principal))
        except ScopeError:
            return jsonify(error="forbidden"),403
