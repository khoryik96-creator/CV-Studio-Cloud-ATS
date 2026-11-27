"""One trusted, claimed job: durable options → process → publish.

Cooperative continuous heartbeat and deadline checks are integrated.
Hard process deadlines, isolation and provider provisioning remain release gates. On any uncertain error, mark needs_review if the lease
is still valid. Never replay automatically or report success without output.
"""
from cloud.cv_job import execute_cv_job
from cloud.job_state import State
from cloud.worker_supervision import LeaseSupervisor

def run_claimed(*,principal,lease,repository,storage,workers,ledger,policy,transport,outputs,enable_ocr=False,heartbeat_interval=20,deadline=600):
    try:
        with LeaseSupervisor(lambda:workers.heartbeat(principal,lease),interval=heartbeat_interval,deadline=deadline) as supervisor:
            options=repository.options(principal,lease.job_id)
            if options is None:
                raise ValueError("Missing job options")
            result=execute_cv_job(principal=principal,lease=lease,repository=repository,storage=storage,
                workers=workers,ledger=ledger,policy=policy,transport=transport,
                alignment=options.alignment,correct_language=options.correct_language,
                neutral_gender=options.neutral_gender,enable_ocr=enable_ocr,check_supervisor=supervisor.check)
            supervisor.check()
            if not workers.heartbeat(principal,lease):
                raise ValueError("Lease lost before publication")
        # Stop heartbeat before terminal publication, otherwise a heartbeat
        # racing with a successful commit would misread success as lease loss.
        # Publication independently checks the unexpired token in SQL.
        outputs.publish(principal,lease,result)
        return True
    except Exception:
        # Deliberately avoid logging provider responses, CV contents or paths.
        # If the database is unreachable, expiry recovery will decide state.
        try:
            workers.finish(principal,lease,State.NEEDS_REVIEW)
        except Exception:
            pass
        return False
