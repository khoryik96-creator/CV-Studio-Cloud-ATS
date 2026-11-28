"""Optional public redemption only. Tokens enter a POST body, never URLs.

Issuance and delivery remain internal. This endpoint does not authenticate
or establish a session; the recipient signs in separately afterwards.
"""
from pathlib import Path
from flask import jsonify,request,Response,send_file
from cloud.auth import TOKEN,digest
from cloud.account_admin import AccountAdminError

def register(app,auth,same_origin,service):
    if not callable(getattr(service,"redeem",None)):
        raise ValueError("Onboarding service required")

    @app.get("/activate")
    def activation_page():
        # The token is never accepted from a query string or fragment.
        if request.query_string:
            return Response("Open /activate without a token in the address.",status=400,mimetype="text/plain")
        response=Response("""<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>CV Studio · Activate account</title><link rel="stylesheet" href="/activate/style.css"><script src="/activate/client.js" defer></script></head><body><main><h1>CV Studio</h1><h2>Activate account or reset password</h2><p>Enter the one-time code supplied securely by your organisation administrator. Choose a new password. After activation, sign in separately.</p><form id="activationForm" method="post" action="/api/auth/redeem"><label for="activationCode">One-time code</label><input id="activationCode" type="password" autocomplete="off" maxlength="43" required disabled><label for="activationPassword">New password</label><input id="activationPassword" type="password" autocomplete="new-password" minlength="12" maxlength="256" required disabled><label for="activationConfirm">Confirm password</label><input id="activationConfirm" type="password" autocomplete="new-password" minlength="12" maxlength="256" required disabled><button id="activationSubmit" type="submit" disabled>Set password</button></form><p role="status" aria-live="polite" id="activationStatus">Loading secure form…</p><a href="/cloud-ui">Return to sign in</a></main></body></html>""",mimetype="text/html")
        response.headers["Content-Security-Policy"]="default-src 'none'; script-src 'self'; style-src 'self'; connect-src 'self'; form-action 'none'; frame-ancestors 'none'; base-uri 'none'"
        response.headers["Referrer-Policy"]="no-referrer"
        response.headers["X-Frame-Options"]="DENY"
        return response

    @app.get("/activate/client.js")
    def activation_script():
        return send_file(Path(__file__).with_name("frontend")/"activation_cloud.js",mimetype="application/javascript",conditional=False,max_age=0)

    @app.get("/activate/style.css")
    def activation_style():
        return send_file(Path(__file__).with_name("frontend")/"activation_cloud.css",mimetype="text/css",conditional=False,max_age=0)

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
