# CV Studio Cloud ATS

Cloud migration of CV Studio, retaining its familiar interface and these five selected modules: CV Formatting, CV Blinding, CV Scoring, Company Profile and Blind JD. Other modules remain in source but must not be exposed by the cloud application. This is a development repository, not a production-ready service.

## Start here

- [Master cloud roadmap and current milestones](https://github.com/khoryik96-creator/CV-Studio-Cloud-ATS/issues/9)
- [Contributor rules](AGENTS.md) and [legacy collaboration context](HANDOFF.md)
- [Cloud foundation](docs/CLOUD_FOUNDATION.md), [authentication](docs/CLOUD_AUTH.md), [storage and jobs](docs/CLOUD_STORAGE_JOBS.md), [AI foundation](docs/CLOUD_AI_FOUNDATION.md)
- [CV engine](docs/CLOUD_CV_ENGINE.md), [DeepSeek and extraction](docs/CLOUD_DEEPSEEK_FILE_PROCESSING.md), [OCR and outputs](docs/CLOUD_OCR_OUTPUTS.md), [authenticated workflow](docs/CLOUD_CV_WORKFLOW.md), [worker supervision](docs/CLOUD_WORKER_SUPERVISION.md)
- [Formatting notes](FORMATTING_NOTES.md), [source-fidelity guardrails](CV_SOURCE_CHECK_GUARDRAILS.md), [template parity](docs/CLOUD_TEMPLATE_PARITY.md)

## Retained legacy reference and validation

The desktop source baseline is tracked in [VERSION](VERSION). [Desktop QA record](docs/QA.md), [backburner and diagnostics reference](BACKBURNER_ROADMAP.md), [protected build guide](owner_build_tools/PROTECTED_BUILD_GUIDE.md), and the notes for [Job Leads](JOB_LEADS_NOTES.md), [LinkedIn Sourcer](LINKEDIN_SOURCER_NOTES.md) and [Email Verifier](EMAIL_VERIFIER_NOTES.md) are retained for preserved source and regression checks, not active cloud product scope.

## Historical plans (removed from current tree)

The following superseded desktop planning files remain available at the immutable [pre-cleanup snapshot](https://github.com/khoryik96-creator/CV-Studio-Cloud-ATS/tree/5595bb61a42d9bd2af5fc39f403fc25b4fd6d8b4):

- [FRONTEND_ROADMAP.md](https://github.com/khoryik96-creator/CV-Studio-Cloud-ATS/blob/5595bb61a42d9bd2af5fc39f403fc25b4fd6d8b4/FRONTEND_ROADMAP.md)
- [IMPLEMENT.md](https://github.com/khoryik96-creator/CV-Studio-Cloud-ATS/blob/5595bb61a42d9bd2af5fc39f403fc25b4fd6d8b4/IMPLEMENT.md)
- [PHASE_STATUS.md](https://github.com/khoryik96-creator/CV-Studio-Cloud-ATS/blob/5595bb61a42d9bd2af5fc39f403fc25b4fd6d8b4/PHASE_STATUS.md)
- [ROADMAP.md](https://github.com/khoryik96-creator/CV-Studio-Cloud-ATS/blob/5595bb61a42d9bd2af5fc39f403fc25b4fd6d8b4/ROADMAP.md)

Earlier version-specific desktop reports also remain in the [original desktop archive](https://github.com/khoryik96-creator/CV_Studio_Main/tree/24d77eaf07d09cf09cb6e07f391bb112ffe70a71).

Use the roadmap and PRs for current evidence. Do not create per-release root Markdown reports. Do not deploy, use live candidate data or make paid requests until release gates and explicit owner approval are satisfied.
