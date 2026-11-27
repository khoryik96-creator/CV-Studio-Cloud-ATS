"""HyPlug CV layout parity: pure helpers, no app startup or credentials."""
from __future__ import annotations
import copy
import re
from typing import Any
from cvstudio_cv_normalize import _CV_LEADING_BULLET_MARKER_RE

def _cv_bullet_match_key(text):
    """Normalize a bullet for source<->parsed matching, mirrored in generate.js.

    Strips the same leading marker/enumerator the formatter strips for display
    (_CV_LEADING_BULLET_MARKER_RE) and lowercases, so a level looked up from the
    raw source bullet matches the rendered (already-stripped) bullet text.
    """
    value = re.sub(r"\s+", " ", str(text or "")).strip()
    for _ in range(5):
        stripped = _CV_LEADING_BULLET_MARKER_RE.sub("", value, count=1).strip()
        if stripped == value:
            break
        value = stripped
    return value.lower()

def _extract_docx_bullet_levels(file_bytes):
    """Map nested list paragraphs to their indent level.

    Word stores list nesting in w:numPr/w:ilvl, which the plain-text extraction
    discards. This side-channel lets the renderer restore the indent
    deterministically by matching parsed bullet text back to its source level.
    A CV often sets a list level's indent by hand (level 3 drawn as shallow as
    level 0, its own sub-points deeper), so within each run of list
    paragraphs the level is the rank of the bullet's indent on the page: the
    shallowest is 0, the next 1, and so on.
    Only levels >= 1 are recorded; every unmatched bullet renders at level 0.
    """
    import io as _io
    import docx as _docx
    from docx.oxml.ns import qn
    out = []
    seen = set()
    try:
        doc = _docx.Document(_io.BytesIO(file_bytes))
    except Exception:
        return out
    numbering = _list_level_indents(doc)

    def indent_of(p, num_id, level):
        own = p.xpath("./w:pPr/w:ind/@w:left") or p.xpath("./w:pPr/w:ind/@w:start")
        if own:
            try:
                return int(own[0])
            except (TypeError, ValueError):
                pass
        found = numbering.get((num_id, level))
        return found if found is not None else 720 * (level + 1)

    # Read as an outline: a bullet deeper than the one before it is a level
    # below it; one as deep (within 150 twips, including manual 359 vs numbering 360) is a sibling; a shallower one goes
    # back up. A paragraph that is not a list item, or a list item styled as
    # a heading, starts afresh.
    stack = []
    for p in doc.element.body.iter(qn("w:p")):
        ilvl_vals = p.xpath("./w:pPr/w:numPr/w:ilvl/@w:val")
        num_vals = p.xpath("./w:pPr/w:numPr/w:numId/@w:val")
        style = (p.xpath("./w:pPr/w:pStyle/@w:val") or [""])[0].lower()
        text = "".join(node.text or "" for node in p.iter(qn("w:t"))).strip()
        if (not ilvl_vals and not num_vals) or style.startswith("heading"):
            if text:
                stack = []
            continue
        if not text:
            continue
        try:
            raw = int(ilvl_vals[0]) if ilvl_vals else 0
        except (TypeError, ValueError):
            continue
        ind = indent_of(p, num_vals[0] if num_vals else "", raw)
        while stack and ind <= stack[-1] + 150:
            stack.pop()
        level = len(stack)
        stack.append(ind)
        if level < 1:
            continue
        key = _cv_bullet_match_key(text)
        if not key:
            continue
        dedup = (key, level)
        if dedup in seen:
            continue
        seen.add(dedup)
        out.append({"text": key, "level": min(level, 8)})
    return out


def _list_level_indents(doc):
    """(numId, level) -> the left indent (twips) Word's numbering gives it."""
    from docx.oxml.ns import qn
    out = {}
    try:
        root = doc.part.numbering_part.element
    except Exception:
        return out

    def left(ppr):
        ind = ppr.find(qn("w:ind")) if ppr is not None else None
        value = None if ind is None else (ind.get(qn("w:left")) or ind.get(qn("w:start")))
        try:
            return int(value) if value is not None else None
        except ValueError:
            return None

    abstract = {}
    for a in root.iter(qn("w:abstractNum")):
        for lvl in a.iter(qn("w:lvl")):
            ind = left(lvl.find(qn("w:pPr")))
            if ind is not None:
                try:
                    abstract[(a.get(qn("w:abstractNumId")), int(lvl.get(qn("w:ilvl"))))] = ind
                except (TypeError, ValueError):
                    pass
    for num in root.iter(qn("w:num")):
        ref = num.find(qn("w:abstractNumId"))
        aid = ref.get(qn("w:val")) if ref is not None else None
        for (a, level), ind in abstract.items():
            if a == aid:
                out[(num.get(qn("w:numId")), level)] = ind
    return out

GUARDRAILS = (
    "\n\nSTRUCTURE AND MASKING GUARDRAILS (these override nothing above; they make it exact):\n"
    "- Return every work experience, role and bullet in the same order and the same number. "
    'A bullet object with a "heading" and its own "bullets" stays such an object: never turn its '
    "heading into a bullet, never merge a heading into the bullet after it, never merge or split "
    "roles or work experiences.\n"
    '- Copy every job title (role "title" and candidate "current_position") and every "date_range" '
    "exactly as given, character for character, except an organisation, brand, school or person "
    "named in one, which you mask as usual.\n"
    '- Use "[Company]" only where an organisation or brand name stood. Never put it in place of '
    'ordinary words ("company codes", "insurance"), tax or business terms (GST, TDS, TCS, VAT), '
    "or a technology or product that does not reveal the employer."
)


