"""Opt-in staging composition of the original CV Studio single-CV view.

Only audited DOM fragments and fixed assets are served. Never serve the full
desktop shell, its script directory, or its desktop routes.
"""
from pathlib import Path
from copy import deepcopy
from flask import Blueprint, Response, send_file

ROOT=Path(__file__).resolve().parents[2]
FRONTEND=Path(__file__).resolve().parent
ASSETS={
    "app.css": ROOT/"vendor/cvstudio/app.css",
    "cv_client.js": FRONTEND/"cv_client.js",
    "existing_cv_controls.js": FRONTEND/"existing_cv_controls.js",
    "bootstrap.js": FRONTEND/"bootstrap.js",
    "provider_settings.js": FRONTEND/"provider_settings.js",
    "create_profile_cloud.js": FRONTEND/"create_profile_cloud.js",
    "reports_cloud.js": FRONTEND/"reports_cloud.js",
    "scoring_cloud.js": FRONTEND/"scoring_cloud.js",
    "batch_cloud.js": FRONTEND/"batch_cloud.js",
    "history_cloud.js": FRONTEND/"history_cloud.js",
    "account_cloud.js": FRONTEND/"account_cloud.js",
    "usage_cloud.js": FRONTEND/"usage_cloud.js",
}
NAV=("Format","Batch","JDAnon","Company","Appraiser","JACreate")
TAGS=frozenset("div span button svg path circle ellipse h2 label input textarea select option p b strong small".split())
ATTR=frozenset("id class style type title aria-label aria-hidden aria-pressed role disabled accept value placeholder for checked hidden multiple viewbox width height fill stroke stroke-width stroke-linecap stroke-linejoin d cx cy r rx ry".split())

def _one(source,key):
    matches=source.xpath(".//*[@id=$key]",key=key)
    if len(matches)!=1:
        raise ValueError("Original UI fragment missing or ambiguous")
    return matches[0]

def _clean(node):
    # Strict positive tag/attribute policy; no script, forms, URL-bearing
    # attributes, inline event handlers, or custom executable elements.
    for child in list(node):
        if not isinstance(child.tag,str) or child.tag.lower() not in TAGS:
            node.remove(child)
        else:
            _clean(child)
    for key in list(node.attrib):
        if key.lower() not in ATTR:
            del node.attrib[key]
    if "style" in node.attrib and any(x in node.attrib["style"].lower() for x in ("url(","@import","expression(","\\", "/*")):
        del node.attrib["style"]
    if node.tag=="button":
        node.set("type","button")
    return node

