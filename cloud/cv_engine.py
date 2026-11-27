"""Cloud-only formatting/blinding engine; no desktop startup or network access.

The completion callback is supplied by a trusted budgeted worker. No live
provider is configured by this module. Rendered blind documents always require
human review: an exact-identity sweep is not a guarantee of anonymisation.
"""
from __future__ import annotations
from dataclasses import dataclass
from pathlib import Path
import copy
import io
import json
import math
import os
import re
import subprocess
import tempfile
import zipfile
from lxml import etree

from cloud import cv_pipeline as pipeline
from cloud.cv_outline import _merge_bullet_level_lists
from cvstudio_layout_parity import GUARDRAILS, steady, finish, blind_levels, _role_bullet_groups
from cvstudio_docx_repair import repair
from cvstudio_document_safety import validate_zip_payload
import cvstudio_blind_mask as blind_mask
import cvstudio_cv_normalize as normal

ROOT = Path(__file__).resolve().parents[1]
PROMPTS = Path(__file__).with_name("prompts")
MAX_SOURCE = 200_000
MAX_ANSWER_BYTES = 2_000_000
MAX_OUTPUT = 32 * 1024 * 1024
MAX_TOKENS = 32_000
TYPO_LINE = "- All text: fix spelling/typos silently, preserve everything else"

class EngineError(ValueError):
    pass

@dataclass(frozen=True, repr=False)
class Result:
    document: bytes
    requires_review: bool
    warnings: tuple[str,...]

def _prompt(name):
    return (PROMPTS / (name + ".txt")).read_text(encoding="utf-8").strip()

def parse_prompt(correct_language=False):
    prompt=_prompt("SYSTEM_PROMPT")
    if correct_language:
        if TYPO_LINE not in prompt:
            raise EngineError("language_instruction_unavailable")
        prompt=prompt.replace(TYPO_LINE,_prompt("CV_LANGUAGE_CORRECTION_INSTRUCTION"))
    return prompt

def blind_prompt(neutral_gender=False):
    prompt=_prompt("BLIND_SYSTEM_PROMPT")
    if neutral_gender:
        prompt += "\n\n" + _prompt("BLIND_CANDIDATE_GENDER_NEUTRALIZATION_INSTRUCTION")
    return prompt + GUARDRAILS

def _unique(pairs):
    out={}
    for key,value in pairs:
        if key in out or key.startswith("_"):
            raise EngineError("invalid_provider_object")
        out[key]=value
    return out

def _constant(_value):
    raise EngineError("invalid_provider_object")

def answer_json(text):
    if not isinstance(text,str) or len(text)>MAX_ANSWER_BYTES:
        raise EngineError("invalid_provider_response")
    try:
        if len(text.encode("utf-8"))>MAX_ANSWER_BYTES:
            raise EngineError("invalid_provider_response")
        clean=text.strip()
        if clean.startswith("```"):
            match=re.fullmatch(r"```(?:json)?\s*(.*?)\s*```",clean,re.S|re.I)
            if not match:
                raise EngineError("invalid_provider_response")
            clean=match.group(1)
        data=json.loads(clean,object_pairs_hook=_unique,parse_constant=_constant)
        stack=[(data,0)]
        count=0
        while stack:
            value,depth=stack.pop()
            count+=1
            if count>100_000 or depth>20:
                raise EngineError("provider_response_too_complex")
            if isinstance(value,dict):
                stack.extend((v,depth+1) for v in value.values())
            elif isinstance(value,list):
                stack.extend((v,depth+1) for v in value)
            elif isinstance(value,str):
                value.encode("utf-8")
            elif isinstance(value,float) and not math.isfinite(value):
                raise EngineError("invalid_provider_object")
        if not isinstance(data,dict) or not isinstance(data.get("candidate"),dict) or not isinstance(data.get("work_experiences"),list):
            raise EngineError("invalid_cv_structure")
        for field in ("summary_bullets","education","certifications","skills"):
            if field in data and not isinstance(data[field],list):
                raise EngineError("invalid_cv_structure")
        _role_bullet_groups(data)
        return data
    except (ValueError,TypeError,AttributeError,RecursionError,UnicodeError,OverflowError) as exc:
        if isinstance(exc,EngineError):
            raise
        raise EngineError("invalid_provider_response") from None

