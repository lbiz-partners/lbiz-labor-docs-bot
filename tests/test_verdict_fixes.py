"""2026-11-11 출고 판정(수정 필요) 결함 10건 — M-1~M-4, L-1~L-6 고친 것 시험.
실행: python3 -m unittest discover -s tests -v"""
import json
import random
import re
import sys
import tempfile
import unittest
from datetime import date, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from nomudocs import ATTRIBUTION, tool_version_label  # noqa: E402
from nomudocs.generate import FOOTER, generate, prepare  # noqa: E402
from nomudocs.checks import check  # noqa: E402
from nomudocs.timeutil import _end_of_months, tenure_text, tenure_ymd  # noqa: E402

DRAFT = ROOT / "docs" / "bot-instructions-draft"
PROFILE = DRAFT / "profile-description.md"
START = DRAFT / "lbiz-labor-docs-getting-started" / "SKILL.md"
RULES = DRAFT / "lbiz-labor-docs-rules" / "SKILL.md"
CARD = DRAFT / "template-card.md"


def sample(name):
    return json.loads((ROOT / "samples" / f"{name}.json").read_text(encoding="utf-8"))


def run(data):
    data, result = prepare(data)
    return check(data, result), result


def docx_text(path):
    from docx import Document
    doc = Document(path)
    paras = "\n".join(p.text for p in doc.paragraphs)
    cells = "\n".join(c.text for t in doc.tables for row in t.rows for c in row.cells)
    foot = "\n".join(p.text for s in doc.sections for p in s.footer.paragraphs)
    return paras + "\n" + cells + "\n" + foot


def make(data, stem="x"):
    td = tempfile.mkdtemp()
    out = generate(data, td, stem=stem, pdf=False, png=False)
    return out, docx_text(out["docx"])


# ─────────────── M-1 통상임금 확인 알림 ───────────────
class M1OrdinaryWage(unittest.TestCase):
    def test_payslip_fixed_meal_warns_and_asks(self):
        rep, r = run(sample("payslip"))  # 기본급 260만 + 매달 고정 식대 20만, 연장 10·야간 2 (판정 P1)
        f = [x for x in rep.findings if x.code == "ORDINARY_WAGE_CHECK"]
        self.assertEqual(len(f), 1)
        self.assertEqual(f[0].level, "warn")
        self.assertIn("식대", f[0].msg)
        self.assertIn("확인해 주세요", f[0].msg)          # 묻기만 하고
        self.assertIn("들어갈 수 있어요", f[0].msg)       # 단정하지 않는다
        self.assertNotRegex(f[0].msg, r"들어갑니다|포함해야 합니다|위법")
        self.assertIn("연장·야간·휴일", f[0].msg)
        self.assertIn("근로기준법 시행령 §6①", f[0].basis)
        self.assertIn("2020다247190", f[0].basis)
        self.assertEqual(r["input"]["hourlyOrdinary"], 12440)  # 도구가 직접 바꾸지 않음

    def test_payslip_owner_sets_ordinary_monthly(self):
        d = sample("payslip")
        d["pay"]["ordinaryMonthly"] = 2800000
        rep, r = run(d)
        self.assertNotIn("ORDINARY_WAGE_CHECK", rep.codes())
        self.assertEqual(r["input"]["hourlyOrdinary"], 13397)
        self.assertEqual(r["earnings"]["overtimePay"], 200957)

    def test_payslip_variable_or_bonus_only_no_warn(self):
        d = sample("payslip")
        d["extraEarnings"] = [{"name": "성과급", "amount": 100000, "bonus": True},
                              {"name": "출장비", "amount": 50000, "variable": True, "method": "출장일수 × 1만원"}]
        self.assertNotIn("ORDINARY_WAGE_CHECK", run(d)[0].codes())

    def test_payslip_no_hours_still_warns_without_hours_sentence(self):
        d = sample("payslip")
        d["hours"] = {}
        f = [x for x in run(d)[0].findings if x.code == "ORDINARY_WAGE_CHECK"]
        self.assertEqual(len(f), 1)
        self.assertNotIn("이번에는 연장", f[0].msg)

    def test_contract_fixed_allowance_warns(self):
        d = sample("contract_regular")  # 식대 매월 고정
        rep, _ = run(d)
        self.assertIn("ORDINARY_WAGE_CHECK", rep.codes("warn"))
        d["wage"]["ordinaryMonthly"] = 2800000
        self.assertNotIn("ORDINARY_WAGE_CHECK", run(d)[0].codes())
        d2 = sample("contract_regular")
        d2["wage"]["allowances"][0]["monthlyRegular"] = False
        self.assertNotIn("ORDINARY_WAGE_CHECK", run(d2)[0].codes())

    def test_contract_fixed_overtime_uses_ordinary_monthly(self):
        d = sample("contract_regular")
        d["work"]["fixedOvertime"] = {"hoursMonthly": 10, "amount": 190000}
        rep, _ = run(d)
        self.assertNotIn("FIXED_OT_SHORT", rep.codes("error"))  # 기본급 기준이면 충분
        d["wage"]["ordinaryMonthly"] = 2800000
        rep, _ = run(d)
        self.assertIn("FIXED_OT_SHORT", rep.codes("error"))     # 통상임금을 정하면 그 금액 기준


