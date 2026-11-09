"""입력 JSON 하나 → 점검 보고서 + DOCX (+PDF/PNG)."""
import json
from pathlib import Path

from . import calc, checks
from .docs import certificates, contract, foreign, payslip
from .render import docx_to_pdf, pdf_to_png

FOOTER = "이 서류는 사업주가 직접 입력한 내용으로 만든 양식입니다(2026년 기준 · 2027년 최저임금 반영). 내용 확인과 교부 책임은 사업주에게 있습니다."
NAMES = {
    "contract_regular": "근로계약서_정규직", "contract_fixed": "근로계약서_기간제", "contract_parttime": "근로계약서_단시간",
    "contract_minor": "근로계약서_연소자", "contract_foreign": "표준근로계약서_외국인", "cert_employment": "재직증명서",
    "cert_career": "경력증명서", "payslip": "임금명세서",
}


class Blocked(Exception):
    """민감정보 등으로 서류를 만들지 않는 경우."""

    def __init__(self, report):
        super().__init__("서류를 만들지 않았습니다(민감정보).")
        self.report = report


def prepare(data):
    """임금명세서면 엔진으로 먼저 계산한다. (data, result) 를 돌려준다."""
    if data.get("doc") != "payslip":
        return data, None
    inp = payslip.build_engine_input(data)
    data = {**data, "_engine_input": inp}
    result = calc.payroll({k: x for k, x in inp.items() if not k.startswith("_")})
    # 최저임금은 임금계산기간(끝날 → 시작날 → 지급일)의 연도 값으로 판정한다.
    # 예: 2026년 12월분을 2027-01-10에 주면 2026년 값, 2027년 1월분이면 2027년 값.
    base_date = data.get("periodTo") or data.get("periodFrom") or data.get("payDate")
    mw_inp = inp["_mw"] if inp.get("_mw") else {k: x for k, x in inp.items() if not k.startswith("_")}
    result["minimumWage"] = calc.minwage({**mw_inp, "payDate": base_date})
    return data, result


def generate(data: dict, outdir, stem=None, pdf=True, png=True, footer=FOOTER, allow_sensitive=False):
    outdir = Path(outdir)
    outdir.mkdir(parents=True, exist_ok=True)
    data, result = prepare(data)
    rep = checks.check(data, result)
    if not allow_sensitive and any(f.code.startswith("SENSITIVE") for f in rep.findings):
        raise Blocked(rep)
    safe = checks.mask_sensitive(data)
    fam, kind = checks.DOC_KINDS[data["doc"]]
    if fam == "contract":
        doc = contract.render(safe, rep, kind, footer)
    elif fam == "foreign":
        doc = foreign.render(safe, rep, footer)
    elif fam == "cert":
        doc = certificates.render(safe, rep, kind, footer)
    else:
        doc = payslip.render(safe, rep, result, footer)
    stem = stem or NAMES[data["doc"]]
    dx = outdir / f"{stem}.docx"
    doc.save(dx)
    out = {"docx": str(dx), "report": rep.as_dict()}
    if result is not None:
        out["payroll"] = {"earnings": result["earnings"], "deductions": result["deductions"], "netPay": result["netPay"]}
    if pdf:
        p = docx_to_pdf(dx, outdir)
        out["pdf"] = str(p)
        if png:
            out["png"] = [str(x) for x in pdf_to_png(p)]
    (outdir / f"{stem}.점검결과.json").write_text(json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")
    return out
