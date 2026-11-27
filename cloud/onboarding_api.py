"""Optional public redemption only. Tokens enter a POST body, never URLs.

Issuance and delivery remain internal. This endpoint does not authenticate
or establish a session; the recipient signs in separately afterwards.
"""
from flask import jsonify,request
from cloud.auth import TOKEN,digest
from cloud.account_admin import AccountAdminError

def register(app,auth,same_origin,service):
    if not callable(getattr(service,"redeem",None)):
        raise ValueError("Onboarding service required")

    @app.post("/api/auth/redeem")
    def redeem():
        if not same_origin():
            return jsonify(error="forbidden"),403
        request.max_content_length=4096
        source=request.remote_addr
        if not isinstance(source,str) or not 1<=len(source)<=128:
            return jsonify(error="invalid_request"),400
        now=auth.clock()
        # Source before parsing/allocating token buckets, with distinct prefixes
        # from normal login. No trust in caller-provided forwarding headers.
        if not auth.store.consume_attempt(digest("redeem:source:"+source),now):
            return jsonify(error="try_again_later"),429
        body=request.get_json(silent=True)
        if not isinstance(body,dict) or set(body)!={"token","password"}:
            return jsonify(error="invalid_or_expired_challenge"),400
        token,password=body["token"],body["password"]
        if not isinstance(token,str) or not TOKEN.fullmatch(token):
            return jsonify(error="invalid_or_expired_challenge"),400
        if not auth.store.consume_attempt(digest("redeem:token:"+token),now):
            return jsonify(error="try_again_later"),429
        try:
            if not isinstance(password,str) or not 12<=len(password)<=256 or any(ord(c)<32 or ord(c)==127 for c in password):
                raise ValueError()
            password.encode("utf-8")
            if not service.redeem(token,password):
                raise ValueError()
        except (ValueError,UnicodeError,AccountAdminError):
            return jsonify(error="invalid_or_expired_challenge"),400
        return jsonify(ok=True)
