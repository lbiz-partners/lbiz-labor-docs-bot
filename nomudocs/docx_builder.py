"""DOCX 공통 부품. 글꼴은 '맑은 고딕'(동아시아)으로 적고, 박스에서 PDF로 바꿀 때는
fontconfig 별칭으로 Noto Sans CJK KR 로 렌더링한다(render/fonts.conf)."""
from docx import Document
from docx.enum.section import WD_ORIENT
from docx.enum.table import WD_TABLE_ALIGNMENT
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.oxml import OxmlElement
from docx.oxml.ns import qn
from docx.shared import Mm, Pt, RGBColor

FONT = "맑은 고딕"
BLANK = "　　　　　　"  # 손으로 채울 빈칸(전각 공백)


def _set_font(run, size=None, bold=None, color=None):
    run.font.name = FONT
    rpr = run._element.get_or_add_rPr()
    rfonts = rpr.find(qn("w:rFonts"))
    if rfonts is None:
        rfonts = OxmlElement("w:rFonts")
        rpr.append(rfonts)
    for k in ("w:ascii", "w:hAnsi", "w:eastAsia", "w:cs"):
        rfonts.set(qn(k), FONT)
    if size:
        run.font.size = Pt(size)
    if bold is not None:
        run.bold = bold
    if color:
        run.font.color.rgb = RGBColor(*color)


def v(x, unit="", empty=BLANK):
    """값이 비면 손글씨용 빈칸을 돌려준다."""
    if x is None or x == "" or x == []:
        return empty
    if isinstance(x, bool):
        return "예" if x else "아니오"
    if isinstance(x, (int, float)) and not isinstance(x, bool):
        s = f"{int(x):,}" if float(x).is_integer() else f"{x:,}"
        return s + unit
    return str(x) + unit


def won(x):
    return v(x, "원")


def ymd(s, empty=BLANK):
    if not s:
        return f"{empty}년 　월 　일"
    y, m, d = str(s)[:10].split("-")
    return f"{int(y)}년 {int(m)}월 {int(d)}일"


def box(checked):
    return "■" if checked else "□"


