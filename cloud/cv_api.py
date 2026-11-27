"""Opt-in authenticated staging endpoints. No production startup wiring."""
from functools import wraps
import hmac
from io import BytesIO
from flask import jsonify,request,send_file
from cloud.auth import TOKEN
from cloud.documents_jobs import uid,JobConflict,ScopeError,MAX_BYTES
from cloud.job_options import Options
from cloud.private_storage import DOCX,StorageError

CV_MODULES=frozenset({"cv_formatting","cv_blinding"})

def register(app,auth,cookie,same_origin,uploads,repository,outputs):
    def protected(*,write=False):
        def decorate(fn):
            @wraps(fn)
            def wrapped(*args,**kwargs):
                principal=auth.principal(request.cookies.get(cookie))
                if principal is None:
                    return jsonify(error="unauthorized"),401
                if write:
                    csrf=request.headers.get("X-CSRF-Token","")
                    if not same_origin() or not TOKEN.fullmatch(csrf) or not hmac.compare_digest(principal.csrf,csrf):
                        return jsonify(error="forbidden"),403
                try:
                    return fn(principal,*args,**kwargs)
                except ScopeError:
                    return jsonify(error="not_found"),404
                except JobConflict:
                    return jsonify(error="quota_or_request_conflict"),409
                except StorageError:
                    return jsonify(error="document_validation_or_integrity_failed"),400 if write else 503
                except (ValueError,TypeError):
                    return jsonify(error="invalid_request"),400
                except OSError:
                    return jsonify(error="storage_unavailable"),503
            return wrapped
        return decorate

    @app.post("/api/documents")
    @protected(write=True)
    def upload(principal):
        if request.content_length is None:
            return jsonify(error="content_length_required"),411
        if request.content_length>MAX_BYTES:
            return jsonify(error="file_too_large"),413
        object_id=uploads.upload(principal,request.stream,media_type=request.mimetype,byte_size=request.content_length)
        return jsonify(document_id=object_id),201

    @app.post("/api/jobs")
    @protected(write=True)
    def submit(principal):
        request.max_content_length=4096
        body=request.get_json(silent=True)
        if not isinstance(body,dict) or set(body)-{"document_id","module","idempotency_key","alignment","correct_language","neutral_gender"}:
            return jsonify(error="invalid_request"),400
        module=body.get("module")
        if not isinstance(module,str) or module not in CV_MODULES:
            return jsonify(error="module_unavailable"),400
        options=Options(body.get("alignment","left"),body.get("correct_language",False),body.get("neutral_gender",False)).validate(module)
        job=repository.enqueue(principal,document_id=uid(body.get("document_id")),module=module,
            idempotency_key=uid(body.get("idempotency_key")),options=options)
        return jsonify(job_id=job),202

    @app.get("/api/jobs/<uuid:job_id>")
    @protected()
    def status(principal,job_id):
        row=repository.job(principal,str(job_id))
        if not row:
            return jsonify(error="not_found"),404
        return jsonify(job_id=row[0],module=row[1],state=row[2],document_id=row[3])

    @app.get("/api/jobs/<uuid:job_id>/download")
    @protected()
    def download(principal,job_id):
        result=outputs.download(principal,str(job_id))
        if result is None:
            return jsonify(error="not_found"),404
        if result.requires_review and request.args.get("review")!="1":
            return jsonify(error="review_required",message="Download for human review, not external distribution."),409
        response=send_file(BytesIO(result.document),mimetype=DOCX,as_attachment=True,
            download_name="cv-review.docx" if result.requires_review else "cv.docx",conditional=False,max_age=0)
        response.headers["X-CV-Review-Required"]="1" if result.requires_review else "0"
        return response
