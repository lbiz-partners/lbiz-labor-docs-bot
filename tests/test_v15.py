"""v1.5 — 2027 건강보험 요율, 휴게 생략 단서, 보육수당·출산지원금."""
import json
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from nomudocs import calc  # noqa: E402
from nomudocs.checks import check  # noqa: E402
from nomudocs.docs.ledger import _tax_kind, rows_to_entries  # noqa: E402
from nomudocs.generate import generate, prepare  # noqa: E402
from nomudocs.xlsx_roster import read_workbook  # noqa: E402

LTC_NOTE = "2026-10-30 장기요양위원회 0.9994% 의결, 보건복지부공고 제2026-846호 입법예고 중. 개정 시행령 공포 전이라 2026 요율로 임시 계산"
EI_NOTE = "고용노동부공고 제2026-450호 입법예고(실업급여 1천분의 18→20, 근로자 0.9%→1.0%). 공포 전이라 0.9%로 임시 계산"
BIRTH_Q = "출생일 2년 이내·최대 2회·친족 특수관계 제외"
WAIVER_MSG = "근로자가 직접 요청한 경우에만 생략 가능. 요청 사실을 서면으로 남겨 두세요"


def sample(name):
    return json.loads((ROOT / "samples" / f"{name}.json").read_text(encoding="utf-8"))


def codes(data, level=None):
    data, result = prepare(data)
    rep = check(data, result)
    return rep, rep.codes(level)


class Health2027(unittest.TestCase):
    def payroll(self, base, **kw):
        inp = {
            "payType": "monthly", "baseSalary": base, "payDate": "2027-01-25",
            "periodFrom": "2027-01-01", "periodTo": "2027-01-31", "incomeTax": {"family": 1},
        }
        inp.update(kw)
        return calc.payroll(inp)

    def test_rate_confirmed_without_flag_when_cap_does_not_bind(self):
        r = self.payroll(2000000)
        health = r["yearBasis"]["insurance"]["rates"]["health"]
        self.assertTrue(health["confirmed"])
        self.assertAlmostEqual(health["rateTotal"], 0.0719)
        self.assertAlmostEqual(health["rateWorker"], 0.03595)
        self.assertEqual(health["checked"], "2026-11-24")
        self.assertIn("1만분의 719", health["src"])
        self.assertNotIn("[확인 필요]", health["src"])
        self.assertNotIn("pending", health)
        self.assertIsNone(r["yearBasis"]["insurance"]["healthPremiumBound"])
        self.assertFalse(any("상한" in w or "하한" in w for w in r["meta"]["warnings"]))
        self.assertEqual(r["deductions"]["healthInsurance"], 71900)
        self.assertEqual(r["deductions"]["longTermCare"], 9440)
        self.assertEqual(r["deductions"]["employmentInsurance"], 18000)
        self.assertEqual(r["deductions"]["nationalPension"], 100000)

    def test_pending_notes_exact_and_2026_rates_kept(self):
        r = self.payroll(2600000)
        rates = r["yearBasis"]["insurance"]["rates"]
        self.assertEqual(rates["longTermCare"]["pending"], LTC_NOTE)
        self.assertEqual(rates["employment"]["pending"], EI_NOTE)
        for key in ("longTermCare", "employment"):
            self.assertFalse(rates[key]["confirmed"])
            self.assertIn("[확인 필요]", rates[key]["src"])
            self.assertIn("공포 전", rates[key]["src"])
        self.assertNotIn("health", r["yearBasis"]["insurance"]["rates"]["longTermCare"]["pending"])

    def test_cap_and_floor_flag_only_when_they_bind(self):
        capped = self.payroll(130000000)
        cap_note = capped["yearBasis"]["insurance"]["healthPremiumBound"]["note"]
        self.assertIn("[확인 필요]", cap_note)
        self.assertIn("9,183,480", cap_note)
        self.assertNotIn("[확인 필요]", capped["yearBasis"]["insurance"]["rates"]["health"]["src"])
        self.assertEqual(capped["deductions"]["healthInsurance"], 4591740)
        floored = self.payroll(200000)
        floor_note = floored["yearBasis"]["insurance"]["healthPremiumBound"]["note"]
        self.assertIn("[확인 필요]", floor_note)
        self.assertIn("20,160", floor_note)
        self.assertNotIn("상한", floor_note)
        self.assertEqual(floored["deductions"]["healthInsurance"], 10080)
        y2026 = calc.payroll({
            "payType": "monthly", "baseSalary": 200000, "payDate": "2026-06-25",
            "periodFrom": "2026-06-01", "periodTo": "2026-06-30", "incomeTax": {"family": 1},
        })
        self.assertIsNone(y2026["yearBasis"]["insurance"]["healthPremiumBound"])
        self.assertNotIn("[확인 필요]", y2026["yearBasis"]["insurance"]["rates"]["health"]["src"])