# ─────────────── M-2 근속기간 ───────────────
class M2Tenure(unittest.TestCase):
    CASES = [
        ("2022-03-02", "2026-11-09", "4년 8개월 8일"),   # 판정 E1 (예전: 총 4년 9개월)
        ("2020-03-02", "2026-06-30", "6년 3개월 29일"),  # 판정 E2 (예전: 총 6년 4개월)
        ("2026-03-02", "2026-03-02", "1일"),            # 같은 날 = 하루 (예전: 총 1개월)
        ("2026-03-02", "2026-03-03", "2일"),
        ("2026-03-02", "2026-04-01", "1개월"),          # 딱 1개월 (예전: 총 2개월)
        ("2026-03-02", "2026-03-31", "30일"),
        ("2026-01-31", "2026-02-28", "1개월"),          # 말일 시작 → 2월 말일
        ("2026-01-31", "2026-03-01", "1개월 1일"),
        ("2026-01-30", "2026-02-27", "29일"),          # 1/30·31 + 2/1~27
        ("2024-01-31", "2024-02-29", "1개월"),          # 윤년 2월
        ("2024-02-29", "2025-02-28", "1년"),            # 윤일 입사
        ("2024-02-29", "2025-02-27", "11개월 30일"),
        ("2023-03-01", "2024-02-29", "1년"),
        ("2024-03-01", "2025-02-28", "1년"),
        ("2025-12-01", "2026-11-30", "1년"),
        ("2025-12-01", "2026-11-29", "11개월 29일"),
    ]

    def test_exact_cases(self):
        for a, b, want in self.CASES:
            self.assertEqual(tenure_text(a, b), want, (a, b))

    def test_empty_or_reversed(self):
        self.assertEqual(tenure_text(None, "2026-01-01"), "")
        self.assertEqual(tenure_text("2026-03-02", "2026-03-01"), "")

    def test_never_longer_than_actual(self):
        rnd = random.Random(20261111)
        for _ in range(3000):
            a = date(2018, 1, 1) + timedelta(days=rnd.randrange(0, 3650))
            b = a + timedelta(days=rnd.randrange(0, 2500))
            y, m, d = tenure_ymd(a.isoformat(), b.isoformat())
            n = y * 12 + m
            # 꽉 찬 n개월이 끝난 날 + 남은 d일 = 끝날 (정확히 맞아떨어짐)
            self.assertEqual(_end_of_months(a, n) + timedelta(days=d), b, (a, b))
            # n개월은 끝날을 넘지 않고, n+1개월은 끝날을 넘는다(올림 없음·버림 없음)
            self.assertLessEqual(_end_of_months(a, n), b)
            self.assertGreater(_end_of_months(a, n + 1), b)
            self.assertLess(d, 32)

    def test_certificates_print_exact(self):
        _, t = make(sample("cert_employment"), "e1")
        self.assertIn("(총 4년 8개월 8일)", t)
        self.assertNotIn("4년 9개월", t)
        d = sample("cert_career")
        d["periods"] = [{"from": "2020-03-02", "to": "2026-06-30", "dept": "영업팀", "position": "사원"}]
        out, t = make(d, "e2")
        self.assertIn("(총 6년 3개월 29일)", t)
        self.assertEqual(out["report"]["derived"]["tenure"], {"years": 6, "months": 3, "days": 29})


