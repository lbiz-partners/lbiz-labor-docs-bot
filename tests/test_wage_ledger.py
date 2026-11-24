"""임금대장 — 한 사람, 여러 사람·여러 달, 4명 이하 생략, 빈칸, 엑셀 명단."""
import copy
import json
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from nomudocs import __version__, tool_version_label  # noqa: E402
from nomudocs.generate import Blocked, generate, prepare  # noqa: E402
from nomudocs.xlsx_roster import read_workbook, write_xlsx  # noqa: E402


def sample(name):
    return json.loads((ROOT / "samples" / f"{name}.json").read_text(encoding="utf-8"))


def codes(data, level=None):
    _data, _result = prepare(copy.deepcopy(data))
    from nomudocs.checks import check
    rep = check(_data, _result)
    return rep, [f.code for f in rep.findings if level is None or f.level == level]


def docx_text(path):
    from docx import Document
    d = Document(path)
    parts = [p.text for p in d.paragraphs]
    parts += [c.text for t in d.tables for r in t.rows for c in r.cells]
    parts += [p.text for s in d.sections for p in s.footer.paragraphs]
    return "\n".join(parts)


class WageLedgerSingle(unittest.TestCase):
    def test_matches_payslip_engine(self):
        """요율표·4대보험·소득세는 임금명세서와 같은 엔진 결과여야 한다."""
        ledger = sample("wage_ledger")
        slip = sample("payslip")
        _, led = prepare(ledger)
        _, pay = prepare(slip)
        row = led["entries"][0]["result"]
        self.assertEqual(row["earnings"], pay["earnings"])
        self.assertEqual(row["deductions"], pay["deductions"])
        self.assertEqual(row["netPay"], pay["netPay"])
        self.assertEqual(row["yearBasis"]["insurance"]["month"], pay["yearBasis"]["insurance"]["month"])
        self.assertEqual(row["yearBasis"]["incomeTax"]["year"], pay["yearBasis"]["incomeTax"]["year"])
        src = (ROOT / "nomudocs" / "docs" / "ledger.py").read_text(encoding="utf-8")
        self.assertIn("build_engine_input", src)
        self.assertNotIn("INSURANCE_EXTRA", src)
        self.assertNotIn("0.0475", src)
        self.assertNotIn("10320", src)

    def test_prints_tool_version_and_statute(self):
        with tempfile.TemporaryDirectory() as td:
            out = generate(sample("wage_ledger"), td, stem="ledger", pdf=False, png=False)
            text = docx_text(out["docx"])
            self.assertIn(tool_version_label(), text)
            self.assertIn(__version__, out["tool_version"])
            self.assertIn("임 금 대 장", text)
            self.assertIn("시행령 제27조", text)
            self.assertIn("홍길동", text)
            self.assertIn("경영지원", text)
            self.assertNotIn("주민등록번호", text)
            self.assertNotIn("계좌번호", text)
            self.assertEqual(out["payroll"]["count"], 1)
            self.assertEqual(out["payroll"]["entries"][0]["netPay"], out["payroll"]["entries"][0]["earnings"]["grossPay"] - out["payroll"]["entries"][0]["deductions"]["totalDeductions"])


class WageLedgerMany(unittest.TestCase):
    def test_multi_worker_and_month_and_grouping(self):
        data = sample("wage_ledger_multi")
        expanded, result = prepare(data)
        self.assertEqual(len(expanded["entries"]), 4)
        names = {e["employee"]["name"] for e in expanded["entries"]}
        self.assertEqual(names, {"홍길동", "김하나"})
        months = {e["periodLabel"] for e in expanded["entries"]}
        self.assertEqual(months, {"2026년 11월", "2026년 12월"})
        dec = next(item["result"] for entry, item in zip(expanded["entries"], result["entries"])
                   if entry["employee"]["name"] == "홍길동" and entry["periodFrom"].startswith("2026-12"))
        self.assertEqual(dec["yearBasis"]["incomeTax"]["year"], 2027)
        self.assertEqual(dec["yearBasis"]["insurance"]["month"], "2026-12")
        self.assertEqual(dec["yearBasis"]["insurance"]["year"], 2026)
        rep, _ = codes(data)
        self.assertEqual([f for f in rep.findings if f.level in ("missing", "error")], [])
        with tempfile.TemporaryDirectory() as td:
            out = generate(data, Path(td) / "worker", stem="w", pdf=False, png=False)
            text = docx_text(out["docx"])
            self.assertLess(text.find("김하나"), text.find("홍길동 · "))
            self.assertIn("근로자별", text)
            month = copy.deepcopy(data)
            month["groupBy"] = "month"
            out = generate(month, Path(td) / "month", stem="m", pdf=False, png=False)
            text = docx_text(out["docx"])
            self.assertLess(text.find("2026년 11월분"), text.find("2026년 12월분"))
            self.assertIn("월별", text)
            self.assertIn(tool_version_label(), text)


