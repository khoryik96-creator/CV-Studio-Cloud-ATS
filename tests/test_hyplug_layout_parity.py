"""A formatted CV's bullets nest as the original shows them: Word's list level
number is not how deep a bullet sits when a CV sets its indent by hand."""

from __future__ import annotations

import io

import docx
from docx.oxml import OxmlElement
from docx.oxml.ns import qn

import cvstudio_layout_parity as engine


def _bullet(d: docx.document.Document, text: str, level: int, left_twips: int | None) -> None:
    p = d.add_paragraph(text, style="List Bullet")
    ppr = p._p.get_or_add_pPr()
    num = ppr.find(qn("w:numPr"))
    if num is None:
        num = OxmlElement("w:numPr")
        ppr.append(num)
        num_id = OxmlElement("w:numId")
        num_id.set(qn("w:val"), "1")
        num.append(num_id)
    ilvl = num.find(qn("w:ilvl"))
    if ilvl is None:
        ilvl = OxmlElement("w:ilvl")
        num.insert(0, ilvl)
    ilvl.set(qn("w:val"), str(level))
    if left_twips is not None:
        ind = OxmlElement("w:ind")
        ind.set(qn("w:left"), str(left_twips))
        ppr.append(ind)


def test_bullets_nest_by_how_deep_they_sit_not_by_their_list_level() -> None:
    d = docx.Document()
    d.add_paragraph("Achievements")
    # Level 2 and 3 of a list drawn shallow by hand, their sub-points deeper.
    _bullet(d, "Completed two end to end implementations", 2, 709)
    _bullet(d, "Contoh Telco for Accounts Payable", 0, 993)
    _bullet(d, "Contoh Berhad for Asset Accounting", 0, 993)
    _bullet(d, "Completed four rollouts of the FICO module", 2, 709)
    d.add_paragraph("Support Role")
    _bullet(d, "Support team member for SAP FICO", 3, 709)
    _bullet(d, "Create and maintain cost centres", 0, 709)
    buf = io.BytesIO()
    d.save(buf)
    levels = {e["text"]: e["level"] for e in engine._extract_docx_bullet_levels(buf.getvalue())}
    assert levels == {
        "contoh telco for accounts payable": 1,
        "contoh berhad for asset accounting": 1,
    }, "the sub-points one level in; the rest (levels 2 and 3 drawn shallow) at the first level"

def test_blind_nesting_follows_rewritten_bullets():
    def cv(*items):
        return {"work_experiences": [{"roles": [{"bullets": list(items)}]}]}
    before = cv("Main duty", {"heading": "Projects", "bullets": ["Built Acme platform"]})
    after = cv("Main duty", {"heading": "Projects", "bullets": ["Built [Company] platform"]})
    levels = [{"text": "built acme platform", "level": 1}]
    assert engine.blind_levels(levels, before, after) == [{"text": "built [company] platform", "level": 1}]
    assert engine.blind_levels(levels, before, cv("Shortened")) == levels

def test_ambiguous_duplicate_output_is_not_indented():
    def cv(*items):
        return {"work_experiences": [{"roles": [{"bullets": list(items)}]}]}
    assert engine.blind_levels([{"text":"second","level":1}], cv("first","second"), cv("same","same")) == []

def test_inherited_word_list_style_and_explicit_cancel():
    d = docx.Document()
    p = d.add_paragraph("Parent", style="List Bullet")
    p.paragraph_format.left_indent = docx.shared.Twips(360)
    p = d.add_paragraph("Child", style="List Bullet")
    p.paragraph_format.left_indent = docx.shared.Twips(720)
    p = d.add_paragraph("Not a list", style="List Bullet")
    num = p._p.get_or_add_pPr().get_or_add_numPr()
    num.get_or_add_numId().val = 0
    p = d.add_paragraph("New parent", style="List Bullet")
    p.paragraph_format.left_indent = docx.shared.Twips(720)
    buf = io.BytesIO()
    d.save(buf)
    assert engine._extract_docx_bullet_levels(buf.getvalue()) == [{"text":"child","level":1}]

def test_conflicting_source_levels_are_not_assigned_to_blind_output():
    before = {"work_experiences":[{"roles":[{"bullets":["same"]}]}]}
    after = {"work_experiences":[{"roles":[{"bullets":["rewritten"]}]}]}
    assert engine.blind_levels([{"text":"same","level":1},{"text":"same","level":2}], before, after) == []