# ─────────────── M-3 봇 지침·스킬 초안 ───────────────
class M3Drafts(unittest.TestCase):
    def setUp(self):
        self.p, self.s, self.r, self.c = (x.read_text(encoding="utf-8") for x in (PROFILE, START, RULES, CARD))

    def test_files_exist_as_drafts(self):
        for f in (PROFILE, START, RULES, CARD, DRAFT / "README.md"):
            self.assertTrue(f.exists(), f)
        self.assertIn("초안", self.c)
        self.assertIn("게시", self.c)

    def test_v12_year_basis_in_rules_and_profile(self):
        for t in (self.p, self.r):
            self.assertIn("insuranceMonth", t)
            self.assertIn("실제", t)               # 실제 지급일
            self.assertIn("몇 월분", t)
            self.assertIn("5.00%", t)              # 2027 국민연금 반영
            self.assertIn("[확인 필요]", t)
            self.assertNotIn("2026년 값만", t)      # 옛 문장 삭제
        self.assertIn("바꾸지 않", self.r)          # 날짜를 바꿔 경고 피하기 금지
        self.assertIn("2027", self.r)

    def test_rules_ask_ordinary_wage_and_children(self):
        self.assertIn("통상임금", self.r)
        self.assertIn("ORDINARY_WAGE_CHECK", self.r)
        self.assertIn("8세 이상 20세 이하", self.r)
        self.assertIn("8세 이상 20세 이하", self.p)

    def test_release_check_kept(self):
        # 하루 한 번 새 판 확인(시작하기 3-2)은 그대로
        for line in ('if [ -f ~/nomu-tool/.last_check ] && [ "$(cat ~/nomu-tool/.last_check)" = "$TODAY" ]; then',
                     '&& (cd "$TMP/new" && sha256sum -c MANIFEST.txt) \\',
                     'rm -rf ~/nomu-tool.prev',
                     '### 3-2. 하루 한 번만 새 판 확인 (이미 설치돼 있을 때)'):
            self.assertIn(line, self.s)

    def test_style_rules(self):
        allt = self.p + self.s + self.r + self.c
        self.assertNotIn("대가" + " 없이", allt)
        self.assertIn("먼저 물을 때만", self.p)    # 묻지 않은 소개 금지 유지
        self.assertIn("처음 말할 때 한 번만", self.p)  # 법령 링크는 처음 한 번만
        self.assertIn("처음 말할 때 한 번만", self.s)


# ─────────────── M-4 만든 곳·저작권·라이선스·출처 ───────────────
class M4Notice(unittest.TestCase):
    def test_notice_file(self):
        t = (ROOT / "NOTICE.md").read_text(encoding="utf-8")
        for w in ("엘비즈파트너스", "저작권", "라이선스", "nomu-payroll", "nomu-people", "engine/vendor", "[확인 필요"):
            self.assertIn(w, t)

    def test_readme_and_outputs(self):
        self.assertIn("엘비즈파트너스", (ROOT / "README.md").read_text(encoding="utf-8"))
        self.assertIn("NOTICE.md", (ROOT / "README.md").read_text(encoding="utf-8"))
        out, t = make(sample("payslip"), "m4")
        self.assertIn(f"{tool_version_label()} · {ATTRIBUTION}", t)
        self.assertEqual(out["made_by"], ATTRIBUTION)
        self.assertIn("엘비즈파트너스", (CARD).read_text(encoding="utf-8"))