def render_shell(*,enable_batch=False,enable_scoring=False,enable_reports=False,enable_profile=False,enable_provider_settings=False,enable_history=False,enable_accounts=False,enable_usage=False):
    from lxml import html, etree
    source=html.parse(str(ROOT/"index.html"),parser=html.HTMLParser(no_network=True)).getroot()
    nav=deepcopy(_one(source,"pageTabs"))
    keep={"tab"+x for x in NAV if x!="JACreate" or enable_profile}
    for node in list(nav):
        if node.get("id") not in keep:
            nav.remove(node)
        else:
            enabled = {"tabFormat"}
            if enable_batch:
                enabled.add("tabBatch")
            if enable_scoring:
                enabled.add("tabAppraiser")
            if enable_reports:
                enabled.update(("tabCompany", "tabJDAnon"))
            if enable_profile:
                enabled.add("tabJACreate")
            if node.get("id") not in enabled:
                node.set("disabled","disabled")
                node.set("title","Staging integration pending")
            if node.get("id")=="tabAppraiser":
                node.set("class","page-tab")
                if enable_scoring:
                    node.attrib.pop("title", None)
                labels=node.xpath(".//span[@class='tab-label']")
                if len(labels)!=1:
                    raise ValueError("Original scoring label missing")
                labels[0].text="CV Scoring"
    view=deepcopy(_one(source,"viewFormat"))
    for key in ("progressWrap","singleAiQuickPanel","singleSummaryToggle","cvSingleFormattingReviewNotice","formatSummaryNote","btnJALogin","jaBar","cvFormattingReviewPanel"):
        node=_one(view,key)
        if key=="singleSummaryToggle":
            node=node.getparent()
        node.getparent().remove(node)
    for node in view.xpath(".//*[@data-cv-open-ready]"):
        node.getparent().remove(node)
    _one(view,"fileInput").set("accept",".pdf,.docx,.txt")
    _one(view,"fileInput").set("aria-label","Source CV file")
    _one(view,"cvInput").set("aria-label","Raw CV text")
    _one(view,"outputBox").set("role","status")
    for node in view.xpath(".//button"):
        if node.get("id") in {"btnFormat","btnBlind","btnDocx"}:
            node.set("disabled","disabled")
        if node.get("onclick")=="clearInput()":
            node.set("id","cloudClearInput")
    _clean(nav);_clean(view)
    # The original CSS and two-card input/output structure remain the source.
    # Pending modules are visible but disabled, not loaded as desktop scripts.
    shell=html.fromstring("""<html lang="en"><head><meta charset="UTF-8"><meta name="viewport" content="width=device-width, initial-scale=1"><title>CV Studio Cloud</title><link rel="stylesheet" href="/cloud-ui/assets/app.css"><script src="/cloud-ui/assets/cv_client.js" defer></script><script src="/cloud-ui/assets/existing_cv_controls.js" defer></script><script src="/cloud-ui/assets/bootstrap.js" defer></script></head><body><div class="app"><div class="header"><div><h1>CV Studio</h1><p>Cloud staging · fictional documents only</p></div><button id="cloudLogout" class="sec" type="button" style="display:none" hidden>Sign out</button></div><section class="card" id="cloudLoginPanel"><div class="card-head"><h2>Sign in</h2></div><div class="card-body"><form id="cloudLogin" method="post" action="/cloud-ui"><label>Organisation <input name="tenant" required autocomplete="organization" maxlength="63"></label><label>Email <input name="email" required type="email" autocomplete="username" maxlength="254"></label><label>Password <input name="password" required type="password" autocomplete="current-password" maxlength="256"></label><button type="submit" class="primary">Sign in</button></form></div></section><p id="cloudMessage" role="status" aria-live="polite"></p><div id="cloudContent" style="display:none"><div class="card" id="cloudJobOptions"><div class="card-body"><div class="btn-row"><label>CV alignment <select id="cloudAlignment"><option value="left">Left</option><option value="justify">Justify</option></select></label><label><input type="checkbox" id="cloudLanguage"> Correct spelling and grammar</label><label><input type="checkbox" id="cloudNeutral"> Gender-neutral blinded CV</label></div><p>Word download is available after processing. Structured preview, summary, batch and other module integration are pending.</p><div class="btn-row"><button class="sec" type="button" id="cloudRefresh">Refresh job status</button><button class="sec" type="button" id="cloudRecover">Recover unconfirmed submission</button></div></div></div></div></div></body></html>""")
    content=_one(shell,"cloudContent")
    content.insert(0,nav)
    content.append(view)
    if enable_batch:
        batch=deepcopy(_one(source,"viewBatch"))
        for key in ("batchAiQuickPanel","batchSummaryToggle","btnBatchDownload","batchTotalCost","batchTimer","batchJAStatus","batchJAConnBadge"):
            item=_one(batch,key)
            if key=="batchSummaryToggle":
                item=item.getparent()
            item.getparent().remove(item)
        for item in batch.xpath(".//*[@data-cv-open-ready]"):
            item.getparent().remove(item)
        for item in batch.xpath(".//button"):
            if item.get("onclick")=="clearBatch()":
                item.set("id","cloudBatchClear")
            if item.get("id")=="btnBatchRun":
                item.set("disabled","disabled")
        file_input=_one(batch,"batchFileInput")
        file_input.set("accept",".pdf,.docx,.txt")
        file_input.set("aria-label","Batch source CV files")
        drop=_one(batch,"batchDropZone")
        labels=drop.xpath(".//span[@class='dz-label']")
        subs=drop.xpath(".//span[@class='dz-sub']")
        if len(labels)!=1 or len(subs)!=1:
            raise ValueError("Batch drop-zone labels unavailable")
        labels[0].text="Select up to 10 files (PDF, DOCX, TXT)"
        subs[0].text="Click to browse or drop files; each has its own processing status"
        _one(batch,"batchSummary").set("role","status")
        _clean(batch)
        batch.set("style","display:none")
        content.append(batch)
        script=html.Element("script",src="/cloud-ui/assets/batch_cloud.js",defer="defer")
        bootstrap=shell.xpath(".//script[@src='/cloud-ui/assets/bootstrap.js']")[0]
        bootstrap.addprevious(script)
        options=content.xpath(".//*[@id='cloudJobOptions']//p")[0]
        options.text="Shared CV options apply when starting a batch. Each completed file is downloaded individually; structured preview and other modules are pending."
    if enable_scoring:
        scoring = deepcopy(_one(source, "viewAppraiser"))
        for key in ("appraiserRouteBadge", "appraiserAiQuickHint", "appraiserSalary",
                    "appraiserCopyBtn", "appraiserWordBtn", "appraiserPdfBtn", "appraiserBadge"):
            node = _one(scoring, key)
            if key in {"appraiserRouteBadge", "appraiserSalary"}:
                node = node.getparent()
            if key == "appraiserAiQuickHint":
                node = node.getparent().getparent()
            node.getparent().remove(node)
        for button in scoring.xpath(".//button[@onclick='clearAppraiser()']"):
            button.set("id", "cloudScoringClear")
        for kind in ("Cv", "Jd"):
            name = "Candidate CV" if kind == "Cv" else "Job description"
            file = _one(scoring, f"appraiser{kind}File")
            file.set("accept", ".txt,.pdf,.docx")
            file.set("aria-label", name + " file")
            _one(scoring, f"appraiser{kind}Text").set("aria-label", name + " text")
            drop = _one(scoring, f"appraiser{kind}Drop")
            drop.xpath(".//div[@class='appraiser-upload-sub']")[0].text = "PDF, DOCX or TXT"
        remarks = scoring.xpath(".//div[contains(@class, 'appraiser-remarks')]")[0]
        remarks.clear(keep_tail=True)
        remarks.set("class", "appraiser-panel appraiser-remarks")
        remarks.append(html.fromstring('<div><label for="cloudScoringRubric">Job requirements</label><p>Enter up to 30 job-related requirements copied from the JD, one per line. Review each requirement for fairness.</p><textarea id="cloudScoringRubric" class="appraiser-ta" maxlength="15030"></textarea></div>'))
        actions = scoring.xpath(".//div[@class='appraiser-actions']")[0]
        actions[0].text = "Assess documented evidence for each requirement. A recruiter reviews the results."
        _clean(scoring)
        output = _one(scoring, "appraiserOutput")
        output.set("style", "display:block")
        output[0][0].text = "Evidence report"
        output.append(html.fromstring('<div><p id="cloudScoringStatus" role="status"></p><label for="cloudScoringHistory">Recent assessments</label> <select id="cloudScoringHistory"></select><button id="cloudScoringLoad" type="button" class="sec">Load report</button></div>'))
        scoring.set("style", "display:none")
        content.append(scoring)
        bootstrap = shell.xpath(".//script[@src='/cloud-ui/assets/bootstrap.js']")[0]
        bootstrap.addprevious(html.Element("script", src="/cloud-ui/assets/scoring_cloud.js", defer="defer"))
    if enable_reports:
        for key in ("Company", "JDAnon"):
            view = deepcopy(_one(source, "view" + key))
            is_company = key == "Company"
            heading = view.xpath(".//div[@class='card-head']")[0]
            heading[1].text = ("Generate a profile from fictional research sources" if is_company
                               else "Remove employer identifiers and review the rewritten JD")
            quick = _one(view, "companyAiQuickHint" if is_company else "jdAnonAiQuickHint").getparent().getparent()
            quick.getparent().remove(quick)
            remove_buttons = [
                "copyCompanyProfile()", "exportCompanyDoc()", "exportCompanyPDF()",
                "copyAnonJD()", "exportAnonJDDoc()", "exportAnonJDPDF()",
            ]
            for button in view.xpath(".//button"):
                action = button.get("onclick")
                if action in remove_buttons or button.get("data-cv-open-ready") is not None or (
                    action in {"generateCompanyProfile()", "generateAnonJD()"} and button.get("id") is None
                ):
                    button.getparent().remove(button)
                elif action in {"clearCompanyProfile()", "clearAnonJD()"}:
                    button.set("id", "cloudClear" + key)
            if is_company:
                url = _one(view, "companyUrl").getparent().getparent()
                drop = _one(view, "companyDropZone")
                source_panel = drop.getparent()
                source_panel[0].text = "Company name"
                # Remove the desktop URL fetch and document import controls.
                for node in (url, drop.getprevious(), drop):
                    source_panel.remove(node)
                field = _one(view, "companyText")
                field.set("aria-label", "Company name")
                field.set("maxlength", "200")
                field.set("style", field.get("style").replace("240px", "52px"))
                context = _one(view, "companyContext").getparent()
                context.getparent().remove(context)
                target = _one(view, "companyOutput")
                cost = _one(view, "companyCost")
            else:
                field = _one(view, "anonRawText")
                field.set("aria-label", "Original job description")
                file = _one(view, "anonFileInput")
                file.set("accept", ".txt,.docx,.pdf")
                _one(view, "anonDropZone")[2].text = "PDF, DOCX or TXT"
                employer = _one(view, "anonCompanyName")
                employer.set("aria-label", "Employer name")
                employer.set("maxlength", "150")
                context = employer.getparent().getparent()
                for child in list(context):
                    if child is not context[0] and child is not employer.getparent():
                        context.remove(child)
                context.append(html.fromstring('<div><label for="cloudJDIdentifiers">Other identifiers to remove, one per line</label><textarea id="cloudJDIdentifiers"></textarea><label for="cloudJDTechnologies">Technologies to retain, one per line</label><textarea id="cloudJDTechnologies"></textarea></div>'))
                toolbar = _one(view, "anonPreviewModeVisual").getparent()
                toolbar.getparent().remove(toolbar)
                target = _one(view, "anonJDOutput")
                cost = _one(view, "anonJDCost")
            cost.getparent().remove(cost)
            target.getparent().insert(1, html.fromstring(f'<div><label for="cloudHistory{key}">Recent reports</label> <select id="cloudHistory{key}"></select><button id="cloudLoad{key}" class="sec" type="button">Load report</button></div>'))
            view.set("style", "display:none")
            content.append(_clean(view))
        bootstrap = shell.xpath(".//script[@src='/cloud-ui/assets/bootstrap.js']")[0]
        bootstrap.addprevious(html.Element("script", src="/cloud-ui/assets/reports_cloud.js", defer="defer"))
    if enable_profile:
        profile = deepcopy(_one(source, "viewJACreate"))
        note = profile.xpath(".//div[@class='card-body']/p")[0]
        note.clear()
        note.text = "Upload the fictional CV and review the extracted details. Confirm before creating a profile in mocked JobAdder."
        file = _one(profile, "jaCreateInput")
        file.set("accept", ".txt,.pdf,.docx")
        _one(profile, "jaCreateDrop")[2].text = "TXT, PDF or DOCX"
        _one(profile, "btnJACreateAll").text = "Confirm reviewed profiles"
        for button in profile.xpath(".//button[@onclick='clearJACreateQueue()']"):
            button.set("id", "cloudProfileClear")
        _one(profile, "jaCreateAllStatus").set("role", "status")
        panel = _one(profile, "jaCreateList")
        panel.addnext(html.fromstring('<div><button class="sec" id="cloudProfileHistory" type="button">Refresh JobAdder history</button><div id="cloudProfileAudit"></div></div>'))
        profile.set("style", "display:none")
        content.append(_clean(profile))
        bootstrap = shell.xpath(".//script[@src='/cloud-ui/assets/bootstrap.js']")[0]
        bootstrap.addprevious(html.Element("script", src="/cloud-ui/assets/create_profile_cloud.js", defer="defer"))
    if enable_provider_settings:
        # Reuse only the main AI card, not the desktop settings drawer or
        # integration cards. Model choices must come from the cloud server.
        pane=_one(source,"settingsPaneApi")
        card=deepcopy(_one(pane,"mainProviderSel").getparent())
        provider=_one(card,"mainProviderSel")
        model=_one(card,"modelSel")
        for select in (provider,model):
            for child in list(select):
                select.remove(child)
        for key in ("mainModelInput","btnTest"):
            item=_one(card,key)
            item.getparent().remove(item)
        save=card.xpath(".//button[@onclick='saveKey()']")
        if len(save)!=1:
            raise ValueError("Original save control unavailable")
        save[0].set("id","cloudProviderSave")
        save[0].text="Save / replace key"
        key=_one(card,"keyInput")
        key.set("aria-label","New organisation AI API key")
        for select,label in ((provider,"AI provider"),(model,"Approved AI model")):
            select.set("aria-label",label)
        _one(card,"mainProviderNote").set("role","status")
        _clean(card)
        key.set("autocomplete","new-password")
        key.set("maxlength","4096")
        for item in (provider,model,key,save[0]):
            item.set("disabled","disabled")
        panel=html.fromstring("""<section id="cloudProviderPanel" class="card" style="display:none"><div class="card-head"><h2>Settings · Main API Settings</h2><button id="cloudProviderClose" class="sec" type="button">Close</button></div><div class="card-body"><p>Organisation-wide AI configuration. Existing keys cannot be read back. Enter a new key when replacing settings.</p><div id="cloudProviderFields"></div><div class="btn-row"><button id="cloudProviderReload" type="button" class="sec">Refresh settings</button><button id="cloudProviderDisable" type="button" class="sec" disabled>Disable provider</button></div><p id="cloudProviderStatus" role="status" aria-live="polite"></p></div></section>""")
        _one(panel,"cloudProviderFields").append(card)
        settings=deepcopy(_one(source,"btnSettingsToggle"))
        _clean(settings)
        settings.set("id","cloudProviderToggle")
        settings.set("style",settings.get("style","")+";display:none")
        _one(shell,"cloudLogout").addprevious(settings)
        content.insert(1,panel)
        script=html.Element("script",src="/cloud-ui/assets/provider_settings.js",defer="defer")
        shell.xpath(".//script[@src='/cloud-ui/assets/bootstrap.js']")[0].addprevious(script)
    if enable_history:
        panel=html.fromstring("""<section class="card" id="cloudHistoryPanel" style="display:none"><div class="card-head"><h2>My processing history</h2><button type="button" class="sec" id="cloudHistoryClose">Close</button></div><div class="card-body"><p>Only your own records are shown. Uploaded files without a job are listed separately. Refresh to check current status; no job is resubmitted from this view.</p><div class="btn-row"><button type="button" class="sec" id="cloudHistoryJobs">CV jobs</button><button type="button" class="sec" id="cloudHistoryDocuments">Uploaded documents</button><button type="button" class="sec" id="cloudHistoryRefresh">Refresh</button><button type="button" class="sec" id="cloudHistoryNext" disabled>Older records</button></div><p role="status" aria-live="polite" id="cloudHistoryStatus"></p><div id="cloudHistoryList"></div></div></section>""")
        content.insert(1,panel)
        button=html.Element("button",id="cloudHistoryToggle",type="button")
        button.set("class","sec")
        button.set("style","display:none")
        button.text="My history"
        _one(shell,"cloudLogout").addprevious(button)
        script=html.Element("script",src="/cloud-ui/assets/history_cloud.js",defer="defer")
        shell.xpath(".//script[@src='/cloud-ui/assets/bootstrap.js']")[0].addprevious(script)
    if enable_accounts:
        panel=html.fromstring("""<section class="card" id="cloudAccountsPanel" style="display:none"><div class="card-head"><h2>Organisation users</h2><button type="button" class="sec" id="cloudAccountsClose">Close</button></div><div class="card-body"><p>Manage existing accounts and sessions. Account invitations and password resets are not available in this staging interface.</p><button type="button" class="sec" id="cloudAccountsRefresh">Refresh users</button><p id="cloudAccountsStatus" role="status" aria-live="polite"></p><div id="cloudAccountsList"></div></div></section>""")
        content.insert(1,panel)
        button=html.Element("button",id="cloudAccountsToggle",type="button")
        button.set("class","sec")
        button.set("style","display:none")
        button.text="Users"
        _one(shell,"cloudLogout").addprevious(button)
        script=html.Element("script",src="/cloud-ui/assets/account_cloud.js",defer="defer")
        shell.xpath(".//script[@src='/cloud-ui/assets/bootstrap.js']")[0].addprevious(script)
    if enable_usage:
        panel=html.fromstring("""<section class="card" id="cloudUsagePanel" style="display:none"><div class="card-head"><h2>Organisation AI expenditure</h2><button class="sec" type="button" id="cloudUsageClose">Close</button></div><div class="card-body"><p>Current cumulative internal ledger in USD, not a provider invoice or monthly allowance. Reserved funds include requests whose final charges may still be unknown.</p><button class="sec" type="button" id="cloudUsageRefresh">Refresh usage</button><p role="status" aria-live="polite" id="cloudUsageStatus"></p><div id="cloudUsageValues"></div></div></section>""")
        content.insert(1,panel)
        button=html.Element("button",id="cloudUsageToggle",type="button")
        button.set("class","sec")
        button.set("style","display:none")
        button.text="AI usage"
        _one(shell,"cloudLogout").addprevious(button)
        script=html.Element("script",src="/cloud-ui/assets/usage_cloud.js",defer="defer")
        shell.xpath(".//script[@src='/cloud-ui/assets/bootstrap.js']")[0].addprevious(script)
    return etree.tostring(shell,method="html",encoding="utf-8",doctype="<!DOCTYPE html>")