def prepare_source(text):
    if not isinstance(text,str) or not text.strip() or len(text)>MAX_SOURCE:
        raise EngineError("invalid_source_text")
    try:
        text.encode("utf-8")
    except UnicodeError:
        raise EngineError("invalid_source_text") from None
    kept=[]
    for line in text.splitlines():
        if line.strip() and normal._cv_strip_pay_from_summary_counted([line])[1]:
            continue
        kept.append(line)
    cleaned=pipeline.prepare_source("\n".join(kept))
    if not cleaned:
        raise EngineError("empty_source_text")
    return cleaned

def _safe_levels(levels):
    if levels is None:
        return []
    if not isinstance(levels,list) or len(levels)>20_000:
        raise EngineError("invalid_bullet_levels")
    out=[]
    for item in levels:
        if not isinstance(item,dict) or not isinstance(item.get("text"),str) or len(item["text"])>20_000 or type(item.get("level")) is not int or not 0<=item["level"]<=8:
            raise EngineError("invalid_bullet_levels")
        out.append({"text":item["text"],"level":item["level"]})
    return out

def render(data, *, alignment, levels):
    prepared=pipeline.prepare_export(data,alignment=alignment,bullet_levels=levels)
    # Do not inherit provider credentials or arbitrary NODE_OPTIONS.
    env={k:os.environ[k] for k in ("PATH","SystemRoot","WINDIR","TEMP","TMP","TMPDIR") if k in os.environ}
    with tempfile.TemporaryDirectory(prefix="cvcloud-render-") as tmp:
        payload,output=Path(tmp)/"input.json",Path(tmp)/"output.docx"
        payload.write_text(json.dumps(prepared,ensure_ascii=False,allow_nan=False),encoding="utf-8")
        try:
            run=subprocess.run(["node",str(ROOT/"generate.js"),str(payload),str(output),str(ROOT/"cloud"/"templates"/"hyplug.docx")],
                cwd=ROOT,env=env,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL,
                timeout=120,check=False)
            if run.returncode or not output.is_file() or not 1<=output.stat().st_size<=MAX_OUTPUT:
                raise EngineError("render_failed")
            raw=output.read_bytes()
            validate_zip_payload(raw,"generated document")
            result=repair(raw)
            if len(result)>MAX_OUTPUT:
                raise EngineError("render_output_too_large")
            validate_zip_payload(result,"generated document")
            with zipfile.ZipFile(io.BytesIO(result)) as archive:
                etree.fromstring(archive.read("word/document.xml"),etree.XMLParser(resolve_entities=False,no_network=True,load_dtd=False))
            return result
        except (OSError,subprocess.TimeoutExpired,ValueError,KeyError,zipfile.BadZipFile,etree.XMLSyntaxError) as exc:
            if isinstance(exc,EngineError):
                raise
            raise EngineError("render_failed") from None

def _word_text(raw):
    """Inspect text, XML attributes, properties and relationship URLs."""
    chunks=[]
    with zipfile.ZipFile(io.BytesIO(raw)) as archive:
        for entry in archive.infolist():
            if not entry.filename.lower().endswith((".xml",".rels")):
                continue
            if entry.file_size>20_000_000:
                raise EngineError("render_part_too_large")
            root=etree.fromstring(archive.read(entry),etree.XMLParser(resolve_entities=False,no_network=True,load_dtd=False))
            for node in root.iter():
                if not isinstance(node.tag,str):
                    continue
                if node.tag.endswith("}p"):
                    chunks.append((entry.filename,"".join(t.text or "" for t in node.iter() if isinstance(t.tag,str) and t.tag.rsplit("}",1)[-1] in ("t","delText","instrText"))))
                elif node.text and node.text.strip():
                    chunks.append((entry.filename,node.text))
                for key,value in node.attrib.items():
                    # ECMA-376 font Unicode/codepage bitmasks are fixed-width hex,
                    # not candidate contact fields. All other attributes are swept,
                    # including font names, relationship targets and document IDs.
                    w="{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"
                    if (entry.filename=="word/fontTable.xml" and node.tag==w+"sig"
                            and key in {w+n for n in ("usb0","usb1","usb2","usb3","csb0","csb1")}
                            and re.fullmatch(r"[0-9A-Fa-f]{8}",value)):
                        continue
                    chunks.append((entry.filename,value))
    return chunks

