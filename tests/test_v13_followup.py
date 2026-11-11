"""재검수(2026-11-11) 추가 수정 — N-1 판 번호 1.3, N-2 증명서 날짜가 거꾸로면 만들지 않음."""
import json
import re
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from nomudocs import __version__, tool_version_label  # noqa: E402
from nomudocs.checks import check  # noqa: E402
from nomudocs.generate import Refused, generate, prepare  # noqa: E402

DRAFT = ROOT / "docs" / "bot-instructions-draft"


def sample(name):
    return json.loads((ROOT / "samples" / f"{name}.json").read_text(encoding="utf-8"))


def docx_all_text(path):
    from docx import Document
    d = Document(path)
    return "\n".join([p.text for p in d.paragraphs] + [c.text for t in d.tables for r in t.rows for c in r.cells]
                     + [p.text for s in d.sections for p in s.footer.paragraphs])


class N1Version13(unittest.TestCase):
    def test_version_file_and_label(self):
        self.assertEqual((ROOT / "VERSION").read_text(encoding="utf-8").strip(), "1.3")
        self.assertEqual(__version__, "1.3")
        self.assertEqual(tool_version_label(), "도구 판 v1.3")

    def test_every_sample_prints_v13_only(self):
        with tempfile.TemporaryDirectory() as td:
            for f in sorted((ROOT / "samples").glob("*.json")):
                out = generate(json.loads(f.read_text(encoding="utf-8")), Path(td) / f.stem, stem=f.stem, pdf=False, png=False)
                t = docx_all_text(out["docx"])
                self.assertIn("도구 판 v1.3", t, f.stem)
                self.assertNotIn("v1.2", t, f.stem)
                j = json.loads((Path(td) / f.stem / f"{f.stem}.점검결과.json").read_text(encoding="utf-8"))
                self.assertEqual(j["tool_version"], "1.3", f.stem)
                self.assertNotIn("v1.2", json.dumps(j, ensure_ascii=False), f.stem)

    def test_no_hardcoded_old_version_in_code(self):
        for f in list((ROOT / "nomudocs").rglob("*.py")) + [ROOT / "engine" / "calc.mjs", ROOT / "make_samples.py"]:
            for line in f.read_text(encoding="utf-8").splitlines():
                if re.search(r"""["'`]v?1\.2["'`]""", line):
                    self.fail(f"{f}: {line}")

    def test_drafts_say_v13(self):
        for f in DRAFT.rglob("*.md"):
            self.assertNotIn("v1.2", f.read_text(encoding="utf-8"), f)
        self.assertIn("v1.3", (DRAFT / "lbiz-labor-docs-rules" / "SKILL.md").read_text(encoding="utf-8"))
        self.assertIn("v1.3", (DRAFT / "profile-description.md").read_text(encoding="utf-8"))
        self.assertIn("v1.3", (ROOT / "README.md").read_text(encoding="utf-8"))


class N2ReversedCertDates(unittest.TestCase):
    def career(self, frm, to):
        d = sample("cert_career")
        d["periods"] = [{"from": frm, "to": to, "dept": "영업팀", "position": "사원"}]
        return d

    def refused(self, d):
        with tempfile.TemporaryDirectory() as td:
            with self.assertRaises(Refused) as cm:
                generate(d, Path(td) / "o", stem="c", pdf=False, png=False)
            made = list(Path(td).rglob("*")) if (Path(td) / "o").exists() else []
            self.assertFalse([x for x in made if x.is_file()], made)  # 파일 하나도 안 만듦
        return cm.exception.report

    def test_career_reversed_refused_plain_korean(self):
        rep = self.refused(self.career("2026-05-01", "2026-04-30"))  # 재검수 E7
        f = [x for x in rep.findings if x.code == "C_DATE_REVERSED"]
        self.assertEqual(len(f), 1)
        self.assertEqual(f[0].level, "error")
        self.assertIn("2026. 04. 30.", f[0].msg)
        self.assertIn("2026. 05. 01.", f[0].msg)
        self.assertIn("보다 앞이에요", f[0].msg)
        self.assertIn("만들지 않아요", f[0].msg)
        self.assertNotIn("C_UNDER_30", rep.codes())  # 거꾸로인 기간으로 30일 미만 안내를 내지 않음

    def test_career_one_of_two_periods_reversed(self):
        d = sample("cert_career")
        d["periods"][0]["to"] = "2019-02-28"  # 2020-03-02 시작인데 끝이 앞
        rep = self.refused(d)
        self.assertTrue(any("1번째 근무기간" in x.msg for x in rep.findings if x.code == "C_DATE_REVERSED"))

    def test_employment_issue_before_join_refused(self):
        d = sample("cert_employment")
        d["issueDate"] = "2022-03-01"  # 입사 2022-03-02
        rep = self.refused(d)
        self.assertTrue(any("발급일" in x.msg and "입사일" in x.msg for x in rep.findings if x.code == "C_DATE_REVERSED"))

    def test_same_day_and_normal_still_made(self):
        with tempfile.TemporaryDirectory() as td:
            out = generate(self.career("2026-05-01", "2026-05-01"), Path(td) / "a", stem="a", pdf=False, png=False)
            self.assertIn("(총 1일)", docx_all_text(out["docx"]))
            d = sample("cert_employment")
            d["issueDate"] = d["employee"]["joinDate"]
            out = generate(d, Path(td) / "b", stem="b", pdf=False, png=False)
            self.assertTrue(Path(out["docx"]).exists())
        self.assertNotIn("C_DATE_REVERSED", check(prepare(sample("cert_career"))[0]).codes())

    def test_cli_make_refuses_with_message(self):
        with tempfile.TemporaryDirectory() as td:
            inp = Path(td) / "in.json"
            inp.write_text(json.dumps(self.career("2026-05-01", "2026-04-30"), ensure_ascii=False), encoding="utf-8")
            r = subprocess.run([sys.executable, "-m", "nomudocs", "make", str(inp), str(Path(td) / "out"), "--no-pdf"],
                               cwd=ROOT, capture_output=True, text=True)
            self.assertEqual(r.returncode, 4, r.stdout + r.stderr)
            self.assertIn("[고쳐야 함]", r.stdout)
            self.assertIn("서류를 만들지 않았습니다", r.stdout)
            self.assertFalse(list((Path(td) / "out").rglob("*.docx")) if (Path(td) / "out").exists() else [])


class LicenseNotice(unittest.TestCase):
    def test_mit_license_and_notice(self):
        lic = (ROOT / "LICENSE").read_text(encoding="utf-8")
        self.assertTrue(lic.startswith("MIT License"))
        self.assertIn("Copyright (c) 2026 엘비즈파트너스(LBIZ Partners)", lic)
        self.assertIn("THE SOFTWARE IS PROVIDED \"AS IS\"", lic)
        notice = (ROOT / "NOTICE.md").read_text(encoding="utf-8")
        self.assertIn("MIT", notice)
        self.assertIn("저작권자는 엘비즈파트너스", notice)
        self.assertIn("다른 곳의 코드를 가져온 것이 아닙니다", notice)
        self.assertNotIn("라이선스는 아직 정하지 않았습니다", notice)
        self.assertIn("[확인 필요: 같은 스킬의 다른 사본에는", notice)  # 엔진 판 번호는 아직 확인 필요
        self.assertIn("MIT", (ROOT / "README.md").read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