class FourOrFewer(unittest.TestCase):
    def test_hours_may_be_omitted(self):
        data = sample("wage_ledger_small")
        rep, found = codes(data)
        self.assertNotIn("L_HOURS", found)
        self.assertNotIn("L_OT", found)
        self.assertIn("L_FOUR_OR_FEWER", found)
        self.assertEqual([f for f in rep.findings if f.level in ("missing", "error")], [])
        with tempfile.TemporaryDirectory() as td:
            out = generate(data, td, stem="small", pdf=False, png=False)
            text = docx_text(out["docx"])
            self.assertIn("생략 가능(시행령 제27조제3항)", text)
            self.assertIn("상시 4명 이하", text)
            self.assertIn("박알바", text)
            self.assertIn("이수습", text)
        data["entries"][0]["employee"]["name"] = ""
        _, found = codes(data)
        self.assertIn("L_NAME", found)

    def test_five_plus_still_requires_hours(self):
        data = sample("wage_ledger")
        data["entries"][0]["totalHours"] = ""
        _, found = codes(data)
        self.assertIn("L_HOURS", found)

    def test_article63_flag_omits_hours_without_judging(self):
        data = sample("wage_ledger")
        data["entries"][0]["hoursExempt"] = True
        data["entries"][0].pop("totalHours")
        data["entries"][0]["hours"] = {}
        _, found = codes(data)
        self.assertNotIn("L_HOURS", found)
        self.assertIn("L_ART63", found)


class MissingFields(unittest.TestCase):
    def test_easy_korean_for_each_required_item(self):
        data = sample("wage_ledger")
        entry = data["entries"][0]
        entry["employee"] = {"name": "", "birth": "", "employeeNo": "", "hiredOn": "", "job": ""}
        entry["workDays"] = ""
        entry["totalHours"] = ""
        entry["pay"] = {}
        entry["extraEarnings"] = []
        entry["hours"] = {"overtime": ""}
        rep, found = codes(data)
        for code in ("L_NAME", "L_ID", "L_HIRED", "L_JOB", "L_BASIS", "L_DAYS", "L_HOURS", "L_OT", "L_WAGE"):
            self.assertIn(code, found, code)
        msgs = [f.msg for f in rep.findings if f.code.startswith("L_")]
        self.assertTrue(all("비어" in m for m in msgs), msgs)
        self.assertTrue(any("성명" in m for m in msgs))
        self.assertTrue(any("생년월일" in m for m in msgs))
        self.assertTrue(any("고용 연월일" in m for m in msgs))
        self.assertTrue(any("종사하는 업무" in m for m in msgs))
        self.assertTrue(any("근로일수" in m for m in msgs))
        self.assertTrue(any("근로시간수" in m for m in msgs))

    def test_daily_under_30_may_omit_id_and_basis(self):
        data = sample("wage_ledger")
        entry = data["entries"][0]
        entry["employment"] = {"type": "daily"}
        entry["employee"]["hiredOn"] = "2026-11-10"
        entry["employee"]["birth"] = ""
        entry["employee"]["employeeNo"] = ""
        entry["pay"] = {}
        entry["extraEarnings"] = []
        entry["calcBasis"] = ""
        _, found = codes(data)
        self.assertNotIn("L_ID", found)
        self.assertNotIn("L_BASIS", found)
        self.assertIn("L_DAILY30", found)
        self.assertIn("L_WAGE", found)
        entry["employee"]["hiredOn"] = "2024-03-01"
        _, found = codes(data)
        self.assertIn("L_ID", found)
        self.assertIn("L_BASIS", found)


