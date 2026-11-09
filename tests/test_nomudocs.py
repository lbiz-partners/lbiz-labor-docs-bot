"""노무 서류 도우미 자동 시험. 실행: cd build && python3 -m unittest discover -s tests -v"""
import copy
import json
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from nomudocs import __version__, calc, tool_version_label  # noqa: E402
from nomudocs.checks import check, mask_sensitive  # noqa: E402
from nomudocs.generate import Blocked, generate, prepare  # noqa: E402


def sample(name):
    return json.loads((ROOT / "samples" / f"{name}.json").read_text(encoding="utf-8"))


def run_check(data):
    data, result = prepare(data)
    return check(data, result)


class EngineValues(unittest.TestCase):
    """엔진 값이 공식 출처 값(RATES_CHECK.md)과 같은지."""

    @classmethod
    def setUpClass(cls):
        cls.r = calc.rates(2026)

    def test_min_wage(self):
        self.assertEqual(self.r["MINWAGE"]["2026"]["hour"], 10320)
        self.assertEqual(self.r["MINWAGE"]["2026"]["month209"], 2156880)

    def test_insurance_rates(self):
        ins = self.r["INSURANCE"]
        self.assertAlmostEqual(ins["nationalPension"]["rateTotal"], 0.095)
        self.assertAlmostEqual(ins["health"]["rateTotal"], 0.0719)
        self.assertAlmostEqual(ins["longTermCare"]["rateOfSalary"], 0.009448)
        self.assertAlmostEqual(ins["employment"]["rateWorker"], 0.009)

    def test_withholding_table(self):
        self.assertEqual(calc.run("withholding", {"taxable": 3500000, "family": 4})["tax"], 49340)
        self.assertEqual(calc.run("withholding", {"taxable": 5000000, "family": 4})["tax"], 219100)

    def test_health_10won_floor(self):
        r = calc.payroll({"payType": "monthly", "baseSalary": 2000000, "payDate": "2026-11-25", "family": 1})
        ded = r["deductions"]
        self.assertEqual(ded["nationalPension"], 95000)
        self.assertEqual(ded["healthInsurance"], 71900)
        self.assertEqual(ded["longTermCare"], 9440)   # 엔진 원값 9,448 → 10원 미만 절사
        self.assertEqual(ded["employmentInsurance"], 18000)
        self.assertEqual(ded["engineRounding"]["longTermCare"], 9448)


class SamplesPass(unittest.TestCase):
    def test_all_samples_have_no_missing_or_error(self):
        for f in sorted((ROOT / "samples").glob("*.json")):
            rep = run_check(json.loads(f.read_text(encoding="utf-8")))
            bad = [x for x in rep.findings if x.level in ("missing", "error")]
            self.assertEqual(bad, [], f"{f.stem}: {bad}")


class ContractRules(unittest.TestCase):
    def setUp(self):
        self.d = sample("contract_regular")

    def codes(self, d, level=None):
        return run_check(d).codes(level)

    def test_missing_place(self):
        self.d["contract"]["place"] = ""
        self.assertTrue(any(c for c in self.codes(self.d, "missing")))

    def test_min_wage_monthly(self):
        self.d["wage"]["amount"] = 2000000
        self.d["wage"]["allowances"] = []
        self.assertIn("MIN_WAGE", self.codes(self.d, "error"))

    def test_min_wage_hourly_exact_ok(self):
        d = sample("contract_parttime")
        d["wage"]["amount"] = 10320
        self.assertNotIn("MIN_WAGE", self.codes(d, "error"))
        d["wage"]["amount"] = 10319
        self.assertIn("MIN_WAGE", self.codes(d, "error"))

    def test_break_too_short(self):
        self.d["work"]["breaks"] = [{"start": "12:00", "end": "12:30"}]
        self.d["work"]["breakMin"] = 30
        self.d["work"]["end"] = "17:30"
        self.assertIn("BREAK", self.codes(self.d, "error"))

    def test_public_holiday_5plus(self):
        self.d["work"]["publicHolidaysPaid"] = False
        self.assertIn("PUBLIC_HOLIDAY", self.codes(self.d, "error"))

    def test_fixed_overtime_short(self):
        self.d["work"]["fixedOvertime"] = {"hoursMonthly": 10, "amount": 50000}
        self.assertIn("FIXED_OT_SHORT", self.codes(self.d, "error"))

    def test_toxic_clauses(self):
        self.d["specialTerms"] = ["1년 안에 그만두면 위약금 100만원을 낸다", "퇴직금은 월급에 포함한다", "여권은 회사가 보관한다"]
        errs = self.codes(self.d, "error")
        self.assertGreaterEqual(sum(1 for c in errs if c.startswith("TOXIC")), 3, errs)

    def test_sensitive_blocked(self):
        self.d["employee"]["note"] = "주민번호 950412-1234567"
        with tempfile.TemporaryDirectory() as t, self.assertRaises(Blocked):
            generate(self.d, t, pdf=False, png=False)
        masked = mask_sensitive(self.d)
        self.assertNotIn("1234567", json.dumps(masked, ensure_ascii=False))

    def test_secret_word_blocked(self):
        self.d["employee"]["note"] = "통장 비밀번호 1234"
        self.assertIn("SENSITIVE_SECRET", run_check(self.d).codes())