def _words(value: Any) -> list[str]:
    """A text's words, without punctuation or case: "Lead, GST." -> ["lead", "gst"]."""
    return re.findall(r"[^\W_]+", str(value or "").casefold())


def same_words(given: Any, made: Any) -> bool:
    """Whether the AI kept the given text word for word (only punctuation,
    capitals or spacing may differ). Pure: unit tested."""
    words = _words(given)
    return bool(words) and words == _words(made)


def steady(answer: dict[str, Any], prepared: dict[str, Any]) -> dict[str, Any]:
    """The AI's anonymised CV with the given titles and dates kept (see above)."""
    out = copy.deepcopy(answer)

    def keep(target: dict[str, Any], source: dict[str, Any], key: str) -> None:
        given = source.get(key)
        if isinstance(given, str) and same_words(given, target.get(key)):
            target[key] = given

    if isinstance(out.get("candidate"), dict) and isinstance(prepared.get("candidate"), dict):
        keep(out["candidate"], prepared["candidate"], "current_position")
    given_exps, made_exps = prepared.get("work_experiences") or [], out.get("work_experiences") or []
    if (
        not isinstance(given_exps, list)
        or not isinstance(made_exps, list)
        or len(given_exps) != len(made_exps)
    ):
        return out  # not one for one: CV Studio's checks decide
    for given, made in zip(given_exps, made_exps, strict=True):
        if not isinstance(given, dict) or not isinstance(made, dict):
            continue
        keep(made, given, "date_range")
        given_roles, made_roles = given.get("roles") or [], made.get("roles") or []
        if (
            isinstance(given_roles, list)
            and isinstance(made_roles, list)
            and len(given_roles) == len(made_roles)
        ):
            for given_role, made_role in zip(given_roles, made_roles, strict=True):
                if isinstance(given_role, dict) and isinstance(made_role, dict):
                    keep(made_role, given_role, "title")
                    keep(made_role, given_role, "date_range")
    return out


def finish(cv: dict[str, Any]) -> dict[str, Any]:
    """The checked blind CV, ready to render: jobs kept apart, headings tidy."""
    out = copy.deepcopy(cv)
    for exp in out.get("work_experiences") or []:
        if not isinstance(exp, dict):
            continue
        exp["_keep_apart"] = True
        for role in exp.get("roles") or []:
            for item in (role.get("bullets") or []) if isinstance(role, dict) else []:
                if isinstance(item, dict) and isinstance(item.get("heading"), str):
                    item["heading"] = item["heading"].rstrip().rstrip(":").rstrip()
    return out


def _role_bullet_groups(cv):
    """Require matching experience, role and heading-group shape for mapping."""
    out = []
    for exp in cv.get("work_experiences") or []:
        roles = []
        for role in exp.get("roles") or []:
            entries = []
            for item in role.get("bullets") or []:
                if isinstance(item, str):
                    entries.append(("line", [item]))
                elif isinstance(item, dict) and isinstance(item.get("bullets"), list) and all(isinstance(x, str) for x in item["bullets"]):
                    entries.append(("group", item["bullets"]))
                else:
                    raise ValueError("Unsupported bullet structure")
            roles.append(entries)
        out.append(roles)
    return out


def blind_levels(levels, prepared, blinded):
    """Carry source indentation through a one-for-one anonymisation.
    
    A text-keyed renderer cannot disambiguate duplicate text at different
    depths. Do not assign a new depth when an output key is ambiguous.
    """
    original = [e for e in levels if isinstance(e, dict)] if isinstance(levels, list) else []
    if not isinstance(prepared, dict) or not isinstance(blinded, dict):
        return original
    try:
        before, after = _role_bullet_groups(prepared), _role_bullet_groups(blinded)
        shape = lambda exps: [[[(kind, len(items)) for kind, items in role] for role in exp] for exp in exps]
        if shape(before) != shape(after):
            return original
        by_key = {}
        for e in original:
            k = _cv_bullet_match_key(e.get("text"))
            try:
                depth = max(0, min(8, int(e.get("level") or 0)))
            except (TypeError, ValueError):
                continue
            if k:
                by_key[k] = max(depth, by_key.get(k, 0))
        mapped = {}
        source_keys = set()
        for ex1, ex2 in zip(before, after):
            for role1, role2 in zip(ex1, ex2):
                for (_, b1), (_, b2) in zip(role1, role2):
                    for src, dst in zip(b1, b2):
                        src_key, dst_key = _cv_bullet_match_key(src), _cv_bullet_match_key(dst)
                        source_keys.add(src_key)
                        if dst_key:
                            mapped.setdefault(dst_key, set()).add(by_key.get(src_key, 0))
        out = [e for e in original if _cv_bullet_match_key(e.get("text")) not in source_keys and _cv_bullet_match_key(e.get("text")) not in mapped]
        out.extend({"text": k, "level": next(iter(depths))} for k, depths in mapped.items() if len(depths) == 1 and next(iter(depths)) > 0)
        return out
    except (AttributeError, TypeError, ValueError):
        return original
