"""Cloud product scope; disabled modules are retained in the legacy source."""
from dataclasses import dataclass

@dataclass(frozen=True)
class Module:
    key: str
    selected: bool
    description: str

MODULES = (
    Module("cv_formatting", True, "Format and export CVs"),
    Module("cv_blinding", True, "Anonymise CVs"),
    Module("cv_scoring", True, "Evaluate against job requirements"),
    Module("company_profile", True, "Company profile research"),
    Module("blind_jd", True, "Anonymise job descriptions"),
    Module("create_profile", True, "Create a reviewed JobAdder candidate profile"),
    Module("jd_generation", False, "Pending product decision"),
    Module("salary_comparison", False, "Preserved"),
    Module("linkedin_sourcer", False, "Preserved"),
    Module("job_leads", False, "Preserved"),
    Module("lead_finder", False, "Preserved"),
    Module("email_verifier", False, "Preserved"),
    Module("jobadder", False, "Preserved"),
    Module("apollo", False, "Preserved"),
    Module("outlook", False, "Preserved"),
    Module("onenote", False, "Preserved"),
    Module("desktop_install_update", False, "Preserved"),
)

SELECTED_MODULES = frozenset(m.key for m in MODULES if m.selected)
# Selected means approved scope, NOT permission to serve a route.
# No document processing route can be exposed until auth and isolation land.