class MinorRules(unittest.TestCase):
    def setUp(self):
        self.d = sample("contract_minor")

    def test_hours_over_7(self):
        self.d["work"]["schedule"]["토"] = {"start": "09:00", "end": "18:00", "breakMin": 60}
        self.assertIn("MINOR_HOURS", run_check(self.d).codes("error"))

    def test_night(self):
        self.d["work"]["schedule"]["토"] = {"start": "17:00", "end": "23:00", "breakMin": 30}
        self.assertIn("MINOR_NIGHT", run_check(self.d).codes("error"))

    def test_permit_for_middle_school(self):
        self.d["minor"]["middleSchool"] = True
        self.assertIn("MINOR_PERMIT", run_check(self.d).codes("error"))

    def test_consent_missing(self):
        self.d["minor"]["guardianConsent"] = False
        self.assertIn("MINOR_CONSENT", run_check(self.d).codes("missing"))


class CertAndPayslipRules(unittest.TestCase):
    def test_cert_unrequested_salary(self):
        d = sample("cert_employment")
        d["salary"] = 3000000
        self.assertIn("C_SALARY_UNREQUESTED", run_check(d).codes("error"))

    def test_payslip_min_wage(self):
        d = sample("payslip")
        d["pay"]["baseSalary"] = 1800000
        self.assertIn("MIN_WAGE", run_check(d).codes())

    def test_unknown_doc(self):
        self.assertIn("DOC", check({"doc": "해고통지서"}).codes("error"))


class MinWageByYear(unittest.TestCase):
    """2027 최저임금(고용노동부고시 제2026-60호: 시급 10,700원·월 2,236,300원) — 기준일 연도별 적용."""

    def mwd(self, d):
        rep = run_check(d)
        return rep, rep.derived.get("minimumWage") or {}

    def test_engine_2027_values(self):
        from nomudocs import checks
        r = calc.rates(2027)
        self.assertEqual(r["MINWAGE"]["2027"]["hour"], 10700)
        self.assertEqual(r["MINWAGE"]["2027"]["month209"], 2236300)
        self.assertEqual(r["MINWAGE"]["2027"]["month209"], 10700 * 209)
        self.assertEqual(r["MINWAGE"]["2026"]["hour"], 10320)  # 2026 값 유지
        m = calc.run("minwageFor", {"year": 2027})
        self.assertTrue(m["registered"])
        self.assertEqual(m["notice"], "고용노동부고시 제2026-60호")
        self.assertEqual(checks.MIN_WAGE_2027, m["hour"])
        self.assertEqual(checks.MIN_WAGE_2026, calc.run("minwageFor", {"year": 2026})["hour"])

    def test_contract_2027_start_uses_2027(self):
        d = sample("contract_parttime")
        d["contract"]["startDate"] = "2027-01-04"
        d["wage"]["amount"] = 10500
        rep, mw = self.mwd(d)
        self.assertEqual(mw["year"], 2027)
        self.assertEqual(mw["appliedMinHourly"], 10700)
        self.assertIn("MIN_WAGE", rep.codes("error"))
        d["wage"]["amount"] = 10700  # 딱 같으면 통과
        rep, mw = self.mwd(d)
        self.assertNotIn("MIN_WAGE", rep.codes("error"))

    def test_contract_2026_start_uses_2026(self):
        d = sample("contract_parttime")
        d["contract"]["startDate"] = "2026-12-01"
        d["wage"]["amount"] = 10500
        rep, mw = self.mwd(d)
        self.assertEqual(mw["year"], 2026)
        self.assertEqual(mw["appliedMinHourly"], 10320)
        self.assertNotIn("MIN_WAGE", rep.codes("error"))
        self.assertIn("MIN_WAGE_2027", rep.codes("warn"))  # 2027-01-01까지 이어지는 계약은 미리 알림
        d["contract"]["endDate"] = "2026-12-31"
        self.assertNotIn("MIN_WAGE_2027", run_check(d).codes())

    def test_contract_monthly_2027(self):
        d = sample("contract_regular")
        d["contract"]["startDate"] = "2027-02-01"
        d["wage"]["amount"] = 2200000
        d["wage"]["allowances"] = []
        rep, mw = self.mwd(d)
        self.assertEqual(mw["year"], 2027)
        self.assertIn("MIN_WAGE", rep.codes("error"))
        self.assertIn("제2026-60호", next(f.basis for f in rep.findings if f.code == "MIN_WAGE"))
        d["contract"]["startDate"] = "2026-12-01"
        rep, mw = self.mwd(d)
        self.assertEqual(mw["year"], 2026)
        self.assertNotIn("MIN_WAGE", rep.codes("error"))

    def test_foreign_2027(self):
        d = sample("contract_foreign")  # 월 2,156,880원 = 2026 최저
        d["signDate"] = "2027-01-05"
        rep, mw = self.mwd(d)
        self.assertEqual(mw["year"], 2027)
        self.assertIn("MIN_WAGE", rep.codes("error"))
        d["signDate"] = "2026-11-20"
        rep, mw = self.mwd(d)
        self.assertEqual(mw["year"], 2026)
        self.assertNotIn("MIN_WAGE", rep.codes("error"))

    def test_payslip_period_year(self):
        d = sample("payslip")
        d["pay"]["baseSalary"] = 2200000
        d["extraEarnings"] = []
        d.update({"periodFrom": "2027-01-01", "periodTo": "2027-01-31", "payDate": "2027-02-10"})
        rep, mw = self.mwd(d)
        self.assertEqual(mw["year"], 2027)
        self.assertEqual(mw["appliedMinHourly"], 10700)
        self.assertIn("MIN_WAGE", rep.codes("error"))
        # 2026년 12월분을 2027년 1월에 지급 → 2026 값
        d.update({"periodFrom": "2026-12-01", "periodTo": "2026-12-31", "payDate": "2027-01-10"})
        rep, mw = self.mwd(d)
        self.assertEqual(mw["year"], 2026)
        self.assertEqual(mw["appliedMinHourly"], 10320)
        self.assertNotIn("MIN_WAGE", rep.codes("error"))

    def test_payslip_parttime_2027(self):
        d = sample("payslip_parttime")  # 시급 10,500원
        d.update({"periodFrom": "2027-01-01", "periodTo": "2027-01-31", "payDate": "2027-02-05"})
        rep, mw = self.mwd(d)
        self.assertEqual(mw["year"], 2027)
        self.assertIn("MIN_WAGE", rep.codes("error"))
        d = sample("payslip_parttime")
        rep, mw = self.mwd(d)
        self.assertEqual(mw["year"], 2026)
        self.assertNotIn("MIN_WAGE", rep.codes("error"))

    def test_payroll_bridge_2027(self):
        r = calc.payroll({"payType": "monthly", "baseSalary": 2200000, "payDate": "2027-01-25", "family": 1})
        self.assertEqual(r["minimumWage"]["usingYear"], 2027)
        self.assertTrue(r["minimumWage"]["violated"])
        ws = " ".join(r["meta"]["warnings"])
        self.assertIn("4대보험 요율·간이세액표", ws)  # 2027 보험·세율은 아직 미등록이라는 경고는 남김
        self.assertIn("10,700", ws)
        r = calc.payroll({"payType": "monthly", "baseSalary": 2200000, "payDate": "2026-11-25", "family": 1})
        self.assertEqual(r["minimumWage"]["usingYear"], 2026)
        self.assertFalse(r["minimumWage"]["violated"])