class Doc:
    def __init__(self, title, subtitle=None, footer=None, base_size=9.5):
        self.d = Document()
        self.base = base_size
        st = self.d.styles["Normal"]
        st.font.name = FONT
        st.font.size = Pt(base_size)
        st.element.rPr.rFonts.set(qn("w:eastAsia"), FONT)
        pf = st.paragraph_format
        pf.space_after = Pt(2)
        pf.space_before = Pt(0)
        pf.line_spacing = 1.15
        sec = self.d.sections[0]
        sec.orientation = WD_ORIENT.PORTRAIT
        sec.page_width, sec.page_height = Mm(210), Mm(297)
        sec.left_margin = sec.right_margin = Mm(18)
        sec.top_margin, sec.bottom_margin = Mm(15), Mm(15)
        if footer:
            fp = sec.footer.paragraphs[0]
            fp.alignment = WD_ALIGN_PARAGRAPH.CENTER
            _set_font(fp.add_run(footer), size=7.5, color=(110, 110, 110))
        self.title(title, subtitle)

    # ---- 문단 ----
    def title(self, text, subtitle=None):
        p = self.d.add_paragraph()
        p.alignment = WD_ALIGN_PARAGRAPH.CENTER
        p.paragraph_format.space_after = Pt(2 if subtitle else 8)
        _set_font(p.add_run(text), size=17, bold=True)
        if subtitle:
            p2 = self.d.add_paragraph()
            p2.alignment = WD_ALIGN_PARAGRAPH.CENTER
            p2.paragraph_format.space_after = Pt(8)
            _set_font(p2.add_run(subtitle), size=10.5, bold=True)

    def p(self, text="", bold=False, size=None, align=None, gray=False, space_after=None, keep_with_next=False):
        para = self.d.add_paragraph()
        if keep_with_next:
            para.paragraph_format.keep_with_next = True
        if align == "center":
            para.alignment = WD_ALIGN_PARAGRAPH.CENTER
        elif align == "right":
            para.alignment = WD_ALIGN_PARAGRAPH.RIGHT
        if space_after is not None:
            para.paragraph_format.space_after = Pt(space_after)
        _set_font(para.add_run(text), size=size or self.base, bold=bold,
                  color=(90, 90, 90) if gray else None)
        return para

    def h(self, text):
        para = self.d.add_paragraph()
        para.paragraph_format.space_before = Pt(5)
        para.paragraph_format.space_after = Pt(1)
        _set_font(para.add_run(text), size=self.base + 0.5, bold=True)
        return para

    def lines(self, items, indent=True):
        for t in items:
            self.p(("  " if indent else "") + t)

    # ---- 표 ----
    def table(self, rows, widths=None, header=False, size=None, bold_first_col=False, shade_first_col=False, keep_together=False):
        t = self.d.add_table(rows=len(rows), cols=max(len(r) for r in rows))
        t.style = "Table Grid"
        t.alignment = WD_TABLE_ALIGNMENT.CENTER
        for i, r in enumerate(rows):
            for j in range(len(t.columns)):
                cell = t.cell(i, j)
                text = r[j] if j < len(r) else ""
                cell.text = ""
                lines = str(text).split("\n")
                para = cell.paragraphs[0]
                for k, ln in enumerate(lines):
                    if k:
                        para = cell.add_paragraph()
                    para.paragraph_format.space_after = Pt(0)
                    b = (header and i == 0) or (bold_first_col and j == 0)
                    _set_font(para.add_run(ln), size=size or self.base - 0.5, bold=b)
                if (header and i == 0) or (shade_first_col and j == 0):
                    self._shade(cell)
        if widths:
            t.autofit = False
            grid = t._tbl.tblGrid
            for j, gc in enumerate(grid.findall(qn("w:gridCol"))):
                if j < len(widths):
                    gc.set(qn("w:w"), str(int(Mm(widths[j]).twips)))
            for j, w in enumerate(widths):
                for i in range(len(rows)):
                    t.cell(i, j).width = Mm(w)
        if keep_together:
            # 서명란이 두 쪽으로 갈라지지 않게: 행 분할 금지 + 마지막 행 전까지 '다음 문단과 함께'
            for i, row in enumerate(t.rows):
                trPr = row._tr.get_or_add_trPr()
                cs = OxmlElement("w:cantSplit")
                trPr.append(cs)
                if i < len(t.rows) - 1:
                    for c in row.cells:
                        for para in c.paragraphs:
                            para.paragraph_format.keep_with_next = True
        self._spacer()
        return t

    def _spacer(self, pt=3):
        sp = self.d.add_paragraph()
        sp.paragraph_format.space_after = Pt(0)
        sp.paragraph_format.space_before = Pt(0)
        sp.paragraph_format.line_spacing = Pt(pt)
        _set_font(sp.add_run(""), size=1)
        return sp

    @staticmethod
    def _shade(cell, fill="EDEFF2"):
        tcpr = cell._element.get_or_add_tcPr()
        shd = OxmlElement("w:shd")
        shd.set(qn("w:val"), "clear")
        shd.set(qn("w:color"), "auto")
        shd.set(qn("w:fill"), fill)
        tcpr.append(shd)

    def merge_row(self, table, row, c0, c1):
        a, b = table.cell(row, c0), table.cell(row, c1)
        txt = a.text
        m = a.merge(b)
        # merge 는 두 칸 글자를 이어 붙이므로 첫 칸 글자만 남긴다
        for para in m.paragraphs[1:]:
            para._element.getparent().remove(para._element)
        return m

    def page_break(self):
        self.d.add_page_break()

    def save(self, path):
        # 마지막 빈 문단이 다음 쪽으로 넘어가 빈 쪽이 생기지 않게 지운다
        body = self.d.element.body
        kids = [k for k in body.iterchildren() if k.tag != qn("w:sectPr")]
        if kids and kids[-1].tag == qn("w:p") and not "".join(kids[-1].itertext()).strip() and len(kids) > 1 and kids[-2].tag == qn("w:tbl"):
            kids[-1].getparent().remove(kids[-1])
        self.d.save(path)
