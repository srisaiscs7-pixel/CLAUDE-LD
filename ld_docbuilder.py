"""Build the Word (.docx) file with python-docx."""
from __future__ import annotations

import io
import re

from docx import Document
from docx.enum.section import WD_SECTION
from docx.enum.table import WD_TABLE_ALIGNMENT
from docx.enum.text import WD_ALIGN_PARAGRAPH, WD_BREAK, WD_LINE_SPACING
from docx.oxml import OxmlElement
from docx.oxml.ns import qn
from docx.shared import Cm, Pt, RGBColor

RED = RGBColor(0xC0, 0x00, 0x00)
SECTPR_ORDER = ["headerReference", "footerReference", "footnotePr", "endnotePr", "type", "pgSz", "pgMar",
                "paperSrc", "pgBorders", "lnNumType", "pgNumType", "cols", "formProt", "vAlign", "noEndnote",
                "titlePg", "textDirection", "bidi", "rtlGutter", "docGrid", "printerSettings", "sectPrChange"]


# ------------------------------------------------------------------ low-level helpers
def _sect_insert(sectPr, el):
    tag = el.tag.split("}")[1]
    idx = SECTPR_ORDER.index(tag)
    for existing in sectPr.findall(qn("w:" + tag)):
        sectPr.remove(existing)
    for i, child in enumerate(list(sectPr)):
        ctag = child.tag.split("}")[1]
        if ctag in SECTPR_ORDER and SECTPR_ORDER.index(ctag) > idx:
            child.addprevious(el)
            return
    sectPr.append(el)


def _page_numbering(section, fmt="decimal", start=None):
    el = OxmlElement("w:pgNumType")
    el.set(qn("w:fmt"), fmt)
    if start is not None:
        el.set(qn("w:start"), str(start))
    _sect_insert(section._sectPr, el)


def _page_border(section):
    b = OxmlElement("w:pgBorders")
    b.set(qn("w:offsetFrom"), "text")
    for side, space in (("top", 12), ("left", 18), ("bottom", 12), ("right", 18)):
        e = OxmlElement(f"w:{side}")
        e.set(qn("w:val"), "single")
        e.set(qn("w:sz"), "6")
        e.set(qn("w:space"), str(space))
        e.set(qn("w:color"), "auto")
        b.append(e)
    _sect_insert(section._sectPr, b)


def _para_border_bottom(p, color, style="thickThinMediumGap", sz=18):
    pPr = p._p.get_or_add_pPr()
    pbdr = OxmlElement("w:pBdr")
    bot = OxmlElement("w:bottom")
    bot.set(qn("w:val"), style)
    bot.set(qn("w:sz"), str(sz))
    bot.set(qn("w:space"), "1")
    bot.set(qn("w:color"), color)
    pbdr.append(bot)
    pPr.append(pbdr)


def _field(paragraph, instr, placeholder="", font=None, size=None, bold=False):
    def r(el_tag, **attrs):
        run = paragraph.add_run()
        el = OxmlElement(el_tag)
        for k, v in attrs.items():
            el.set(qn(k), v)
        run._r.append(el)
        return run
    r("w:fldChar", **{"w:fldCharType": "begin"})
    run = paragraph.add_run()
    it = OxmlElement("w:instrText")
    it.set(qn("xml:space"), "preserve")
    it.text = f" {instr} "
    run._r.append(it)
    r("w:fldChar", **{"w:fldCharType": "separate"})
    ph = paragraph.add_run(placeholder)
    if font:
        ph.font.name = font
    if size:
        ph.font.size = Pt(size)
    ph.bold = bold
    r("w:fldChar", **{"w:fldCharType": "end"})
    return ph


def _shade(cell, fill):
    tcPr = cell._tc.get_or_add_tcPr()
    shd = OxmlElement("w:shd")
    shd.set(qn("w:val"), "clear")
    shd.set(qn("w:color"), "auto")
    shd.set(qn("w:fill"), fill)
    tcPr.append(shd)


