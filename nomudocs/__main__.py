"""사용법:
  python3 -m nomudocs check  입력.json            # 점검만 (빈칸·최저임금·독소조항)
  python3 -m nomudocs make   입력.json [출력폴더] [--no-pdf]
  python3 -m nomudocs check  명단.xlsx            # 임금대장 엑셀 명단
"""
import json
import sys
from pathlib import Path

from . import checks
from .generate import Blocked, Refused, generate


def load_input(path):
    file = Path(path)
    if file.suffix.lower() == ".xlsx":
        from .docs.ledger import document_from_xlsx
        return document_from_xlsx(file)
    return json.loads(file.read_text(encoding="utf-8"))

ICON = {"missing": "[빈칸]", "error": "[고쳐야 함]", "warn": "[다시 보기]", "info": "[참고]"}


def show(rep):
    if not rep["findings"]:
        print("[통과] 빈칸·오류 없음")
    for f in rep["findings"]:
        print(f"{ICON[f['level']]} {f['msg']}" + (f"  — {f['basis']}" if f.get("basis") else ""))


def main(argv):
    if len(argv) < 2 or argv[0] not in ("check", "make"):
        print(__doc__)
        return 2
    data = load_input(argv[1])
    if argv[0] == "check":
        from .generate import prepare
        data, res = prepare(data)
        rep = checks.check(data, res).as_dict()
        show(rep)
        d = rep.get("derived") or {}
        if "netPay" in d or "gross" in d:
            print("계산:", json.dumps({k: d[k] for k in ("gross", "totalDeductions", "netPay") if k in d}, ensure_ascii=False))
        return 1 if any(f["level"] in ("missing", "error") for f in rep["findings"]) else 0
    outdir = argv[2] if len(argv) > 2 and not argv[2].startswith("--") else "out"
    try:
        out = generate(data, outdir, pdf="--no-pdf" not in argv)
    except Blocked as b:
        show(b.report.as_dict())
        print("민감정보가 있어 서류를 만들지 않았습니다.")
        return 3
    except Refused as r:
        show(r.report.as_dict())
        print("날짜가 거꾸로 되어 있어 서류를 만들지 않았습니다. 날짜를 고친 뒤 다시 만들어 주세요.")
        return 4
    show(out["report"])
    print("만든 파일:", out["docx"], out.get("pdf", ""))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
