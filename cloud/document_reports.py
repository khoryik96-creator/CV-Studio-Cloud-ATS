"""Durable Blind JD and source-grounded Company Profile workflows."""

from cloud import blind_jd_contract as blind_jd, company_profile_contract as company
from cloud.ai_dispatch import BudgetedCompletion
from cloud.cv_engine import answer_json
from cloud.job_state import State
from cloud.report_storage import publish, read_document
from cloud.worker_supervision import LeaseSupervisor

MODULES = {"blind_jd": "blind-jd", "company_profile": "company-profile"}


def options(module, value):
    if not isinstance(value, dict):
        raise ValueError("invalid_report_options")
    if module == "blind_jd":
        if set(value) != {"identifiers", "technologies"}:
            raise ValueError("invalid_report_options")
        if not value["identifiers"]:
            raise ValueError("employer_identifier_required")
        # Validate the option shape independently of whether these terms occur in the uploaded JD.
        for terms in value.values():
            if not isinstance(terms, list) or len(terms) > 100 or any(
                not isinstance(term, str) or not term.strip() or len(term) > 150 for term in terms
            ):
                raise ValueError("invalid_report_terms")
    elif module == "company_profile":
        choices = {"focus": {"general", "tech", "culture", "finance"},
                   "length": {"concise", "standard", "detailed"},
                   "tone": {"professional", "conversational", "punchy"}}
        if set(value) != set(choices) or any(
            not isinstance(value[key], str) or value[key] not in allowed for key, allowed in choices.items()
        ):
            raise ValueError("invalid_report_options")
    else:
        raise ValueError("unsupported_report")
    return value


def run_claimed(*, principal, lease, repository, storage, workers, ledger, policy, transport, research):
    try:
        with LeaseSupervisor(lambda: workers.heartbeat(principal, lease), interval=20, deadline=600) as supervisor:
            with repository.scoped(principal) as (conn, tenant, owner):
                row = conn.execute("""SELECT report_options FROM cvcloud.jobs
                    WHERE tenant_id=%s AND owner_id=%s AND id=%s AND document_id=%s AND module=%s
                    AND state='running' AND lease_token=%s AND lease_until>clock_timestamp()""",
                    (tenant, owner, lease.job_id, lease.document_id, lease.module, lease.token)).fetchone()
            if not row:
                raise ValueError("invalid_report_lease")
            request_options = options(lease.module, row[0])
            source = read_document(repository, storage, principal, lease.document_id)
            supervisor.check()
            completion = BudgetedCompletion(ledger, principal, lease, policy, transport)
            if lease.module == "blind_jd":
                system, user = blind_jd.prepare(source, **request_options)
                raw = completion("anonymise_jd", system, user, 8192)
                result = blind_jd.validate(answer_json(raw, cv_structure=False), source, **request_options)
            else:
                company_name = source.strip()
                sources = research(company_name)
                system, user = company.prepare(company_name, sources, **request_options)
                supervisor.check()
                raw = completion("company_profile", system, user, 8192)
                result = company.validate(answer_json(raw, cv_structure=False), company_name, sources)
            supervisor.check()
            if not workers.heartbeat(principal, lease):
                raise ValueError("report_lease_lost")
        publish(repository, principal, lease, result)
        return True
    except Exception:
        try:
            workers.finish(principal, lease, State.NEEDS_REVIEW)
        except Exception:
            pass
        return False


def reports(repository, principal, module, job_id=None):
    with repository.scoped(principal) as (conn, tenant, owner):
        scope = """FROM cvcloud.jobs j
            JOIN cvcloud.users u ON (u.tenant_id,u.id)=(j.tenant_id,j.owner_id)
            JOIN cvcloud.tenants t ON t.id=j.tenant_id
            WHERE j.tenant_id=%s AND j.owner_id=%s AND j.module=%s
            AND j.report_options IS NOT NULL AND u.active AND t.active"""
        params = tenant, owner, module
        if job_id is None:
            rows = conn.execute("SELECT j.id::text, j.state, j.created_at " + scope +
                                " ORDER BY j.created_at DESC, j.id DESC LIMIT 25", params).fetchall()
            return {"items": [{"job_id": jid, "state": state, "created_at": created.isoformat()}
                              for jid, state, created in rows]}
        row = conn.execute("SELECT j.id::text, j.state, j.report_result " + scope + " AND j.id=%s",
                           (*params, job_id)).fetchone()
        if row is not None:
            return {"job_id": row[0], "state": row[1], "result": row[2]}