class ExcelRoster(unittest.TestCase):
    def test_bulk_matches_inline_multi(self):
        multi, multi_result = prepare(sample("wage_ledger_multi"))
        roster, roster_result = prepare(sample("wage_ledger_roster"))
        self.assertEqual(len(roster["entries"]), 4)
        def key(entry, item):
            emp = entry["employee"]
            return (emp["name"], entry["periodFrom"], item["result"]["netPay"], item["result"]["deductions"]["nationalPension"])
        self.assertEqual(
            sorted(key(e, i) for e, i in zip(multi["entries"], multi_result["entries"])),
            sorted(key(e, i) for e, i in zip(roster["entries"], roster_result["entries"])),
        )
        rep, found = codes(sample("wage_ledger_roster"))
        self.assertEqual([f for f in rep.findings if f.level in ("missing", "error")], [])
        self.assertNotIn("L_ROSTER", found)

    def test_samples_have_no_id_or_account_fields(self):
        banned = ("주민등록번호", "주민번호", "계좌번호", "accountNo", "bankAccount")
        for path in (ROOT / "samples").iterdir():
            if path.suffix.lower() not in {".json", ".xlsx"}:
                continue
            blob = path.read_bytes()
            for word in banned:
                self.assertNotIn(word.encode("utf-8"), blob, path.name)

    def test_forbidden_column_is_dropped_and_blocks(self):
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "bad.xlsx"
            secret = "900101-1234567"
            write_xlsx(path, [("명단", [
                ["성명", "생년월일", "주민등록번호", "계좌번호", "종사업무", "고용연월일", "임금년월", "임금지급일", "근로일수", "근로시간수", "임금형태", "기본급"],
                ["홍길동", "1995-04-12", secret, "110-123-456789", "경영지원", "2024-03-01", "2026-11", "2026-11-25", 20, 170, "월급", 2600000],
            ])])
            data = {"doc": "wage_ledger", "workplace": {"size5plus": True}, "employer": {"name": "예시"}, "roster": str(path)}
            expanded, _ = prepare(data)
            dumped = json.dumps(expanded, ensure_ascii=False)
            self.assertNotIn(secret, dumped)
            self.assertNotIn("110-123-456789", dumped)
            with self.assertRaises(Blocked) as caught:
                generate(data, Path(td) / "out", stem="bad", pdf=False, png=False)
            report = json.dumps(caught.exception.report.as_dict(), ensure_ascii=False)
            self.assertNotIn(secret, report)
            self.assertNotIn("110-123-456789", report)
            self.assertIn("SENSITIVE_RRN", caught.exception.report.codes())
            self.assertIn("SENSITIVE_ACCOUNT", caught.exception.report.codes())

    def test_cli_check_and_make(self):
        with tempfile.TemporaryDirectory() as td:
            check = subprocess.run(
                [sys.executable, "-m", "nomudocs", "check", "samples/wage_ledger.json"],
                cwd=ROOT, capture_output=True, text=True,
            )
            self.assertEqual(check.returncode, 0, check.stdout + check.stderr)
            self.assertIn("계산:", check.stdout)
            made = subprocess.run(
                [sys.executable, "-m", "nomudocs", "make", "samples/wage_ledger_roster.xlsx", str(Path(td) / "out"), "--no-pdf"],
                cwd=ROOT, capture_output=True, text=True,
            )
            self.assertEqual(made.returncode, 0, made.stdout + made.stderr)
            self.assertTrue(list(Path(td).rglob("*.docx")))
            text = docx_text(next(Path(td).rglob("*.docx")))
            self.assertIn("도구 판", text)
            self.assertIn("김하나", text)
            self.assertIn("홍길동", text)

    def test_shared_strings_and_date_serial(self):
        """사용자가 엑셀에서 저장한 공유문자열·날짜 일련번호도 읽는다."""
        import zipfile
        from datetime import date
        serial = (date(1995, 4, 12) - date(1899, 12, 30)).days
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "shared.xlsx"
            _write_shared_string_xlsx(path, [["성명", "종사업무"], ["홍길동", "주방"]])
            sheets = read_workbook(path)
            self.assertEqual(sheets["명단"][1][0], "홍길동")
            self.assertEqual(sheets["명단"][1][1], "주방")
            raw_path = Path(td) / "serial.xlsx"
            write_xlsx(raw_path, [("명단", [["생년월일"], [serial]])])
            again = read_workbook(raw_path)
            self.assertEqual(again["명단"][1][0], serial)
            from nomudocs.docs.ledger import rows_to_entries
            entries, bad = rows_to_entries(again["명단"])
            self.assertEqual(bad, [])
            self.assertEqual(entries[0]["employee"]["birth"], "1995-04-12")


