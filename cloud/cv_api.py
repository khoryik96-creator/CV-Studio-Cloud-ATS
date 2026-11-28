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

def register(app,auth,cookie,same_origin,uploads,repository,outputs,*,enable_scoring=False,enable_reports=False,enable_blind_jd=False,create_profile=None):
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

    if enable_scoring:
        from cloud.scoring_contract import parse_rubric
        from cloud.scoring_jobs import reports as read_scoring_reports

        @app.post("/api/scoring/jobs")
        @protected(write=True)
        def submit_scoring(principal):
            request.max_content_length = 96 * 1024
            body = request.get_json(silent=True)
            if not isinstance(body, dict) or set(body) != {"document_id", "jd_document_id", "criteria", "idempotency_key"}:
                return jsonify(error="invalid_request"), 400
            job_id = repository.enqueue(principal, document_id=uid(body["document_id"]), module="cv_scoring",
                idempotency_key=uid(body["idempotency_key"]), scoring=(uid(body["jd_document_id"]), parse_rubric(body["criteria"])))
            return jsonify(job_id=job_id), 202

        @app.get("/api/scoring/jobs")
        @app.get("/api/scoring/jobs/<uuid:job_id>")
        @protected()
        def scoring_reports(principal, job_id=None):
            result = read_scoring_reports(repository, principal, str(job_id) if job_id is not None else None)
            if result is None:
                return jsonify(error="not_found"), 404
            return jsonify(result)

    if enable_reports or enable_blind_jd:
        from cloud.document_reports import MODULES, options as report_options, reports

        def register_report(module, route):
            @protected(write=True)
            def submit_report(principal):
                request.max_content_length = 96 * 1024
                body = request.get_json(silent=True)
                if not isinstance(body, dict) or set(body) != {"document_id", "options", "idempotency_key"}:
                    return jsonify(error="invalid_request"), 400
                job_id = repository.enqueue(principal, document_id=uid(body["document_id"]), module=module,
                    idempotency_key=uid(body["idempotency_key"]), report=report_options(module, body["options"]))
                return jsonify(job_id=job_id), 202

            @protected()
            def get_reports(principal, job_id=None):
                result = reports(repository, principal, module, str(job_id) if job_id is not None else None)
                if result is None:
                    return jsonify(error="not_found"), 404
                return jsonify(result)

            for path in (route, route + "/<uuid:job_id>"):
                app.add_url_rule(path, module + "_reports", get_reports, methods=["GET"])
            app.add_url_rule(route, module + "_submit", submit_report, methods=["POST"])

        for module, slug in MODULES.items():
            if enable_reports or module == "blind_jd":
                register_report(module, "/api/" + slug + "/jobs")

    if create_profile is not None:
        @app.get("/api/create-profile/settings")
        @protected()
        def profile_settings(principal):
            return jsonify(connected=bool(create_profile.settings(principal)), mode="synthetic")

        @app.post("/api/create-profile/prepare")
        @protected(write=True)
        def prepare_profile(principal):
            request.max_content_length = 4096
            body = request.get_json(silent=True)
            if not isinstance(body, dict) or set(body) != {"document_id"}:
                return jsonify(error="invalid_request"), 400
            return jsonify(create_profile.prepare(principal, uid(body["document_id"])))

        @app.post("/api/create-profile/jobs")
        @protected(write=True)
        def confirm_profile(principal):
            request.max_content_length = 4096
            body = request.get_json(silent=True)
            if (not isinstance(body, dict) or set(body) != {"document_id", "confirmed", "confirmation", "idempotency_key"}
                    or body["confirmed"] is not True):
                return jsonify(error="explicit_confirmation_required"), 400
            job_id = create_profile.confirm(principal, uid(body["document_id"]), uid(body["idempotency_key"]), body["confirmation"])
            return jsonify(job_id=job_id), 202

        @app.get("/api/create-profile/jobs")
        @app.get("/api/create-profile/jobs/<uuid:job_id>")
        @protected()
        def profile_reports(principal, job_id=None):
            return jsonify(create_profile.reports(principal, str(job_id) if job_id is not None else None))

        @app.post("/api/create-profile/jobs/<uuid:job_id>/reconcile")
        @protected(write=True)
        def reconcile_profile(principal, job_id):
            return jsonify(create_profile.reconcile(principal, str(job_id)))

    @app.get("/api/jobs")
    @app.get("/api/documents")
    @protected()
    def history(principal):
        if set(request.args)-{"limit","before"} or any(len(request.args.getlist(k))!=1 for k in request.args):
            return jsonify(error="invalid_request"),400
        limit=request.args.get("limit","25")
        if not limit.isascii() or not limit.isdecimal() or len(limit)>2 or str(int(limit))!=limit or not 1<=int(limit)<=50:
            return jsonify(error="invalid_request"),400
        before=request.args.get("before")
        if before is not None and len(before)!=36:
            return jsonify(error="invalid_request"),400
        kind="jobs" if request.path=="/api/jobs" else "documents"
        return jsonify(repository.history(principal,kind=kind,limit=int(limit),before=before))

    @app.get("/api/jobs/<uuid:job_id>")
    @protected()
    def status(principal,job_id):
        row=repository.job(principal,str(job_id),include_elapsed=True)
        if not row:
            return jsonify(error="not_found"),404
        return jsonify(job_id=row[0],module=row[1],state=row[2],document_id=row[3],elapsed_ms=row[4])

    @app.get("/api/jobs/<uuid:job_id>/preview")
    @protected()
    def preview(principal,job_id):
        from cloud.output_preview import preview_paragraphs,PreviewError
        result=outputs.download(principal,str(job_id))
        if result is None:
            return jsonify(error="not_found"),404
        if result.requires_review and request.args.get("review")!="1":
            return jsonify(error="review_required"),409
        try:
            paragraphs=preview_paragraphs(result.document)
        except PreviewError:
            return jsonify(error="preview_unavailable"),503
        return jsonify(job_id=str(job_id),requires_review=result.requires_review,paragraphs=paragraphs)

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
