"""Outline label inference from HyPlug's portable CV Studio engine."""
import re
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



_ROMAN_RE = re.compile(r"^[ivxlcdm]+$", re.I)



_LABEL_PAREN_RE = re.compile(r"^\((?P<body>[ivxlcdm]{1,7}|[a-z]|\d{1,3})\)", re.I)



_LABEL_NUM_RE = re.compile(
    r"^(?P<body>\d{1,3})(?:[.)](?=\s|[^\W\d_])|-(?=\s))"
)



_LABEL_BARE_RE = re.compile(
    r"^(?P<body>(?:[a-z]|[ivxlcdm]{2,7}))(?P<punct>[.)-])(?=\s)"
)



def _label_body_kind(body):
    if body.isdigit():
        return "digit"
    if len(body) > 1 and _ROMAN_RE.match(body):
        return "roman"
    return "alpha"



def _bullet_label_style(text):
    """Classify a leading outline label into a style key, or None.

    Restricted to the label forms the formatter actually strips
    (_CV_LEADING_BULLET_MARKER_RE). Keeping classification and stripping in
    lockstep means a nested item's label is both removed AND counted -- never one
    without the other. A plain glyph or unlabeled line returns None (base level).
    """
    s = str(text or "").lstrip()
    m = _LABEL_PAREN_RE.match(s)
    if m:
        return ("paren", _label_body_kind(m.group("body")))
    m = _LABEL_NUM_RE.match(s)
    if m:
        return ("num", "digit")
    m = _LABEL_BARE_RE.match(s)
    if m:
        return ("bare", _label_body_kind(m.group("body")))
    return None



def _infer_outline_levels(texts):
    """Infer a nesting level per bullet from the sequence of outline labels.

    Appearance-order stack: an unlabeled line is level 0 and resets the outline;
    the first labelled style below it is level 1; a new deeper style nests one
    level further; returning to a seen style pops back to that level. Mirrors
    cvInferLevelsForSequence in index.html.
    """
    levels = []
    stack = []
    for text in texts:
        style = _bullet_label_style(text)
        if style is None:
            stack = []
            levels.append(0)
        elif style in stack:
            idx = stack.index(style)
            del stack[idx + 1:]
            levels.append(idx + 1)
        else:
            stack.append(style)
            levels.append(len(stack))
    return levels



def _infer_label_bullet_levels(cv_data):
    """Outline-label nesting levels for a parsed CV's role bullets.

    Runs _infer_outline_levels over each role's bullet sequence (raw text, before
    labels are stripped) and returns [{text: match_key, level}] for levels >= 1.
    """
    out = []
    for exp in (cv_data or {}).get("work_experiences") or []:
        if not isinstance(exp, dict):
            continue
        for role in exp.get("roles") or []:
            if not isinstance(role, dict):
                continue
            texts = []
            for item in role.get("bullets") or []:
                if isinstance(item, str):
                    texts.append(item)
                elif isinstance(item, dict):
                    for sub in item.get("bullets") or []:
                        if isinstance(sub, str):
                            texts.append(sub)
            for text, level in zip(texts, _infer_outline_levels(texts)):
                if level >= 1:
                    key = _cv_bullet_match_key(text)
                    if key:
                        out.append({"text": key, "level": min(level, 8)})
    return out



def _merge_bullet_level_lists(*lists):
    """Merge {text, level} lists by key, keeping the deepest level (>= 1)."""
    best = {}
    for entries in lists:
        for entry in entries or []:
            if not isinstance(entry, dict):
                continue
            key = str(entry.get("text") or "")
            if not key:
                continue
            try:
                level = int(entry.get("level") or 0)
            except (TypeError, ValueError, OverflowError):
                continue
            level = max(0, min(level, 8))
            if key not in best or level > best[key]:
                best[key] = level
    return [{"text": k, "level": v} for k, v in best.items() if v >= 1]
