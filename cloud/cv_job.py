"""Internal single-job orchestration, with lease and budget fences.

No scheduler or HTTP route. The caller must provide a trusted principal,
worker lease, verified storage metadata and configured server model policy.
Output bytes are returned for a future atomic result-persistence service.
"""
from cloud.private_storage import StoredObject
from cloud.file_extract import extract
from cloud.ai_dispatch import BudgetedCompletion
from cloud.cv_engine import process,Result

class JobExecutionError(ValueError):
    pass

def execute_cv_job(*,principal,lease,repository,storage,workers,ledger,policy,transport,
                   alignment="left",correct_language=False,neutral_gender=False,enable_ocr=False,check_supervisor=lambda:None):
    if lease.module not in ("cv_formatting","cv_blinding"):
        raise JobExecutionError("unsupported_job_module")
    def check():
        check_supervisor()
        if not workers.heartbeat(principal,lease):
            raise JobExecutionError("job_lease_lost")
        check_supervisor()
    check()
    job_row=repository.job(principal,lease.job_id)
    if not job_row or tuple(job_row)!=(lease.job_id,lease.module,"running",lease.document_id):
        raise JobExecutionError("job_lease_metadata_mismatch")
    row=repository.document(principal,lease.document_id)
    if not row or str(row[0])!=lease.document_id:
        raise JobExecutionError("document_not_found")
    _,media_type,size,digest=row
    raw=storage.read_verified(principal.tenant_id,principal.user_id,lease.document_id,StoredObject(size,digest,media_type))
    if type(enable_ocr) is not bool:
        raise JobExecutionError("invalid_ocr_option")
    ocr=None
    if enable_ocr:
        from cloud.ocr import read_pages
        ocr=lambda data,pages:read_pages(data,pages,keep_alive=check)
    extracted=extract(raw,media_type,ocr=ocr)
    check()
    completion=BudgetedCompletion(ledger,principal,lease,policy,transport)
    def complete(stage,system,user,limit):
        check()
        text=completion(stage,system,user,limit)
        check()
        return text
    result=process(extracted.text,complete=complete,blind=lease.module=="cv_blinding",alignment=alignment,
        correct_language=correct_language,neutral_gender=neutral_gender,source_levels=extracted.levels)
    check()
    if extracted.ocr_used:
        result=Result(result.document,True,result.warnings+("ocr_review_required",))
    # Do not mark succeeded before durable output publication and fenced commit.
    return result
