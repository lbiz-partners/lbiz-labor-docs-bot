"""재직증명서·경력증명서 — 원본 nomu-people templates/certificates.md 기준.
근로자가 요청한 항목만 적는다(근로기준법 §39②). 주민번호 전체는 넣지 않는다."""
from ..docx_builder import Doc, v, ymd
from ..timeutil import parse_date


def _dot(s):
    if not s:
        return "　　.　　.　　."
    y, m, d = str(s)[:10].split("-")
    return f"{y}. {m}. {d}."


def _tenure(a, b):
    a, b = parse_date(a), parse_date(b)
    if not a or not b:
        return ""
    months = (b.year - a.year) * 12 + (b.month - a.month) + (1 if b.day >= a.day - 1 else 0)
    y, m = divmod(max(months, 0), 12)
    return f"(총 {y}년 {m}개월)" if y else f"(총 {m}개월)"


def _company(d, er):
    d.table([["회사명(상호)", v(er.get("name"))], ["대표자", v(er.get("ceo"))], ["사업자등록번호", v(er.get("bizNo"))],
             ["소재지", v(er.get("address"))], ["연락처", v(er.get("phone"))]], widths=[40, 134], shade_first_col=True)
    d.p("")
    d.p(f"대표  {v(er.get('ceo'))}  (직인)", align="right", bold=True, size=11, space_after=2)


def render(data, rep, kind, footer):
    er, emp = data.get("employer") or {}, data.get("employee") or {}
    req = set(data.get("requestedItems") or [])
    title = "재 직 증 명 서" if kind == "employment" else "경 력 증 명 서"
    d = Doc(title, footer=footer, base_size=10.5)
    d.p(f"문서번호: {v(data.get('docNo'), empty='제 　　　 호')}", align="right", gray=True)
    d.h("■ 인적사항")
    rows = [["성명", v(emp.get("name"))], ["생년월일", _dot(emp.get("birth"))]]
    if kind == "employment" or "dept" in req:
        if emp.get("dept"):
            rows.append(["부서", v(emp.get("dept"))])
    if kind == "employment" and emp.get("position"):
        rows.append(["직위(직책)", v(emp.get("position"))])
    d.table(rows, widths=[40, 134], shade_first_col=True)
    if kind == "employment":
        d.h("■ 재직사항")
        rows = [["입사일", _dot(emp.get("joinDate"))],
                ["재직기간", f"{_dot(emp.get('joinDate'))} ~ 현재 재직 중 {_tenure(emp.get('joinDate'), data.get('issueDate'))}"]]
        if "duties" in req:
            rows.append(["담당업무", v(emp.get("duties"))])
        if "salary" in req:
            rows.append(["임금", v(data.get("salary"))])
        d.table(rows, widths=[40, 134], shade_first_col=True)
        d.p("위 사람은 현재 본사에 재직 중임을 증명합니다.", align="center", size=12, space_after=8)
    else:
        d.h("■ 경력사항")
        rows = [["근무기간", "부서", "직위(직책)"]]
        for p in data.get("periods") or []:
            rows.append([f"{_dot(p.get('from'))} ~ {_dot(p.get('to'))}", v(p.get("dept")), v(p.get("position"))])
        d.table(rows, widths=[80, 47, 47], header=True)
        ps = data.get("periods") or []
        a = min((p.get("from") for p in ps if p.get("from")), default=None)
        b = max((p.get("to") for p in ps if p.get("to")), default=None)
        rows = [["총 재직기간", f"{_dot(a)} ~ {_dot(b)} {_tenure(a, b)}"]]
        if "duties" in req:
            rows.append(["담당업무", v(emp.get("duties"))])
        if "leaveReason" in req:
            rows.append(["퇴직사유", v(emp.get("leaveReason"))])
        if "salary" in req:
            rows.append(["임금", v(data.get("salary"))])
        d.table(rows, widths=[40, 134], shade_first_col=True)
        d.p("위 사람은 위 기간 동안 본사에 근무하였음을 증명합니다.", align="center", size=12, space_after=8)
    d.h("■ 발급사항")
    d.table([["발급용도", v(data.get("purpose"))], ["발급일자", _dot(data.get("issueDate"))]], widths=[40, 134], shade_first_col=True)
    _company(d, er)
    return d