class BreakWaiver(unittest.TestCase):
    def contract(self, start, end="13:00", waived=True):
        d = sample("contract_regular")
        d["contract"]["startDate"] = start
        d["work"]["end"] = end
        d["work"]["breaks"] = []
        d["work"]["breakMin"] = 0
        d["work"]["breakWaivedByWorker"] = waived
        return d

    def test_boundary_and_scope_flag(self):
        before, before_err = codes(self.contract("2026-12-09"), "error")
        before_warn = before.codes("warn")
        self.assertIn("BREAK", before_err)
        self.assertNotIn("BREAK", before_warn)
        after, after_err = codes(self.contract("2026-12-10"), "error")
        after_warn = [x for x in after.findings if x.code == "BREAK" and x.level == "warn"]
        self.assertNotIn("BREAK", after_err)
        self.assertEqual(len(after_warn), 5)  # 월~금
        self.assertIn(WAIVER_MSG, after_warn[0].msg)
        self.assertIn("[확인 필요]", after_warn[0].msg)
        self.assertIn("1350", after_warn[0].msg)
        self.assertIn("제21784호", after_warn[0].basis)
        eight, eight_err = codes(self.contract("2026-12-10", end="18:00"), "error")
        self.assertIn("BREAK", eight_err)
        self.assertNotIn("BREAK", eight.codes("warn"))

    def test_contract_break_wording(self):
        from docx import Document
        import tempfile
        d = self.contract("2026-12-10")
        with tempfile.TemporaryDirectory() as td:
            out = generate(d, td, stem="brk", pdf=False, png=False)
            text = "\n".join(p.text for p in Document(out["docx"]).paragraphs)
        self.assertIn("근로자가 휴게시간을 이용하지 아니할 것을 명시적으로 요청", text)
        self.assertIn("법률 제21784호", text)
        self.assertIn(WAIVER_MSG, text)
        self.assertIn("[확인 필요]", text)
        self.assertIn("1350", text)


class ChildcareAndBirth(unittest.TestCase):
    def test_two_children_doubles_the_exempt_limit(self):
        def slip(children):
            d = sample("payslip")
            d["extraEarnings"] = list(d["extraEarnings"]) + [
                {"name": "보육수당", "amount": 400000, "kind": "childcare", "taxFree": True},
            ]
            d["childcareChildren"] = children
            return prepare(d)[1]

        two, one = slip(2), slip(1)
        self.assertEqual(two["earnings"]["taxFree"]["childcare"], 400000)
        self.assertEqual(one["earnings"]["taxFree"]["childcare"], 200000)
        self.assertEqual(two["earnings"]["grossPay"], one["earnings"]["grossPay"])
        self.assertEqual(one["earnings"]["taxableGross"] - two["earnings"]["taxableGross"], 200000)
        self.assertEqual(two["taxFreeChildcare"]["children"], 2)
        self.assertEqual(two["taxFreeChildcare"]["limit"], 400000)

    def test_birth_is_fully_tax_free_and_asks(self):
        d = sample("payslip")
        d["extraEarnings"] = list(d["extraEarnings"]) + [
            {"name": "출산지원금", "amount": 1000000, "kind": "birth", "taxFree": True},
        ]
        data, r = prepare(d)
        _, base = prepare(sample("payslip"))
        self.assertEqual(r["earnings"]["taxFree"]["birth"], 1000000)
        self.assertEqual(r["taxFreeBirth"]["question"], BIRTH_Q)
        self.assertTrue(r["taxFreeBirth"]["fullyTaxFree"])
        self.assertEqual(r["earnings"]["taxableGross"], base["earnings"]["taxableGross"])
        self.assertEqual(r["earnings"]["grossPay"], base["earnings"]["grossPay"] + 1000000)
        rep = check(data, r)
        found = [x for x in rep.findings if x.code == "BIRTH_SUPPORT"]
        self.assertTrue(found and BIRTH_Q in found[0].msg)
        self.assertIn("§12", found[0].basis)

    def test_roster_columns_and_tax_kind(self):
        self.assertEqual(_tax_kind("출산")["kind"], "birth")
        self.assertEqual(_tax_kind("보육")["kind"], "childcare")
        self.assertNotEqual(_tax_kind("출산").get("kind"), "childcare")
        entries, bad = rows_to_entries([
            ["성명", "수당1이름", "수당1금액", "수당1비과세", "6세이하자녀수"],
            ["홍길동", "보육수당", 400000, "보육", 2],
            ["김하나", "출산지원금", 500000, "출산", None],
        ])
        self.assertEqual(bad, [])
        self.assertEqual(entries[0]["extraEarnings"][0]["kind"], "childcare")
        self.assertEqual(entries[0]["childcareChildren"], 2)
        self.assertEqual(entries[1]["extraEarnings"][0]["kind"], "birth")
        header = read_workbook(ROOT / "samples" / "wage_ledger_roster.xlsx")["명단"][0]
        self.assertIn("6세이하자녀수", header)


class LodgingBasis(unittest.TestCase):
    def test_foreign_lodging_cites_article(self):
        d = sample("contract_foreign")
        d["lodging"]["type"] = "컨테이너"
        rep, _ = codes(d)
        found = [x for x in rep.findings if x.code == "F_LODGING_TYPE"]
        self.assertEqual(len(found), 1)
        self.assertIn("§22의2", found[0].basis)
        self.assertIn("제21786호", found[0].basis)
        self.assertIn("2027-06-10", found[0].basis)


if __name__ == "__main__":
    unittest.main()