# ─────────────── 낮음 6건 ───────────────
class LowFixes(unittest.TestCase):
    def p2027(self, **kw):
        d = sample("payslip")
        d.update({"periodLabel": "2027년 1월", "periodFrom": "2027-01-01", "periodTo": "2027-01-31", "payDate": "2027-01-25"})
        d.update(kw)
        return d

    def test_L1_2027_rates_status_from_official_text(self):
        _, r = run(self.p2027())
        rates = r["yearBasis"]["insurance"]["rates"]
        self.assertIn("2027-01-01 시행", rates["health"]["src"])
        self.assertIn("1만분의 719", rates["health"]["src"])
        for k in ("longTermCare", "employment"):
            self.assertIn("공포 전", rates[k]["src"])
            self.assertIn("[확인 필요]", rates[k]["src"])
        _, t = make(self.p2027(), "l1")
        self.assertIn("공포 전", t)
        # 공포 전 값(장기요양 0.9994% 등)은 넣지 않는다 — 2026 요율로 임시 계산
        self.assertEqual(r["deductions"]["longTermCare"], 13220)

    def test_L2_income_tax_line_flags_2027_table(self):
        d = sample("payslip")
        d.update({"periodLabel": "2026년 12월", "periodFrom": "2026-12-01", "periodTo": "2026-12-31", "payDate": "2027-01-10"})
        _, t = make(d, "l2")
        line = [x for x in t.split("\n") if "간이세액표 · 공제대상 가족" in x]
        self.assertTrue(line and "[확인 필요: 2027년 간이세액표" in line[0], line)
        _, t26 = make(sample("payslip"), "l2b")
        self.assertNotIn("년 간이세액표 개정 여부 미확인", t26)

    def test_L3_footer(self):
        self.assertNotIn("2026년 기준", FOOTER)
        self.assertNotIn("2027년 최저임금 반영", FOOTER)
        self.assertIn("점검결과", FOOTER)
        _, t = make(sample("cert_employment"), "l3")
        self.assertIn(FOOTER, t)

    def test_L4_no_tag_v1_install_refs(self):
        readme = (ROOT / "README.md").read_text(encoding="utf-8")
        self.assertNotIn("--branch v1 ", readme)
        self.assertNotIn("build/", readme)
        self.assertNotRegex(readme, r"unittest \d+개")
        self.assertIn("releases/latest", readme)
        self.assertNotIn("태그 v1)", PROFILE.read_text(encoding="utf-8"))
        self.assertNotIn("--branch v1 ", RULES.read_text(encoding="utf-8"))
        self.assertFalse((ROOT / "skills").exists())  # 옛 초안 지움(실제 스킬과 달랐음)

    def test_L5_single_first_run_notice_and_no_honsa(self):
        notice = "법률 자문은 아니에요"
        allt = [PROFILE.read_text(encoding="utf-8"), START.read_text(encoding="utf-8"), RULES.read_text(encoding="utf-8")]
        self.assertEqual(sum(t.count(notice) for t in allt), 1)
        self.assertEqual(sum(t.count("안녕하세요, 노무 서류 도우미예요") for t in allt), 1)
        self.assertNotIn("저는 사장님이 알려 주신 내용으로 양식을 채우고", allt[0])  # 지침 쪽 두 번째 안내문 삭제
        _, t = make(sample("cert_employment"), "l5")
        self.assertIn("주식회사 예시상사에 재직 중임을 증명합니다", t)
        self.assertNotIn("본사", t)
        d = sample("cert_career")
        _, t = make(d, "l5b")
        self.assertIn("주식회사 예시상사에 근무하였음을 증명합니다", t)
        d["employer"]["name"] = ""
        _, t = make(d, "l5c")
        self.assertNotIn("본사", t)
        self.assertRegex(t, r"위 기간 동안 　+에 근무하였음")

    def test_L6_children_8_to_20(self):
        base = sample("payslip")
        base.update({"pay": {"type": "monthly", "baseSalary": 3500000}, "extraEarnings": [], "hours": {},
                     "periodLabel": "2027년 1월", "periodFrom": "2027-01-01", "periodTo": "2027-01-31", "payDate": "2027-01-25"})
        new = json.loads(json.dumps(base)); new["incomeTax"] = {"family": 4, "children8to20": 2}
        old = json.loads(json.dumps(base)); old["incomeTax"] = {"family": 4, "childrenUnder20": 2}
        _, rn = run(new)
        _, ro = run(old)
        self.assertEqual(rn["deductions"]["incomeTax"], ro["deductions"]["incomeTax"])
        _, t = make(new, "l6")
        self.assertIn("8세 이상 20세 이하 자녀 2명", t)
        nokey = json.loads(json.dumps(base)); nokey["incomeTax"] = {"family": 3}
        f = [x for x in run(nokey)[0].findings if x.code == "P_CHILDREN"]
        self.assertTrue(f and "8세 이상 20세 이하" in f[0].msg and "별표 2" in f[0].basis)


if __name__ == "__main__":
    unittest.main()
