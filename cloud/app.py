"""Isolated cloud composition root, deliberately not the desktop Flask app."""
from flask import Flask, jsonify

def create_app():
    app = Flask(__name__, static_folder=None)
    app.config.update(MAX_CONTENT_LENGTH=32 * 1024 * 1024)
    @app.get("/healthz")
    def health():
        return jsonify(status="ok", service="cv-studio-cloud", stage="foundation")
    @app.get("/readyz")
    def ready():
        return jsonify(status="not_ready", reason="authentication_and_storage_not_implemented"), 503
    return app

if __name__ == "__main__":
    from waitress import serve
    serve(create_app(), host="0.0.0.0", port=8000, threads=4)