def _shape(value):
    return [[[(kind,len(items)) for kind,items in role] for role in exp]
            for exp in _role_bullet_groups(value)]

def blind_identity_findings(raw, original):
    candidate=original.get("candidate",{})
    # Keep paragraph and attribute boundaries: unrelated XML numbers must
    # not concatenate into a phone number. Normalize only harmless existing
    # generic-label grammar before comparing; never allowlist personal details.
    findings=set()
    for part,text in _word_text(raw):
        text=blind_mask._BLIND_LINK_SCHEME_LEFTOVER_RE.sub("[Link Redacted]",text)
        text=blind_mask._BLIND_HONORIFIC_LABEL_RE.sub("the candidate",text)
        text=blind_mask._BLIND_DOUBLED_ARTICLE_RE.sub("the candidate",text)
        text=blind_mask._BLIND_GENERIC_LABEL_SENTENCE_RE.sub(lambda m:m.group(1)+"The candidate",text)
        swept=blind_mask._blind_scrub_candidate_identity({"text":text},{"candidate":copy.deepcopy(candidate)})["text"]
        if swept!=text:
            # No content, candidate names, email addresses, or paths in findings.
            # Categories are fixed; only package-part type is exposed.
            kinds=[]
            for marker,label in (("[Email Redacted]","email"),("[Phone Redacted]","phone"),("[Link Redacted]","link")):
                if swept.count(marker)>text.count(marker):
                    kinds.append(label)
            area="properties" if part.startswith("docProps/") else "relationships" if part.endswith(".rels") else "body" if part=="word/document.xml" else "other_xml"
            findings.update((area,kind) for kind in (kinds or ["name_or_identifier"]))
    return tuple(sorted(findings))

def verify_blind_identity(raw, original):
    if blind_identity_findings(raw,original):
        raise EngineError("blind_identity_check_failed")

def process(source_text, *, complete, blind=False, alignment="left",
            correct_language=False, neutral_gender=False, source_levels=None):
    """Run bounded parse, optional anonymisation and actual Word rendering.

    complete(stage, system, user, max_tokens) is an injected trusted callable.
    The caller must reserve budget before dispatch and reconcile actual usage.
    """
    if alignment not in ("left","justify") or any(type(v) is not bool for v in (blind,correct_language,neutral_gender)):
        raise EngineError("invalid_processing_options")
    if neutral_gender and not blind:
        raise EngineError("gender_option_requires_blinding")
    source=prepare_source(source_text)
    levels=_safe_levels(source_levels)
    parsed=answer_json(complete("parse",parse_prompt(correct_language),source,MAX_TOKENS))
    try:
        checked=pipeline.postprocess_parse(parsed,source,preserve_source_summary=blind,correct_language=correct_language)
        cv=checked["data"]
        levels=_merge_bullet_level_lists(levels,checked.get("bullet_levels"))
        warnings=["source_fidelity_review"] if not checked.get("fidelity",{}).get("ok") else []
        original=copy.deepcopy(cv)
        if blind:
            prepared=blind_mask._blind_prepare_summary_bullets(copy.deepcopy(cv))
            if isinstance(prepared.get("summary_bullets"),list):
                prepared["summary_bullets"]=normal._cv_strip_pay_from_summary(prepared["summary_bullets"])
            request="Anonymise this parsed CV JSON:\n\n"+json.dumps(prepared,ensure_ascii=False,allow_nan=False)
            value=answer_json(complete("blind",blind_prompt(neutral_gender),request,MAX_TOKENS))
            cv=finish(pipeline.postprocess_blind(steady(value,prepared),prepared))
            if _shape(prepared)!=_shape(cv):
                raise EngineError("blind_structure_changed")
            levels=blind_levels(levels,prepared,cv)
            warnings.append("human_anonymisation_review_required")
        document=render(cv,alignment=alignment,levels=levels)
        if blind:
            verify_blind_identity(document,original)
            verify_blind_identity(document,parsed)
        return Result(document, bool(warnings), tuple(warnings))
    except EngineError:
        raise
    except (ValueError,TypeError,KeyError,AttributeError,RecursionError,OverflowError,etree.XMLSyntaxError,zipfile.BadZipFile) as exc:
        raise EngineError("cv_processing_checks_failed") from None