def _repeat_header(row):
    trPr = row._tr.get_or_add_trPr()
    for tag in ("w:tblHeader", "w:cantSplit"):
        el = OxmlElement(tag)
        el.set(qn("w:val"), "true")
        trPr.append(el)


def _cant_split(row):
    el = OxmlElement("w:cantSplit")
    el.set(qn("w:val"), "true")
    row._tr.get_or_add_trPr().append(el)


INLINE = re.compile(r"(\*\*.+?\*\*|\*[^*\s][^*]*?\*|⟦[^⟧]+⟧|\{\{.+?\}\})")


class Builder:
    def __init__(self, settings: dict):
        self.s = settings
        self.doc = Document()
        self.font = settings["font"]
        self.size = settings["size"]
        self.spacing = settings["line_spacing"]
        self._setup_styles()
        sec = self.doc.sections[0]
        self._page_setup(sec)

    # ---------------------------------------------------------- setup
    def _setup_styles(self):
        st = self.doc.styles
        normal = st["Normal"]
        normal.font.name = self.font
        normal.font.size = Pt(self.size)
        rpr = normal.element.get_or_add_rPr()
        rf = rpr.find(qn("w:rFonts"))
        if rf is None:
            rf = OxmlElement("w:rFonts")
            rpr.append(rf)
        for k in ("w:ascii", "w:hAnsi", "w:cs", "w:eastAsia"):
            rf.set(qn(k), self.font)
        pf = normal.paragraph_format
        pf.space_after = Pt(0)
        pf.space_before = Pt(0)
        for name, size, align in (("Heading 1", 14, WD_ALIGN_PARAGRAPH.CENTER),
                                  ("Heading 2", 12, WD_ALIGN_PARAGRAPH.LEFT),
                                  ("Heading 3", 12, WD_ALIGN_PARAGRAPH.LEFT)):
            h = st[name]
            h.font.name = self.font
            h.font.size = Pt(size)
            h.font.bold = True
            h.font.italic = name == "Heading 3"
            h.font.color.rgb = RGBColor(0, 0, 0)
            h.font.underline = name != "Heading 3"
            hr = h.element.get_or_add_rPr()
            rf = hr.find(qn("w:rFonts"))
            if rf is None:
                rf = OxmlElement("w:rFonts")
                hr.append(rf)
            for k in ("w:ascii", "w:hAnsi", "w:cs", "w:eastAsia"):
                rf.set(qn(k), self.font)
            for attr in ("w:asciiTheme", "w:hAnsiTheme", "w:cstheme", "w:eastAsiaTheme"):
                if rf.get(qn(attr)) is not None:
                    del rf.attrib[qn(attr)]
            h.paragraph_format.alignment = align
            h.paragraph_format.space_before = Pt(12 if name != "Heading 1" else 0)
            h.paragraph_format.space_after = Pt(6 if name != "Heading 1" else 18)
            h.paragraph_format.keep_with_next = True
            h.paragraph_format.line_spacing = 1.15
        settings = self.doc.settings.element
        uf = OxmlElement("w:updateFields")
        uf.set(qn("w:val"), "true")
        settings.append(uf)

    def _page_setup(self, sec):
        top, right, bottom, left = self.s["margins_cm"]
        sec.page_width, sec.page_height = Cm(21.0), Cm(29.7)
        sec.top_margin, sec.right_margin, sec.bottom_margin, sec.left_margin = Cm(top), Cm(right), Cm(bottom), Cm(left)
        sec.header_distance, sec.footer_distance = Cm(1.25), Cm(1.25)
        if self.s.get("page_border"):
            _page_border(sec)

    def new_section(self, header_text: str | None, numbering: str | None = None, start: int | None = None,
                    divider: bool = False):
        if getattr(self, "_reuse_first", False):  # content-only document: use the first page
            self._reuse_first = False
            sec = self.doc.sections[0]
        else:
            sec = self.doc.add_section(WD_SECTION.NEW_PAGE)
        self._page_setup(sec)
        sec.header.is_linked_to_previous = False
        sec.footer.is_linked_to_previous = False
        sec.different_first_page_header_footer = divider
        if divider:
            sec.first_page_header.is_linked_to_previous = False
            sec.first_page_footer.is_linked_to_previous = False
        for p in sec.header.paragraphs:
            p.text = ""
        for p in sec.footer.paragraphs:
            p.text = ""
        if header_text:
            hp = sec.header.paragraphs[0]
            hp.alignment = WD_ALIGN_PARAGRAPH.RIGHT
            run = hp.add_run(header_text)
            run.italic = True
            run.font.name = self.font
            run.font.size = Pt(11)
            _para_border_bottom(hp, self.s.get("header_rule", "1F3B5A"))
        fp = sec.footer.paragraphs[0]
        fp.alignment = WD_ALIGN_PARAGRAPH.CENTER if self.s.get("page_number_pos") == "center" else WD_ALIGN_PARAGRAPH.RIGHT
        _field(fp, "PAGE", "1", self.font, 11)
        if numbering:
            _page_numbering(sec, numbering, start)
        return sec

    # ---------------------------------------------------------- paragraphs
    def para(self, text="", *, align="justify", bold=False, size=None, italic=False, spacing=None,
             before=0, after=None, indent_first=False, keep_next=False, style=None, hanging=None, left=None):
        p = self.doc.add_paragraph(style=style) if style else self.doc.add_paragraph()
        pf = p.paragraph_format
        pf.alignment = {"justify": WD_ALIGN_PARAGRAPH.JUSTIFY, "center": WD_ALIGN_PARAGRAPH.CENTER,
                        "left": WD_ALIGN_PARAGRAPH.LEFT, "right": WD_ALIGN_PARAGRAPH.RIGHT}[align]
        pf.line_spacing = spacing if spacing is not None else self.spacing
        pf.line_spacing_rule = WD_LINE_SPACING.MULTIPLE
        pf.space_before = Pt(before)
        pf.space_after = Pt(after if after is not None else 6)
        if indent_first:
            pf.first_line_indent = Cm(1.27)
        if hanging is not None:
            pf.left_indent = Cm(left if left is not None else hanging)
            pf.first_line_indent = Cm(-hanging)
        elif left is not None:
            pf.left_indent = Cm(left)
        pf.keep_with_next = keep_next
        if text:
            self.inline(p, text, bold=bold, italic=italic, size=size)
        return p

    def inline(self, p, text, *, bold=False, italic=False, size=None):
        for part in INLINE.split(text):
            if not part:
                continue
            run_bold, run_italic, sup, red = bold, italic, False, False
            if part.startswith("**") and part.endswith("**"):
                part, run_bold = part[2:-2], True
            elif part.startswith("⟦"):
                part = part[1:-1]
                if self.s.get("citation_style") == "superscript":
                    sup = True
                else:
                    part = f" [{part}]"
            elif part.startswith("{{"):
                part, red, run_bold = part[2:-2], True, True
            elif part.startswith("*") and part.endswith("*") and len(part) > 2:
                part, run_italic = part[1:-1], True
            run = p.add_run(part)
            run.bold = run_bold
            run.italic = run_italic
            run.font.name = self.font
            if size:
                run.font.size = Pt(size)
            if sup:
                run.font.superscript = True
            if red:
                run.font.color.rgb = RED
        return p

    def heading(self, text, level):
        h = self.doc.add_heading(level=level)
        h.add_run(text)
        return h

    def page_break(self):
        self.doc.add_paragraph().add_run().add_break(WD_BREAK.PAGE)

    def body_markup(self, text: str):
        """Render the writer's markup: paragraphs, ### headings, - bullets, 1. lists."""
        for block in re.split(r"\n\s*\n", text.strip()):
            lines = [l.rstrip() for l in block.strip().split("\n") if l.strip()]
            if not lines:
                continue
            buf = []

            def flush():
                if buf:
                    self.para(" ".join(buf))
                    buf.clear()
            for line in lines:
                s = line.strip()
                if s.startswith("### ") or s.startswith("## "):
                    flush()
                    self.heading(s.lstrip("#").strip(), 3)
                elif re.match(r"^[-•*]\s+", s):
                    flush()
                    self.para("•\t" + re.sub(r"^[-•*]\s+", "", s), hanging=0.63, left=1.27, after=2)
                elif re.match(r"^\d+[.)]\s+", s):
                    flush()
                    m = re.match(r"^(\d+)[.)]\s+(.*)", s)
                    self.para(f"{m.group(1)}.\t{m.group(2)}", hanging=0.63, left=1.27, after=2)
                else:
                    buf.append(s)
            flush()

    # ---------------------------------------------------------- tables and figures
    def caption(self, kind, number, title, above=True):
        p = self.para(align="center", spacing=1.15, before=10 if above else 4, after=6 if above else 12, keep_next=above)
        r = p.add_run(f"{kind} ")
        r.bold = True
        r.font.name = self.font
        _field(p, f"SEQ {kind} \\* ARABIC", str(number), self.font, None, True)
        r2 = p.add_run(f": {title}")
        r2.bold = True
        r2.font.name = self.font
        return p

    def table(self, number, title, columns, rows, note=""):
        self.caption("Table", number, title, above=True)
        ncol = len(columns)
        t = self.doc.add_table(rows=1, cols=ncol)
        t.style = "Table Grid"
        t.alignment = WD_TABLE_ALIGNMENT.CENTER
        hdr = t.rows[0]
        _repeat_header(hdr)
        for i, c in enumerate(columns):
            cell = hdr.cells[i]
            _shade(cell, "D9E2F3")
            cell.paragraphs[0].alignment = WD_ALIGN_PARAGRAPH.CENTER
            self.inline(cell.paragraphs[0], str(c), bold=True, size=self.size - 1)
        for row in rows:
            r = t.add_row()
            _cant_split(r)
            for i in range(ncol):
                val = str(row[i]) if i < len(row) else ""
                self.inline(r.cells[i].paragraphs[0], val, size=self.size - 1, bold=(i == 0))
        for row in t.rows:
            for c in row.cells:
                for p in c.paragraphs:
                    p.paragraph_format.line_spacing = 1.0
                    p.paragraph_format.space_after = Pt(2)
        if note:
            self.para(note, align="left", italic=True, size=self.size - 2, spacing=1.0, before=3, after=12)
        else:
            self.para("", spacing=1.0, after=6)

    def figure(self, number, title, png: bytes, width_cm=15.0, note=""):
        p = self.para(align="center", spacing=1.0, before=8, after=2, keep_next=True)
        p.add_run().add_picture(io.BytesIO(png), width=Cm(width_cm))
        self.caption("Figure", number, title, above=False)
        if note:
            self.para(note, align="center", italic=True, size=self.size - 2, spacing=1.0, after=12)

    def save(self) -> bytes:
        buf = io.BytesIO()
        self.doc.save(buf)
        return buf.getvalue()


