"""Explicit opt-in staging UI, not registered by the default app."""
from pathlib import Path
from flask import Blueprint,send_from_directory

ASSETS=Path(__file__).with_name("workspace_assets")
workspace=Blueprint("cv_workspace",__name__)

@workspace.get("/workspace")
def index():
    response=send_from_directory(ASSETS,"index.html",conditional=False,max_age=0)
    response.headers["Content-Security-Policy"]="default-src 'none'; script-src 'self'; style-src 'self'; connect-src 'self'; form-action 'self'; base-uri 'none'; frame-ancestors 'none'"
    return response

@workspace.get("/workspace/assets/<name>")
def asset(name):
    if name not in {"workspace.js","workspace.css"}:
        from flask import abort
        abort(404)
    return send_from_directory(ASSETS,name,conditional=False,max_age=0)

@workspace.after_request
def headers(response):
    response.headers["Cache-Control"]="no-store"
    response.headers["X-Content-Type-Options"]="nosniff"
    response.headers["Referrer-Policy"]="no-referrer"
    return response
