"""Offline fictional research and report completion for the interactive stack."""

import json

from cloud import blind_jd_contract, company_profile_contract
from cloud.ai_dispatch import Completion

COMPANY = "Fictional Harbour Labs"
FACT = "Fictional Harbour Labs makes monitoring tools for small logistics teams."
SOURCE = company_profile_contract.Source(
    "overview", "Fictional company overview", FACT, "https://research.example.test/harbour-overview"
)

BLIND_JD = {
    "job_title": "Cloud Operations Engineer",
    "about_client": "",
    "about_role": "Maintain cloud monitoring and document recovery procedures.",
    "industry": "",
    "work_mode": "",
    "location": "",
    "tech_stack": ["Ansible"],
    "responsibilities": [
        "Maintain cloud monitoring and document recovery procedures.",
        "Automate recovery checks with Ansible.",
    ],
    "requirements": ["Two years of infrastructure operations experience required."],
    "nice_to_have": [],
    "why_join": [],
    "alt_titles": [],
}


def research(company_name):
    if company_name != COMPANY:
        raise ValueError("synthetic_company_only")
    return (SOURCE,)


def completion(jd_source):
    jd_system, _ = blind_jd_contract.prepare(jd_source, identifiers=[COMPANY], technologies=["Ansible"])
    company_system, _ = company_profile_contract.prepare(COMPANY, (SOURCE,))

    def fake(system, prompt):
        data = json.loads(prompt)
        if system == jd_system and data["source"] == jd_source:
            report = BLIND_JD
        elif system == company_system and data["company_name"] == COMPANY:
            report = {
                "claims": [{"section": "overview", "text": FACT,
                            "evidence": [{"source_id": SOURCE.id, "quote": FACT}]}],
                "limitations": ["Only the fictional company overview was supplied."],
            }
        else:
            raise ValueError("synthetic_report_only")
        return Completion(json.dumps(report), 100, 100)

    return fake
