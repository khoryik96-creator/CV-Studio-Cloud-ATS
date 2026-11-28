"""Bounded online auth-only WSGI listener; internal network only.

No public proxy, no document services, no live AI. /readyz remains 503.
"""
from cloud.deploy.online_auth import build_online_auth, read_config

def server_options():
    # Middleware must see the original peer and exact raw forwarding headers.
    # Do not configure Waitress trusted_proxy or rewrite REMOTE_ADDR upstream.
    return dict(threads=4,connection_limit=64,channel_timeout=30,
                max_request_header_size=16384,max_request_body_size=4096,
                clear_untrusted_proxy_headers=False,expose_tracebacks=False,
                ident="CV Studio")

def main():
    from waitress import serve
    app=build_online_auth(config=read_config())
    serve(app,host="0.0.0.0",port=8000,**server_options())

if __name__=="__main__":
    main()
