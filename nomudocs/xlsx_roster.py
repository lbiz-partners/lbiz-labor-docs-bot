"""엑셀 명단(.xlsx) 읽기·쓰기. 추가 꾸러미 없이 표준 라이브러리만 쓴다.

주민등록번호·계좌번호 열은 값으로 들이지 않고 열 이름만 돌려준다.
"""
import zipfile
from datetime import date, timedelta
from pathlib import Path
from xml.etree import ElementTree as ET
from xml.sax.saxutils import escape

NS = "http://schemas.openxmlformats.org/spreadsheetml/2006/main"
REL = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
PKG = "http://schemas.openxmlformats.org/package/2006/relationships"
NSMAP = {"m": NS}


def _q(tag):
    return f"{{{NS}}}{tag}"


def _col_row(ref):
    col = 0
    i = 0
    while i < len(ref) and ref[i].isalpha():
        col = col * 26 + (ord(ref[i].upper()) - 64)
        i += 1
    return col - 1, int(ref[i:]) - 1


def _col_name(index):
    n = index + 1
    s = ""
    while n:
        n, r = divmod(n - 1, 26)
        s = chr(65 + r) + s
    return s


def _maybe_num(text):
    try:
        if any(c in text for c in ".eE"):
            num = float(text)
            return int(num) if num.is_integer() else num
        return int(text)
    except (TypeError, ValueError):
        return text


def _shared_strings(z):
    name = "xl/sharedStrings.xml"
    if name not in z.namelist():
        return []
    root = ET.fromstring(z.read(name))
    out = []
    for si in root.findall("m:si", NSMAP):
        out.append("".join((t.text or "") for t in si.findall(".//m:t", NSMAP)))
    return out


def _sheet_targets(z):
    wb = ET.fromstring(z.read("xl/workbook.xml"))
    rels = ET.fromstring(z.read("xl/_rels/workbook.xml.rels"))
    rid_to = {}
    for rel in rels:
        rid = rel.attrib.get("Id")
        target = rel.attrib.get("Target") or ""
        if target.startswith("/"):
            target = target.lstrip("/")
        elif not target.startswith("xl/"):
            target = "xl/" + target
        rid_to[rid] = target
    found = []
    for sh in wb.findall("m:sheets/m:sheet", NSMAP):
        rid = sh.attrib.get(f"{{{REL}}}id")
        found.append((sh.attrib.get("name") or "", rid_to.get(rid, "")))
    return found


def _sheet_matrix(z, path, shared):
    root = ET.fromstring(z.read(path))
    cells = {}
    for c in root.findall(".//m:c", NSMAP):
        ref = c.attrib.get("r")
        if not ref:
            continue
        col, row = _col_row(ref)
        kind = c.attrib.get("t")
        if kind == "inlineStr":
            val = "".join((t.text or "") for t in c.findall(".//m:t", NSMAP))
        elif kind == "s":
            v = c.find("m:v", NSMAP)
            val = shared[int(v.text)] if v is not None and v.text else ""
        elif kind == "b":
            v = c.find("m:v", NSMAP)
            val = bool(v is not None and v.text == "1")
        else:
            v = c.find("m:v", NSMAP)
            val = None if v is None or v.text is None else _maybe_num(v.text)
        cells[(row, col)] = val
    if not cells:
        return []
    max_r = max(r for r, _ in cells)
    max_c = max(c for _, c in cells)
    table = []
    for r in range(max_r + 1):
        table.append([cells.get((r, c)) for c in range(max_c + 1)])
    while table and not any(x not in (None, "") for x in table[0]):
        table.pop(0)
    return table


def read_workbook(path):
    """(sheets: {이름: 행 목록}, ) 를 돌려준다. 못 열면 OSError."""
    sheets = {}
    with zipfile.ZipFile(path) as z:
        shared = _shared_strings(z)
        for name, target in _sheet_targets(z):
            if target and target in z.namelist():
                sheets[name] = _sheet_matrix(z, target, shared)
    return sheets