class Generate(unittest.TestCase):
    def test_docx_pdf_png(self):
        if not shutil.which("soffice") and not shutil.which("libreoffice"):
            self.skipTest("LibreOffice 없음")
        with tempfile.TemporaryDirectory() as t:
            out = generate(sample("payslip"), t, stem="p")
            self.assertTrue(Path(out["docx"]).exists())
            self.assertTrue(Path(out["pdf"]).exists())
            self.assertGreaterEqual(len(out["png"]), 1)

    def test_docx_only_every_sample(self):
        with tempfile.TemporaryDirectory() as t:
            for f in sorted((ROOT / "samples").glob("*.json")):
                out = generate(json.loads(f.read_text(encoding="utf-8")), Path(t) / f.stem, stem=f.stem, pdf=False, png=False)
                self.assertTrue(Path(out["docx"]).exists(), f.stem)



class ToolVersion(unittest.TestCase):
    """결과물에 도구 판 번호가 찍히는지."""

    def test_version_matches_file(self):
        self.assertEqual(__version__, (ROOT / "VERSION").read_text(encoding="utf-8").strip())
        self.assertEqual(tool_version_label(), f"도구 판 v{__version__}")

    def test_tool_version_in_docx_and_json(self):
        label = tool_version_label()
        with tempfile.TemporaryDirectory() as td:
            out = generate(sample("contract_regular"), td, stem="vcheck", pdf=False, png=False)
            self.assertEqual(out.get("tool_version"), __version__)
            j = json.loads((Path(td) / "vcheck.점검결과.json").read_text(encoding="utf-8"))
            self.assertEqual(j.get("tool_version"), __version__)
            from docx import Document
            doc = Document(out["docx"])
            texts = [para.text for para in doc.paragraphs]
            joined = "\n".join(texts)
            self.assertIn(label, joined)
            self.assertEqual(joined.count(label), 1)

    def test_tool_version_every_sample_docx(self):
        label = tool_version_label()
        from docx import Document
        with tempfile.TemporaryDirectory() as td:
            for f in sorted((ROOT / "samples").glob("*.json")):
                out = generate(json.loads(f.read_text(encoding="utf-8")), Path(td) / f.stem, stem=f.stem, pdf=False, png=False)
                self.assertEqual(out.get("tool_version"), __version__, f.stem)
                texts = [para.text for para in Document(out["docx"]).paragraphs]
                self.assertIn(label, "\n".join(texts), f.stem)


if __name__ == "__main__":
    unittest.main()