class PdfIfAvailable(unittest.TestCase):
    def test_ledger_pdf(self):
        if not shutil.which("soffice") and not shutil.which("libreoffice"):
            self.skipTest("LibreOffice 없음")
        with tempfile.TemporaryDirectory() as td:
            out = generate(sample("wage_ledger"), td, stem="ledger")
            self.assertTrue(Path(out["pdf"]).exists())
            self.assertGreaterEqual(len(out["png"]), 1)


def _write_shared_string_xlsx(path, rows):
    """엑셀이 기본으로 쓰는 공유문자열 표를 가진 최소 파일."""
    import zipfile
    from xml.sax.saxutils import escape
    strings = []
    for row in rows:
        for cell in row:
            if isinstance(cell, str) and cell not in strings:
                strings.append(cell)
    shared = "".join(f"<si><t>{escape(s)}</t></si>" for s in strings)
    body = []
    for r, row in enumerate(rows, start=1):
        cells = []
        for c, val in enumerate(row):
            col = chr(65 + c)
            idx = strings.index(val)
            cells.append(f'<c r="{col}{r}" t="s"><v>{idx}</v></c>')
        body.append(f'<row r="{r}">{"".join(cells)}</row>')
    ns = "http://schemas.openxmlformats.org/spreadsheetml/2006/main"
    pkg = "http://schemas.openxmlformats.org/package/2006/relationships"
    rel = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
    with zipfile.ZipFile(path, "w") as z:
        z.writestr("[Content_Types].xml",
                   '<?xml version="1.0" encoding="UTF-8"?>'
                   '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
                   '<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>'
                   '<Default Extension="xml" ContentType="application/xml"/>'
                   '<Override PartName="/xl/workbook.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml"/>'
                   '<Override PartName="/xl/worksheets/sheet1.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"/>'
                   '<Override PartName="/xl/sharedStrings.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.sharedStrings+xml"/>'
                   '<Override PartName="/xl/styles.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.styles+xml"/>'
                   "</Types>")
        z.writestr("_rels/.rels", f'<?xml version="1.0"?><Relationships xmlns="{pkg}"><Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="xl/workbook.xml"/></Relationships>')
        z.writestr("xl/workbook.xml", f'<?xml version="1.0"?><workbook xmlns="{ns}" xmlns:r="{rel}"><sheets><sheet name="명단" sheetId="1" r:id="rId1"/></sheets></workbook>')
        z.writestr("xl/_rels/workbook.xml.rels", f'<?xml version="1.0"?><Relationships xmlns="{pkg}"><Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet" Target="worksheets/sheet1.xml"/><Relationship Id="rId2" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/sharedStrings" Target="sharedStrings.xml"/><Relationship Id="rId3" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/styles" Target="styles.xml"/></Relationships>')
        z.writestr("xl/sharedStrings.xml", f'<?xml version="1.0"?><sst xmlns="{ns}" count="{len(strings)}" uniqueCount="{len(strings)}">{shared}</sst>')
        z.writestr("xl/styles.xml", f'<?xml version="1.0"?><styleSheet xmlns="{ns}"><fonts count="1"/><fills count="1"/><borders count="1"/><cellXfs count="1"><xf/></cellXfs></styleSheet>')
        z.writestr("xl/worksheets/sheet1.xml", f'<?xml version="1.0"?><worksheet xmlns="{ns}"><sheetData>{"".join(body)}</sheetData></worksheet>')


if __name__ == "__main__":
    unittest.main()