def write_xlsx(path, sheets):
    """sheets: [(시트이름, [[셀, ...], ...]), ...]. 글자는 셀 안 문자열, 숫자는 숫자로 적는다."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    sheet_xmls = []
    overrides = []
    for i, (name, rows) in enumerate(sheets, start=1):
        sheet_xmls.append((i, name, _sheet_xml(rows)))
        overrides.append(
            f'<Override PartName="/xl/worksheets/sheet{i}.xml" '
            f'ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"/>'
        )
    content_types = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
        '<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>'
        '<Default Extension="xml" ContentType="application/xml"/>'
        '<Override PartName="/xl/workbook.xml" '
        'ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml"/>'
        '<Override PartName="/xl/styles.xml" '
        'ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.styles+xml"/>'
        + "".join(overrides) + "</Types>"
    )
    root_rels = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        f'<Relationships xmlns="{PKG}">'
        '<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="xl/workbook.xml"/>'
        "</Relationships>"
    )
    wb_rels_parts = []
    sheet_tags = []
    for i, (name, _) in enumerate(sheets, start=1):
        wb_rels_parts.append(
            f'<Relationship Id="rId{i}" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet" Target="worksheets/sheet{i}.xml"/>'
        )
        sheet_tags.append(f'<sheet name="{escape(name)}" sheetId="{i}" r:id="rId{i}"/>')
    wb_rels_parts.append(
        f'<Relationship Id="rId{len(sheets) + 1}" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/styles" Target="styles.xml"/>'
    )
    workbook = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        f'<workbook xmlns="{NS}" xmlns:r="{REL}">'
        "<sheets>" + "".join(sheet_tags) + "</sheets></workbook>"
    )
    wb_rels = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        f'<Relationships xmlns="{PKG}">' + "".join(wb_rels_parts) + "</Relationships>"
    )
    styles = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        f'<styleSheet xmlns="{NS}"><fonts count="1"><font><sz val="11"/><name val="맑은 고딕"/></font></fonts>'
        '<fills count="1"><fill><patternFill patternType="none"/></fill></fills>'
        '<borders count="1"><border/></borders>'
        '<cellStyleXfs count="1"><xf/></cellStyleXfs>'
        '<cellXfs count="1"><xf/></cellXfs></styleSheet>'
    )
    with zipfile.ZipFile(path, "w", compression=zipfile.ZIP_DEFLATED) as z:
        z.writestr("[Content_Types].xml", content_types)
        z.writestr("_rels/.rels", root_rels)
        z.writestr("xl/workbook.xml", workbook)
        z.writestr("xl/_rels/workbook.xml.rels", wb_rels)
        z.writestr("xl/styles.xml", styles)
        for i, _name, xml in sheet_xmls:
            z.writestr(f"xl/worksheets/sheet{i}.xml", xml)


def _sheet_xml(rows):
    body = []
    for r, row in enumerate(rows, start=1):
        cells = []
        for c, val in enumerate(row):
            if val is None or val == "":
                continue
            ref = f"{_col_name(c)}{r}"
            if isinstance(val, bool):
                cells.append(f'<c r="{ref}" t="b"><v>{1 if val else 0}</v></c>')
            elif isinstance(val, (int, float)) and not isinstance(val, bool):
                cells.append(f'<c r="{ref}"><v>{val}</v></c>')
            else:
                cells.append(f'<c r="{ref}" t="inlineStr"><is><t>{escape(str(val))}</t></is></c>')
        body.append(f'<row r="{r}">{"".join(cells)}</row>')
    return (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        f'<worksheet xmlns="{NS}"><sheetData>{"".join(body)}</sheetData></worksheet>'
    )


def excel_serial_to_date(n):
    """엑셀 1900 날짜 일련번호를 date 로. 글자 날짜는 그대로 둔다."""
    if isinstance(n, str):
        return n.strip()
    if isinstance(n, (int, float)) and not isinstance(n, bool) and 20000 <= float(n) <= 80000:
        return (date(1899, 12, 30) + timedelta(days=int(n))).isoformat()
    return n
