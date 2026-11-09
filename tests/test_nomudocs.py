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


class PayYearBasis(unittest.TestCase):
    """v1.2 — 소득세는 지급일, 4대보험은 몇 월분 보험료(귀속월) 기준."""

    def dec2026(self, **kw):
        d = sample("payslip")
        d.update({"periodLabel": "2026년 12월", "periodFrom": "2026-12-01", "periodTo": "2026-12-31", "payDate": "2027-01-10"})
        d.update(kw)
        return d

    def test_dec_work_paid_jan(self):
        # 2026년 12월분을 2027-01-10에 지급: 소득세는 2027(지급일), 4대보험은 2026 요율, 4대보험 미등록 경고 없음
        data, r = prepare(self.dec2026())
        yb = r["yearBasis"]
        self.assertEqual(yb["incomeTax"]["basis"], "payDate")
        self.assertEqual(yb["incomeTax"]["year"], 2027)
        self.assertEqual(yb["insurance"]["month"], "2026-12")
        self.assertEqual(yb["insurance"]["year"], 2026)
        self.assertEqual(yb["insurance"]["pensionPeriod"], "2026H2")
        self.assertEqual(yb["insurance"]["unconfirmed"], [])
        self.assertIn("소득세·지방소득세: 2027-01-10 지급일 기준", yb["label"])
        self.assertIn("4대보험: 2026년 12월분 기준", yb["label"])
        ws = r["meta"]["warnings"]
        self.assertFalse([w for w in ws if "4대보험 요율" in w or "보험료율" in w or "미등록" in w], ws)
        self.assertFalse([w for w in ws if "2027H1" in w], ws)
        # 숫자: 2026 요율 그대로(지급일 2026-12 로 계산한 것과 4대보험이 같아야 함)
        _, r26 = prepare(self.dec2026(payDate="2026-12-31"))
        for k in ("nationalPension", "healthInsurance", "longTermCare", "employmentInsurance", "incomeTax", "localIncomeTax"):
            self.assertEqual(r["deductions"][k], r26["deductions"][k], k)
        taxable = r["earnings"]["taxableGross"]
        self.assertEqual(r["deductions"]["nationalPension"], int(taxable // 1000 * 1000 * 0.0475 // 10 * 10))
        d = r["deductions"]
        self.assertEqual(d["totalDeductions"], d["insuranceTotal"] + d["incomeTax"] + d["localIncomeTax"] + d["otherDeductions"])
        self.assertEqual(r["netPay"], r["earnings"]["grossPay"] - d["totalDeductions"])

    def test_insurance_month_2027_01(self):
        # 1월분 보험료를 떼는 회사: 국민연금 2027 요율(근로자 5.00%), 나머지는 [확인 필요]
        data, r = prepare(self.dec2026(insuranceMonth="2027-01"))
        yb = r["yearBasis"]["insurance"]
        self.assertEqual(yb["month"], "2027-01")
        self.assertEqual(yb["source"], "insuranceMonth")
        self.assertTrue(yb["rates"]["nationalPension"]["confirmed"])
        self.assertAlmostEqual(yb["rates"]["nationalPension"]["rateWorker"], 0.05)
        self.assertIn("제20903호", yb["rates"]["nationalPension"]["src"])
        self.assertEqual(yb["rates"]["nationalPension"]["checked"], "2026-11-09")
        for k in ("health", "longTermCare", "employment"):
            self.assertFalse(yb["rates"][k]["confirmed"], k)
            self.assertIn("[확인 필요]", yb["rates"][k]["src"])
        self.assertEqual(yb["unconfirmed"], ["건강보험", "장기요양보험", "고용보험"])
        self.assertEqual(yb["pensionPeriod"], "2026H2")  # 2026.7~2027.6 적용기
        taxable = r["earnings"]["taxableGross"]
        self.assertEqual(r["deductions"]["nationalPension"], int(taxable // 1000 * 1000 * 0.05 // 10 * 10))
        ws = " ".join(r["meta"]["warnings"])
        self.assertIn("[확인 필요]", ws)
        self.assertIn("근로자 5.00%", ws)
        # 소득세는 그대로 지급일 기준 — 12월분 기준과 같은 값
        _, r12 = prepare(self.dec2026())
        self.assertEqual(r["deductions"]["incomeTax"], r12["deductions"]["incomeTax"])
        self.assertEqual(r["deductions"]["healthInsurance"], r12["deductions"]["healthInsurance"])

    def test_default_month_from_paydate_without_period(self):
        r = calc.payroll({"baseSalary": 2600000, "payDate": "2026-11-25"})
        self.assertEqual(r["yearBasis"]["insurance"]["month"], "2026-11")
        self.assertEqual(r["yearBasis"]["insurance"]["source"], "payDate")

    def test_bad_insurance_month_falls_back(self):
        _, r = prepare(self.dec2026(insuranceMonth="12월"))
        self.assertEqual(r["yearBasis"]["insurance"]["month"], "2026-12")
        self.assertTrue(any("insuranceMonth" in w for w in r["meta"]["warnings"]))

    def test_outputs_show_basis_and_guidance(self):
        from docx import Document
        with tempfile.TemporaryDirectory() as td:
            out = generate(self.dec2026(), td, stem="yb", pdf=False, png=False)
            j = json.loads((Path(td) / "yb.점검결과.json").read_text(encoding="utf-8"))
            b = j["payroll"]["basis"]
            self.assertEqual(b["insurance"]["month"], "2026-12")
            self.assertIn("4대보험 최종 금액은 공단 고지액을 따릅니다.", b["guidance"])
            self.assertIn("지급일은 실제 준 날짜를 넣어야 합니다.", b["guidance"])
            texts = "\n".join(p.text for p in Document(out["docx"]).paragraphs)
            self.assertIn("소득세·지방소득세: 2027-01-10 지급일 기준 / 4대보험: 2026년 12월분 기준", texts)
            self.assertIn("4대보험 최종 금액은 공단 고지액을 따릅니다.", texts)
            self.assertIn("지급일은 실제 준 날짜를 넣어야 합니다.", texts)
            out = generate(self.dec2026(insuranceMonth="2027-01"), Path(td) / "b", stem="yb2", pdf=False, png=False)
            doc = Document(out["docx"])
            cells = "\n".join(c.text for t in doc.tables for row in t.rows for c in row.cells)
            self.assertIn("근로자 부담분 5.00%", cells)
            self.assertIn("[확인 필요", cells)


if __name__ == "__main__":
    unittest.main()
