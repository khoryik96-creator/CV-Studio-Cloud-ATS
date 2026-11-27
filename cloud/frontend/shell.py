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
    "batch_cloud.js": FRONTEND/"batch_cloud.js",
}
NAV=("Format","Batch","JDAnon","Company","Appraiser")
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

def render_shell(*,enable_batch=False,enable_provider_settings=False):
    from lxml import html, etree
    source=html.parse(str(ROOT/"index.html"),parser=html.HTMLParser(no_network=True)).getroot()
    nav=deepcopy(_one(source,"pageTabs"))
    keep={"tab"+x for x in NAV}
    for node in list(nav):
        if node.get("id") not in keep:
            nav.remove(node)
        else:
            if node.get("id")!="tabFormat" and not (enable_batch and node.get("id")=="tabBatch"):
                node.set("disabled","disabled")
                node.set("title","Staging integration pending")
            if node.get("id")=="tabAppraiser":
                node.set("class","page-tab")
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
    return etree.tostring(shell,method="html",encoding="utf-8",doctype="<!DOCTYPE html>")

def register_existing_ui(app, *, enable_batch=False):
    # Only an explicitly configured staging app with real authenticated APIs
    # can mount this view. A health-only or auth-only app cannot mount it.
    rules={(r.rule,method) for r in app.url_map.iter_rules() for method in r.methods}
    required={("/api/auth/login","POST"),("/api/auth/me","GET"),("/api/auth/logout","POST"),("/api/documents","POST"),("/api/jobs","POST"),("/api/jobs/<uuid:job_id>","GET"),("/api/jobs/<uuid:job_id>/download","GET")}
    if "cvcloud_auth" not in app.extensions or not required.issubset(rules):
        raise ValueError("Authenticated CV services required before mounting existing UI")
    admin_required={("/api/admin/ai-provider","GET"),("/api/admin/ai-provider","POST"),("/api/admin/ai-provider/disable","POST")}
    page=render_shell(enable_batch=enable_batch,enable_provider_settings=admin_required.issubset(rules))
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