def register_existing_ui(app, *, enable_batch=False):
    # Only an explicitly configured staging app with real authenticated APIs
    # can mount this view. A health-only or auth-only app cannot mount it.
    rules={(r.rule,method) for r in app.url_map.iter_rules() for method in r.methods}
    required={("/api/auth/login","POST"),("/api/auth/me","GET"),("/api/auth/logout","POST"),("/api/documents","POST"),("/api/jobs","POST"),("/api/jobs/<uuid:job_id>","GET"),("/api/jobs/<uuid:job_id>/download","GET")}
    if "cvcloud_auth" not in app.extensions or not required.issubset(rules):
        raise ValueError("Authenticated CV services required before mounting existing UI")
    admin_required={("/api/admin/ai-provider","GET"),("/api/admin/ai-provider","POST"),("/api/admin/ai-provider/disable","POST")}
    history_required={("/api/jobs","GET"),("/api/documents","GET"),("/api/jobs/<uuid:job_id>/preview","GET")}
    accounts_required={("/api/admin/accounts","GET"),("/api/admin/accounts/<uuid:user_id>/actions","POST")}
    scoring_required={("/api/scoring/jobs","GET"),("/api/scoring/jobs","POST"),("/api/scoring/jobs/<uuid:job_id>","GET")}
    report_routes = {("/api/" + slug + "/jobs", method) for slug in ("company-profile", "blind-jd") for method in ("GET", "POST")}
    profile_routes = {("/api/create-profile/settings","GET"),("/api/create-profile/prepare","POST"),
                      ("/api/create-profile/jobs","POST"),("/api/create-profile/jobs","GET")}
    page=render_shell(enable_profile=profile_routes.issubset(rules),enable_reports=report_routes.issubset(rules),enable_batch=enable_batch,enable_scoring=scoring_required.issubset(rules),enable_provider_settings=admin_required.issubset(rules),
        enable_history=history_required.issubset(rules),enable_accounts=accounts_required.issubset(rules),enable_usage=("/api/admin/ai-usage","GET") in rules)
    bp=Blueprint("existing_cloud_ui",__name__)
    @bp.get("/cloud-ui")
    def index():
        response=Response(page,mimetype="text/html")
        response.headers["Content-Security-Policy"]="default-src 'none'; script-src 'self'; style-src 'self' 'unsafe-inline'; img-src 'self' data:; connect-src 'self'; form-action 'self'; base-uri 'none'; frame-ancestors 'none'"
        return response
    @bp.get("/cloud-ui/assets/<name>")
    def asset(name):
        from flask import abort
        if name not in ASSETS:
            abort(404)
        return send_file(ASSETS[name],conditional=False,max_age=0)
    @bp.after_request
    def headers(response):
        response.headers["Cache-Control"]="no-store"
        response.headers["X-Content-Type-Options"]="nosniff"
        response.headers["Referrer-Policy"]="no-referrer"
        return response
    app.register_blueprint(bp)