# ------------------------------------------------------------------ whole document
def build_document(model: dict) -> bytes:
    s = model["settings"]
    d = model["details"]
    b = Builder(s)
    U = lambda x: (x or "").upper()
    dept_full = d.get("department_full") or d.get("department", "")

    if not model.get("front_matter", True):
        b._reuse_first = True
    else:
        # Title page (first section, no header/footer)
        sec0 = b.doc.sections[0]
        sec0.different_first_page_header_footer = False
        b.para("", spacing=1.0, after=30)
        b.para(f"“{U(d.get('title'))}”", align="center", bold=True, size=16, spacing=1.3, after=24)
        b.para("A LIBRARY DISSERTATION", align="center", bold=True, size=13, spacing=1.2, after=6)
        b.para("Submitted to", align="center", spacing=1.2, after=2)
        b.para(d.get("university") or "{{[University name]}}", align="center", bold=True, spacing=1.2, after=18)
        b.para("In partial fulfilment of the requirements for the degree of", align="center", spacing=1.2, after=4)
        b.para("MASTER OF DENTAL SURGERY", align="center", bold=True, size=13, spacing=1.2, after=4)
        b.para("in", align="center", spacing=1.2, after=4)
        b.para(U(dept_full), align="center", bold=True, spacing=1.2, after=24)
        b.para("By", align="center", spacing=1.2, after=4)
        b.para(f"Dr. {d.get('candidate_name') or '{{[Candidate name]}}'}", align="center", bold=True, size=13, spacing=1.2, after=24)
        b.para("Under the guidance of", align="center", spacing=1.2, after=4)
        b.para(f"Dr. {d.get('guide_name') or '{{[Guide name]}}'}", align="center", bold=True, spacing=1.2, after=2)
        b.para(d.get("guide_designation") or "{{[Designation]}}", align="center", spacing=1.2, after=36)
        b.para(f"DEPARTMENT OF {U(dept_full)}", align="center", bold=True, spacing=1.2, after=2)
        b.para(U(d.get("college")) or "{{[COLLEGE NAME]}}", align="center", bold=True, spacing=1.2, after=2)
        b.para(d.get("academic_year") or "{{[Year]}}", align="center", bold=True, spacing=1.2)

        cand = f"Dr. {d.get('candidate_name') or '{{[Candidate name]}}'}"
        guide = f"Dr. {d.get('guide_name') or '{{[Guide name]}}'}"
        college = d.get("college") or "{{[College name]}}"
        univ = d.get("university") or "{{[University]}}"
        title_q = f"“{d.get('title')}”"
        place = d.get("place") or "{{[Place]}}"

        def front(title):
            b.new_section(None, "lowerRoman", 1 if title == "DECLARATION BY THE CANDIDATE" else None)
            b.para(title, align="center", bold=True, size=14, spacing=1.2, after=30)

        def sign(left, right):
            t = b.doc.add_table(rows=1, cols=2)
            for i, lines in enumerate((left, right)):
                cell = t.rows[0].cells[i]
                cell.paragraphs[0].text = ""
                for k, line in enumerate(lines):
                    p = cell.paragraphs[0] if k == 0 else cell.add_paragraph()
                    p.alignment = WD_ALIGN_PARAGRAPH.LEFT if i == 0 else WD_ALIGN_PARAGRAPH.RIGHT
                    b.inline(p, line, bold=line.startswith("Dr.") or line.isupper())
            b.para("", after=6)

        front("DECLARATION BY THE CANDIDATE")
        b.para(f"I hereby declare that this library dissertation entitled **{title_q}** is a bonafide and genuine work "
               f"carried out by me under the guidance of **{guide}**, {d.get('guide_designation') or '{{[Designation]}}'}, "
               f"Department of {dept_full}, {college}.", spacing=2.0)
        b.para("", spacing=2.0, after=40)
        sign(["Date:", f"Place: {place}"], ["Signature of the candidate", "", cand])

        front("CERTIFICATE BY THE GUIDE")
        b.para(f"This is to certify that the library dissertation entitled **{title_q}** is a bonafide work done by "
               f"**{cand}** in partial fulfilment of the requirements for the degree of **Master of Dental Surgery** in "
               f"**{dept_full}**.", spacing=2.0)
        b.para("", spacing=2.0, after=40)
        sign(["Date:", f"Place: {place}"], ["Signature of the guide", "", guide, d.get("guide_designation") or "{{[Designation]}}",
                                              f"Department of {dept_full}", college])

        front("ENDORSEMENT BY THE HEAD OF THE DEPARTMENT AND PRINCIPAL")
        b.para(f"This is to certify that the library dissertation entitled **{title_q}** is a bonafide work done by "
               f"**{cand}** under the guidance of **{guide}**, {d.get('guide_designation') or '{{[Designation]}}'}, "
               f"Department of {dept_full}, {college}.", spacing=2.0)
        b.para("", spacing=2.0, after=40)
        sign([f"Dr. {d.get('hod_name') or '{{[HOD name]}}'}", "Professor and Head", f"Department of {dept_full}", college, "", "Date:", f"Place: {place}"],
             [f"Dr. {d.get('principal_name') or '{{[Principal name]}}'}", "Principal", college])

        front("COPYRIGHT")
        b.para("DECLARATION BY THE CANDIDATE", align="center", bold=True, after=18)
        b.para(f"I hereby declare that {univ} shall have the rights to preserve, use and disseminate this library "
               f"dissertation in print or electronic format for academic and research purposes.", spacing=2.0)
        b.para("", spacing=2.0, after=40)
        sign(["Date:", f"Place: {place}"], ["Signature of the candidate", "", cand])
        b.para(f"© {univ}", align="center", before=30)

        front("ACKNOWLEDGEMENT")
        b.para("{{[To be written by the candidate]}}", align="center")

        front("TABLE OF CONTENTS")
        p = b.para(align="left", spacing=1.5)
        _field(p, 'TOC \\o "1-2" \\h \\z \\u', "Open this file in Word and press Yes to “update fields” (or right-click here → Update Field) to build the table of contents.", b.font, 11)
        if model.get("n_tables"):
            front("LIST OF TABLES")
            p = b.para(align="left", spacing=1.5)
            _field(p, 'TOC \\h \\z \\c "Table"', "Right-click → Update Field to build the list of tables.", b.font, 11)
        if model.get("n_figures"):
            front("LIST OF FIGURES")
            p = b.para(align="left", spacing=1.5)
            _field(p, 'TOC \\h \\z \\c "Figure"', "Right-click → Update Field to build the list of figures.", b.font, 11)
        if model.get("abbreviations"):
            front("LIST OF ABBREVIATIONS")
            t = b.doc.add_table(rows=1, cols=2)
            t.style = "Table Grid"
            for i, h in enumerate(("Abbreviation", "Expansion")):
                _shade(t.rows[0].cells[i], "D9E2F3")
                b.inline(t.rows[0].cells[i].paragraphs[0], h, bold=True)
            for a, full in model["abbreviations"]:
                r = t.add_row()
                b.inline(r.cells[0].paragraphs[0], a, bold=True)
                b.inline(r.cells[1].paragraphs[0], full)

    # Chapters
    first = True
    for ch in model["chapters"]:
        b.new_section(ch["header"], "decimal", 1 if first else None, divider=s.get("divider_pages", False))
        first = False
        if s.get("divider_pages"):
            for _ in range(12):
                b.para("", spacing=1.5)
            b.para(ch.get("display") or U(ch["title"]), align="center", bold=True, size=22, spacing=1.2)
            b.page_break()
        b.heading(ch.get("display") or U(ch["title"]), 1)
        for blk in ch["blocks"]:
            t = blk["type"]
            if t == "h2":
                b.heading(blk["text"], 2)
            elif t == "text":
                b.body_markup(blk["text"])
            elif t == "aims":
                b.heading("AIM", 2)
                b.para(blk["aim"])
                b.heading("OBJECTIVES", 2)
                for i, o in enumerate(blk["objectives"], 1):
                    b.para(f"{i}.\t{o}", hanging=0.75, left=1.27)
            elif t == "entry":
                b.para(f"**{blk['lead']}** {blk['text']}", indent_first=False, after=10)
            elif t == "table":
                b.table(blk["number"], blk["title"], blk["columns"], blk["rows"], blk.get("note", ""))
            elif t == "figure":
                b.figure(blk["number"], blk["title"], blk["png"], note=blk.get("note", ""))

    # References
    b.new_section("References", None, None, divider=s.get("divider_pages", False))
    if s.get("divider_pages"):
        for _ in range(12):
            b.para("", spacing=1.5)
        b.para("REFERENCES", align="center", bold=True, size=22, spacing=1.2)
        b.page_break()
    b.heading("REFERENCES", 1)
    for i, ref in enumerate(model["references"], 1):
        b.para(f"{i}.\t{ref}", align="left", spacing=min(1.5, s["line_spacing"]), hanging=0.9, after=6)
    return b.save()
