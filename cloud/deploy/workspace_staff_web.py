"""Optional online-only browser enrollment, using the existing staff policy."""
from pathlib import Path
from urllib.parse import urlsplit

from flask import Response, jsonify, request, send_file

from cloud.app import COOKIE
from cloud.deploy.workspace_staff_access import STAFF_TTL, redeem_staff

SCRIPT = Path(__file__).resolve().parent.parent / "frontend" / "staff_enrollment.js"
PAGE = """<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>CV Studio staff access</title><script src="/staff/enroll.js" defer></script></head>
<body><main><h1>CV Studio staff access</h1><p>Use your one-time link to authorize this browser.</p>
<button type="button" id="staffEnroll" disabled>Continue to CV Studio</button>
<p id="staffStatus" role="status"></p></main></body></html>"""


def verify_staff_database(connect):
    with connect() as conn:
        row = conn.execute("""SELECT current_user::text,
            has_function_privilege(current_user,
              to_regprocedure('cvcloud.redeem_staff_enrollment(text,text,text)'), 'EXECUTE')""").fetchone()
    if row != ("cvcloud_auth", True):
        raise RuntimeError("Installed staff enrollment policy required")


def register_staff_access(app, *, public_origin):
    auth = app.extensions["cvcloud_auth"]
    host = urlsplit(public_origin).hostname

    @app.get("/staff/enroll")
    def enrollment_page():
        return Response(PAGE, mimetype="text/html", headers={
            "Content-Security-Policy": "default-src 'none'; script-src 'self'; connect-src 'self'; "
                                       "base-uri 'none'; frame-ancestors 'none'; form-action 'none'",
            "Referrer-Policy": "no-referrer",
        })

    @app.get("/staff/enroll.js")
    def enrollment_script():
        return send_file(SCRIPT, conditional=False, max_age=0)

    @app.post("/staff/enroll")
    def enrollment():
        if request.headers.get("Origin") != public_origin or request.host != host:
            return jsonify(error="forbidden"), 403
        request.max_content_length = 1024
        body = request.get_json(silent=True)
        if not isinstance(body, dict) or set(body) != {"token"}:
            return jsonify(error="invalid_request"), 400
        if auth.principal(request.cookies.get(COOKIE)):
            return jsonify(error="sign_out_first"), 409
        session = redeem_staff(auth, body["token"], request.remote_addr)
        if not session:
            return jsonify(error="enrollment_unavailable"), 401
        response = jsonify(ok=True)
        response.set_cookie(COOKIE, session, max_age=int(STAFF_TTL.total_seconds()),
                            secure=True, httponly=True, samesite="Strict", path="/")
        return response
