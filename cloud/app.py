"""Isolated cloud composition root; desktop routes are never imported."""
from urllib.parse import urlsplit
from flask import Flask, jsonify, request
from cloud.auth import Auth, TTL

COOKIE = "__Host-cvcloud"

def create_app(*, auth_store=None, public_origin=None, cv_services=None, provider_admin=None):
    app = Flask(__name__, static_folder=None)
    app.config.update(MAX_CONTENT_LENGTH=32 * 1024 * 1024)
    @app.get("/healthz")
    def health():
        return jsonify(status="ok", service="cv-studio-cloud", stage="auth-foundation")
    @app.get("/readyz")
    def ready():
        # Authentication is only opt-in for integration tests. No document
        # routes, production configuration, provisioning or migrations yet.
        return jsonify(status="not_ready", reason="production_storage_and_document_services_not_ready"), 503
    if auth_store is None and public_origin is None:
        if cv_services is not None or provider_admin is not None:
            raise ValueError('Cloud services require authentication')
        return app
    if auth_store is None or not isinstance(public_origin, str):
        raise ValueError("Auth store and exact HTTPS origin must be configured together")
    parsed = urlsplit(public_origin)
    if parsed.scheme != "https" or not parsed.hostname or parsed.username or parsed.password or parsed.path or parsed.query or parsed.fragment or parsed.netloc != parsed.hostname or "*" in parsed.hostname:
        raise ValueError("An exact HTTPS hostname without port or path is required")
    app.config["TRUSTED_HOSTS"] = [parsed.hostname]
    auth = Auth(auth_store)
    app.extensions["cvcloud_auth"] = auth

    @app.after_request
    def headers(response):
        response.headers["Cache-Control"] = "no-store"
        response.headers["X-Content-Type-Options"] = "nosniff"
        return response

    def same_origin():
        return request.headers.get("Origin") == public_origin and request.host == parsed.hostname

    @app.post("/api/auth/login")
    def login():
        if not same_origin():
            return jsonify(error="forbidden"), 403
        request.max_content_length = 4096
        if not request.is_json:
            return jsonify(error="invalid_request"), 400
        body = request.get_json(silent=True)
        if not isinstance(body, dict):
            return jsonify(error="invalid_request"), 400
        raw = auth.login(body.get("tenant"), body.get("email"), body.get("password"), request.remote_addr)
        if not raw:
            return jsonify(error="invalid_credentials_or_rate_limited"), 401
        # Revoke the old browser session if present, then set a fresh token.
        old = request.cookies.get(COOKIE)
        old_p = auth.principal(old)
        if old_p:
            auth.logout(old, old_p.csrf)
        response = jsonify(ok=True)
        response.set_cookie(COOKIE, raw, max_age=int(TTL.total_seconds()), secure=True, httponly=True, samesite="Strict", path="/")
        return response

    @app.get("/api/auth/me")
    def me():
        p = auth.principal(request.cookies.get(COOKIE))
        if not p:
            return jsonify(error="unauthorized"), 401
        return jsonify(tenant_id=p.tenant_id, user_id=p.user_id, role=p.role, csrf=p.csrf)

    @app.post("/api/auth/logout")
    def logout():
        if not same_origin() or not auth.logout(request.cookies.get(COOKIE), request.headers.get("X-CSRF-Token")):
            return jsonify(error="forbidden"), 403
        response = jsonify(ok=True)
        response.delete_cookie(COOKIE, path="/", secure=True, httponly=True, samesite="Strict")
        return response
    if cv_services is not None:
        from cloud.cv_api import register
        register(app,auth,COOKIE,same_origin,*cv_services)
    if provider_admin is not None:
        from cloud.provider_admin_api import register as register_provider_admin
        register_provider_admin(app,auth,COOKIE,same_origin,provider_admin)
    return app

if __name__ == "__main__":
    from waitress import serve
    serve(create_app(), host="0.0.0.0", port=8000, threads=4)
