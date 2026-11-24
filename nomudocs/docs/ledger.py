"""임금대장 — 근로기준법 제48조제1항, 시행령 제27조.

조문 확인: 2026-11-24, 법제처 국가법령정보센터.
- 근로기준법 제48조 (법률 제21533호, 시행 2026-10-08)
  https://www.law.go.kr/LSW/lsLinkProc.do?joNo=004800&lsNm=%EA%B7%BC%EB%A1%9C%EA%B8%B0%EC%A4%80%EB%B2%95&mode=11
- 근로기준법 시행령 제27조 (대통령령 제35436호, 시행 2025-10-23)
  https://www.law.go.kr/lsLinkProc.do?joNo=002700&lsClsCd=L&lsNm=%EA%B7%BC%EB%A1%9C%EA%B8%B0%EC%A4%80%EB%B2%95+%EC%8B%9C%ED%96%89%EB%A0%B9&mode=11

계산 숫자(4대보험·소득세·insuranceMonth·연도별 요율)는 임금명세서와 같은
payslip.build_engine_input → calc.payroll 만 쓴다. 요율표는 여기 두지 않는다.
주민등록번호·계좌번호 칸은 만들지 않는다.
"""
import calendar
import copy
import re
import zipfile
from itertools import groupby
from pathlib import Path
from xml.etree import ElementTree as ET

from ..docx_builder import Doc, v, ymd
from ..timeutil import parse_date
from ..xlsx_roster import excel_serial_to_date, read_workbook
from . import payslip

B = "근로기준법 §48①, 시행령 §27"
OT_KEYS = (
    ("overtime", "연장"),
    ("night", "야간"),
    ("holidayWithin8", "휴일 8시간 이내"),
    ("holidayOver8", "휴일 8시간 초과"),
)
HEADER_MAP = {
    "성명": "name", "생년월일": "birth", "사원번호": "employeeNo", "고용연월일": "hiredOn",
    "종사업무": "job", "하는일": "job", "임금년월": "yearMonth", "임금지급일": "payDate",
    "임금계산시작": "periodFrom", "임금계산끝": "periodTo", "보험월": "insuranceMonth",
    "근로일수": "workDays", "근로시간수": "totalHours", "임금형태": "payType",
    "기본급": "baseSalary", "시급": "hourlyWage", "주근로시간": "weeklyHours",
    "이번달근로시간": "workedHours", "주휴시간": "weeklyHolidayHours", "통상임금월액": "ordinaryMonthly",
    "연장근로시간": "overtime", "야간근로시간": "night",
    "휴일근로8시간이내": "holidayWithin8", "휴일근로시간8시간이내": "holidayWithin8",
    "휴일근로8시간초과": "holidayOver8", "휴일근로시간8시간초과": "holidayOver8",
    "가족수": "family", "자녀수8세이상20세이하": "children8to20",
    "수당1이름": "a1name", "수당1금액": "a1amt", "수당1비과세": "a1tax",
    "수당2이름": "a2name", "수당2금액": "a2amt", "수당2비과세": "a2tax",
    "공제1이름": "d1name", "공제1금액": "d1amt", "공제1근거": "d1basis",
    "현물품명": "inkindItem", "현물수량": "inkindQty", "현물평가총액": "inkindValue",
    "일용": "daily", "사용일수": "usageDays", "근로시간적용제외": "hoursExempt",
    "계산기초": "calcBasis", "가족수당기초": "familyBasis",
}
DATE_FIELDS = {"birth", "hiredOn", "payDate", "periodFrom", "periodTo"}
MONTH_FIELDS = {"yearMonth", "insuranceMonth"}
NUM_FIELDS = {
    "workDays", "totalHours", "baseSalary", "hourlyWage", "weeklyHours", "workedHours",
    "weeklyHolidayHours", "ordinaryMonthly", "overtime", "night", "holidayWithin8", "holidayOver8",
    "family", "children8to20", "a1amt", "a2amt", "d1amt", "inkindQty", "inkindValue", "usageDays",
}


def _blank(value):
    return value is None or value == "" or value == []


def _norm_header(text):
    return re.sub(r"[\s·.\-_/()（）]", "", str(text or ""))


def _truthy(value):
    if isinstance(value, bool):
        return value
    if value is None or value == "":
        return False
    if isinstance(value, (int, float)):
        return value != 0
    return str(value).strip().lower() in {"예", "y", "yes", "true", "1", "일용", "해당"}


def _explicit_no(value):
    return str(value or "").strip().lower() in {"아니오", "아니요", "n", "no", "false", "0", "미해당"}


def normalize_group(value):
    text = str(value or "").strip()
    if text in {"근로자", "근로자별", "사람", "사람별"} or text.lower() in {"worker", "person", "employee"}:
        return "worker"
    return "month"


def size5plus(ledger):
    return bool((ledger.get("workplace") or {}).get("size5plus"))


def _is_daily(entry):
    emp = entry.get("employment") or {}
    kind = str(emp.get("type") or entry.get("employmentType") or "").strip().lower()
    return kind in {"daily", "일용"} or _truthy(entry.get("daily"))


def usage_days(entry):
    """사용기간(날). 고용 연월일과 임금계산 끝날이 있으면 그 간격(양쪽 포함)."""
    hired = (entry.get("employee") or {}).get("hiredOn") or (entry.get("employment") or {}).get("hiredOn")
    end = entry.get("periodTo") or entry.get("periodFrom")
    if hired and end:
        start, stop = parse_date(hired), parse_date(end)
        if start and stop and stop >= start:
            return (stop - start).days + 1
    days = (entry.get("employment") or {}).get("usageDays", entry.get("usageDays"))
    if _blank(days):
        return None
    try:
        return int(float(days))
    except (TypeError, ValueError):
        return None


def daily_under_30(entry):
    """시행령 제27조제2항. 일용이고 사용기간이 30일 미만일 때만."""
    if not _is_daily(entry):
        return False
    days = usage_days(entry)
    return days is not None and days < 30


def hours_may_omit(ledger, entry):
    """시행령 제27조제3항. 상시 4명 이하, 또는 사장님이 제63조 해당이라고 표시한 근로자."""
    if not size5plus(ledger):
        return True
    return bool(entry.get("hoursExempt"))


def period_label(entry):
    if entry.get("periodLabel"):
        return str(entry["periodLabel"])
    src = str(entry.get("periodFrom") or entry.get("payDate") or "")
    if len(src) >= 7 and src[4] == "-":
        year, month = src[:7].split("-")
        try:
            return f"{int(year)}년 {int(month)}월"
        except ValueError:
            return src[:7]
    return ""


def who(entry, index):
    name = ((entry.get("employee") or {}).get("name")) or f"{index}번째 줄"
    label = period_label(entry)
    return f"{name}({label})" if label else name


def _fmt_num(value):
    try:
        num = float(value)
    except (TypeError, ValueError):
        return str(value)
    return f"{int(num):,}" if num.is_integer() else f"{num:,}"


def family_items(entry):
    return [x for x in (entry.get("extraEarnings") or []) if "가족수당" in str(x.get("name") or "")]


def calc_basis_text(entry):
    if not _blank(entry.get("calcBasis")):
        return str(entry["calcBasis"]).strip()
    pay = entry.get("pay") or {}
    parts = []
    if pay.get("type") == "monthly" and not _blank(pay.get("baseSalary")):
        parts.append(f"월급 기본급 {_fmt_num(pay['baseSalary'])}원")
    elif pay.get("type") == "hourly" and not _blank(pay.get("hourlyWage")):
        line = f"시급 {_fmt_num(pay['hourlyWage'])}원"
        if not _blank(pay.get("weeklyHours")):
            line += f", 주 {pay['weeklyHours']}시간"
        parts.append(line)
    count = entry.get("familyCount")
    allowance = entry.get("familyAllowance") or {}
    if _blank(count):
        count = allowance.get("count")
    if family_items(entry) or not _blank(count) or allowance.get("basis"):
        if allowance.get("basis"):
            parts.append(f"가족수당 기초: {allowance['basis']}")
        elif not _blank(count):
            parts.append(f"가족수당 기초: 가족 {count}명")
    return ", ".join(parts)


def family_basis_ok(entry):
    if not family_items(entry):
        return True
    if not _blank(entry.get("familyCount")):
        return True
    allowance = entry.get("familyAllowance") or {}
    if not _blank(allowance.get("count")) or allowance.get("basis"):
        return True
    return "가족" in str(entry.get("calcBasis") or "")


def wage_present(entry):
    pay = entry.get("pay") or {}
    if not _blank(pay.get("baseSalary")) or not _blank(pay.get("hourlyWage")):
        return True
    if entry.get("extraEarnings") or entry.get("inKind"):
        return True
    return False


def id_text(entry):
    emp = entry.get("employee") or {}
    if daily_under_30(entry) and _blank(emp.get("birth")) and _blank(emp.get("employeeNo")):
        return "생략 가능(시행령 제27조제2항)"
    lines = []
    if not _blank(emp.get("birth")):
        lines.append(ymd(emp.get("birth")))
    if not _blank(emp.get("employeeNo")):
        lines.append(f"사원번호 {emp['employeeNo']}")
    return "\n".join(lines) if lines else v(None)


def hours_text(entry, omit):
    if omit and _blank(entry.get("totalHours")):
        return "생략 가능(시행령 제27조제3항)"
    return v(entry.get("totalHours"), "시간")


def ot_text(entry, omit):
    hours = entry.get("hours") or {}
    lines = []
    for key, label in OT_KEYS:
        if hours.get(key):
            num = hours[key]
            try:
                shown = f"{float(num):g}"
            except (TypeError, ValueError):
                shown = str(num)
            lines.append(f"{label} {shown}")
    if lines:
        return "\n".join(lines)
    if omit and not any(hours.get(key) for key, _ in OT_KEYS):
        return "생략 가능(시행령 제27조제3항)"
    return "없음"


def wage_text(entry, item):
    pay = entry.get("pay") or {}
    result = item["result"]
    inp = item["input"]
    earned = result["earnings"]
    lines = []
    split = inp.get("_split")
    if pay.get("type") == "hourly" and pay.get("mode") == "actual" and split:
        lines.append(f"기본급 {split['base']:,}")
        lines.append(f"주휴수당 {split['holiday']:,}")
    elif pay.get("type") == "hourly" and not _blank(pay.get("hourlyWage")):
        lines.append(f"기본급(주휴 포함) {earned['baseSalary']:,}")
    elif not _blank(pay.get("baseSalary")) or pay.get("type") == "monthly":
        if _blank(pay.get("baseSalary")) and not (pay.get("type") == "hourly"):
            lines.append("기본급 (비어 있음)")
        else:
            lines.append(f"기본급 {earned['baseSalary']:,}")
    hours = entry.get("hours") or {}
    if hours.get("overtime"):
        lines.append(f"연장근로수당 {earned['overtimePay']:,}")
    if hours.get("night"):
        lines.append(f"야간근로수당 {earned['nightPay']:,}")
    if hours.get("holidayWithin8"):
        lines.append(f"휴일근로수당(8시간 이내) {earned['holiday8Pay']:,}")
    if hours.get("holidayOver8"):
        lines.append(f"휴일근로수당(8시간 초과) {earned['holidayOver8Pay']:,}")
    for extra in entry.get("extraEarnings") or []:
        name = extra.get("name") or "수당"
        amount = extra.get("amount")
        flag = " (비과세)" if extra.get("taxFree") else ""
        lines.append(f"{name} {_fmt_num(amount or 0)}{flag}")
    for kind in entry.get("inKind") or []:
        lines.append(f"현물 {v(kind.get('item'), empty='(품명 없음)')} 수량 {v(kind.get('qty'))} 평가총액 {_fmt_num(kind.get('value') or 0)}")
    lines.append(f"임금 총액 {earned['grossPay']:,}")
    return "\n".join(lines)


def deduct_text(ledger, entry, item):
    result = item["result"]
    deducted = result["deductions"]
    basis = result.get("yearBasis") or {}
    merged = as_payslip(ledger, entry)
    fam = (merged.get("incomeTax") or {}).get("family")
    lines = [
        f"국민연금 {deducted['nationalPension']:,} ({payslip._rate_note(basis, 'nationalPension', '근로자 부담분 4.75%')})",
        f"건강보험 {deducted['healthInsurance']:,} ({payslip._rate_note(basis, 'health', '근로자 부담분 3.595%')})",
        f"장기요양 {deducted['longTermCare']:,} ({payslip._rate_note(basis, 'longTermCare', '건강보험료에 연동')})",
        f"고용보험 {deducted['employmentInsurance']:,} ({payslip._rate_note(basis, 'employment', '근로자 부담분 0.9%')})",
        f"소득세 {deducted['incomeTax']:,} ({payslip._tax_note(merged, basis, fam)})",
        f"지방소득세 {deducted['localIncomeTax']:,} (소득세의 10%)",
    ]
    for extra in entry.get("otherDeductions") or []:
        lines.append(f"{extra.get('name') or '(이름 없음)'} {_fmt_num(extra.get('amount') or 0)}")
    lines.append(f"공제 합계 {deducted['totalDeductions']:,}")
    if basis.get("label"):
        lines.append(basis["label"])
    return "\n".join(lines)


def as_payslip(ledger, entry):
    """임금대장 한 줄을 임금명세서 입력 모양으로. 계산 엔진 입력은 이 함수만 만든다."""
    emp = entry.get("employee") or {}
    tax = dict(ledger.get("incomeTax") or {})
    tax.update({k: val for k, val in (entry.get("incomeTax") or {}).items() if val is not None})
    insurance = dict(ledger.get("insurance") or {})
    insurance.update({k: val for k, val in (entry.get("insurance") or {}).items() if val is not None})
    data = {
        "doc": "payslip",
        "workplace": ledger.get("workplace") or {},
        "employer": ledger.get("employer") or {},
        "employee": {
            "name": emp.get("name"),
            "birth": emp.get("birth"),
            "employeeNo": emp.get("employeeNo"),
            "dept": emp.get("job") or emp.get("dept"),
        },
        "periodLabel": entry.get("periodLabel"),
        "payDate": entry.get("payDate"),
        "periodFrom": entry.get("periodFrom"),
        "periodTo": entry.get("periodTo"),
        "workDays": entry.get("workDays"),
        "totalHours": entry.get("totalHours"),
        "pay": entry.get("pay") or {},
        "hours": entry.get("hours") or {},
        "extraEarnings": entry.get("extraEarnings") or [],
        "inKind": entry.get("inKind") or [],
        "incomeTax": tax,
        "otherDeductions": entry.get("otherDeductions") or [],
        "insurance": insurance,
    }
    month = entry.get("insuranceMonth") or ledger.get("insuranceMonth")
    if month:
        data["insuranceMonth"] = month
    return data


def _repo_root():
    return Path(__file__).resolve().parents[2]


def resolve_roster_path(path):
    raw = Path(path)
    if raw.is_file():
        return raw
    root = _repo_root()
    for cand in (Path.cwd() / raw, root / raw, root / "samples" / raw.name):
        if cand.is_file():
            return cand
    return None


def _cell_value(field, value):
    if _blank(value):
        return None
    if field in DATE_FIELDS:
        converted = excel_serial_to_date(value)
        return converted if isinstance(converted, str) else value
    if field in MONTH_FIELDS:
        if isinstance(value, (int, float)) and not isinstance(value, bool):
            converted = excel_serial_to_date(value)
            if isinstance(converted, str) and len(converted) >= 7:
                return converted[:7]
        text = str(value).strip()
        match = re.match(r"^(\d{4})-(\d{1,2})", text)
        if match:
            return f"{int(match.group(1)):04d}-{int(match.group(2)):02d}"
        return text
    if field in NUM_FIELDS and isinstance(value, str):
        cleaned = value.replace(",", "").replace("원", "").strip()
        try:
            num = float(cleaned)
            return int(num) if num.is_integer() else num
        except ValueError:
            return value
    return value


def _tax_kind(value):
    text = str(value or "").strip().lower()
    if text in {"식대", "meal"}:
        return {"taxFree": True, "kind": "meal"}
    if text in {"자가운전", "자가운전보조금", "car"}:
        return {"taxFree": True, "kind": "car"}
    if text in {"보육", "출산", "출산보육", "childcare"}:
        return {"taxFree": True, "kind": "childcare"}
    if text in {"예", "y", "yes", "true", "비과세", "1"}:
        return {"taxFree": True}
    if text in {"상여", "bonus"}:
        return {"bonus": True}
    return {}


def _apply_year_month(entry, raw):
    ym = raw.get("yearMonth")
    if _blank(ym):
        return
    match = re.match(r"^(\d{4})-(\d{2})$", str(ym))
    if not match:
        return
    year, month = int(match.group(1)), int(match.group(2))
    if _blank(entry.get("periodFrom")):
        entry["periodFrom"] = f"{year:04d}-{month:02d}-01"
    if _blank(entry.get("periodTo")):
        last = calendar.monthrange(year, month)[1]
        entry["periodTo"] = f"{year:04d}-{month:02d}-{last:02d}"
    if _blank(entry.get("periodLabel")):
        entry["periodLabel"] = f"{year}년 {month}월"


def row_to_entry(raw):
    emp = {
        "name": raw.get("name") or "",
        "birth": raw.get("birth") or "",
        "employeeNo": raw.get("employeeNo") or "",
        "hiredOn": raw.get("hiredOn") or "",
        "job": raw.get("job") or "",
    }
    pay = {}
    kind = str(raw.get("payType") or "").strip()
    if kind in {"월급", "monthly", "월"}:
        pay["type"] = "monthly"
    elif kind in {"시급실근로", "시급(실근로)", "actual"}:
        pay["type"] = "hourly"
        pay["mode"] = "actual"
    elif kind in {"시급", "hourly"}:
        pay["type"] = "hourly"
    elif not _blank(raw.get("hourlyWage")) and _blank(raw.get("baseSalary")):
        pay["type"] = "hourly"
    elif not _blank(raw.get("baseSalary")):
        pay["type"] = "monthly"
    for src, dst in (("baseSalary", "baseSalary"), ("hourlyWage", "hourlyWage"), ("weeklyHours", "weeklyHours"),
                     ("workedHours", "workedHours"), ("weeklyHolidayHours", "weeklyHolidayHours"),
                     ("ordinaryMonthly", "ordinaryMonthly")):
        if not _blank(raw.get(src)):
            pay[dst] = raw[src]
    hours = {}
    for key, _label in OT_KEYS:
        if key in raw and not _blank(raw.get(key)):
            hours[key] = raw[key]
    extras = []
    for idx in (1, 2):
        name, amount, tax = raw.get(f"a{idx}name"), raw.get(f"a{idx}amt"), raw.get(f"a{idx}tax")
        if _blank(name) and _blank(amount):
            continue
        item = {"name": name or "", "amount": amount}
        item.update(_tax_kind(tax))
        extras.append(item)
    deductions = []
    if not (_blank(raw.get("d1name")) and _blank(raw.get("d1amt"))):
        deductions.append({"name": raw.get("d1name") or "", "amount": raw.get("d1amt"), "basis": raw.get("d1basis") or ""})
    in_kind = []
    if not all(_blank(raw.get(k)) for k in ("inkindItem", "inkindQty", "inkindValue")):
        in_kind.append({"item": raw.get("inkindItem") or "", "qty": raw.get("inkindQty"), "value": raw.get("inkindValue")})
    tax = {}
    if not _blank(raw.get("family")):
        tax["family"] = raw["family"]
    if not _blank(raw.get("children8to20")):
        tax["children8to20"] = raw["children8to20"]
    entry = {
        "employee": emp,
        "pay": pay,
        "hours": hours,
        "extraEarnings": extras,
        "otherDeductions": deductions,
        "inKind": in_kind,
        "workDays": raw.get("workDays"),
        "totalHours": raw.get("totalHours"),
        "payDate": raw.get("payDate") or "",
        "periodFrom": raw.get("periodFrom") or "",
        "periodTo": raw.get("periodTo") or "",
    }
    if tax:
        entry["incomeTax"] = tax
    if not _blank(raw.get("insuranceMonth")):
        entry["insuranceMonth"] = raw["insuranceMonth"]
    if not _blank(raw.get("calcBasis")):
        entry["calcBasis"] = raw["calcBasis"]
    if not _blank(raw.get("familyBasis")):
        entry["familyAllowance"] = {"basis": raw["familyBasis"]}
    if _truthy(raw.get("daily")):
        entry["employment"] = {"type": "daily"}
        if not _blank(raw.get("usageDays")):
            entry["employment"]["usageDays"] = raw["usageDays"]
            entry["usageDays"] = raw["usageDays"]
    if _truthy(raw.get("hoursExempt")):
        entry["hoursExempt"] = True
    _apply_year_month(entry, raw)
    if _blank(entry.get("periodLabel")):
        label = period_label(entry)
        if label:
            entry["periodLabel"] = label
    return entry


def rows_to_entries(rows):
    """(entries, forbidden_headers). 금지 열의 칸 값은 버린다."""
    if not rows:
        return [], []
    headers = []
    forbidden = []
    from ..checks import _key_forbidden
    for cell in rows[0]:
        label = _norm_header(cell)
        if not label:
            headers.append(None)
            continue
        if _key_forbidden(label) or label in {"주민등록번호", "주민번호", "계좌번호", "외국인등록번호"}:
            forbidden.append(str(cell).strip() or label)
            headers.append(None)
            continue
        headers.append(HEADER_MAP.get(label))
    entries = []
    for row in rows[1:]:
        if not row or not any(not _blank(x) for x in row):
            continue
        raw = {}
        for idx, field in enumerate(headers):
            if not field:
                continue
            raw[field] = _cell_value(field, row[idx] if idx < len(row) else None)
        entries.append(row_to_entry(raw))
    return entries, forbidden


def _meta_map(rows):
    if not rows:
        return {}
    start = 0
    if rows[0] and _norm_header(rows[0][0]) in {"항목", "구분"}:
        start = 1
    meta = {}
    for row in rows[start:]:
        if not row or _blank(row[0]):
            continue
        meta[_norm_header(row[0])] = row[1] if len(row) > 1 else None
    return meta


def _apply_meta(data, meta):
    if not meta:
        return
    employer = data.setdefault("employer", {})
    for src, dst in (("사업장이름", "name"), ("사업장", "name"), ("대표자", "ceo"), ("대표", "ceo"),
                     ("사업자등록번호", "bizNo"), ("주소", "address"), ("전화번호", "phone")):
        if not _blank(meta.get(src)) and _blank(employer.get(dst)):
            employer[dst] = meta[src]
    workplace = data.setdefault("workplace", {})
    if "size5plus" not in workplace and not _blank(meta.get("상시5인이상")):
        answer = meta.get("상시5인이상")
        if _explicit_no(answer):
            workplace["size5plus"] = False
        elif _truthy(answer):
            workplace["size5plus"] = True
    if _blank(data.get("groupBy")) and not _blank(meta.get("묶음")):
        data["groupBy"] = meta["묶음"]


def _pick_sheets(sheets):
    names = list(sheets)
    roster = next((n for n in names if _norm_header(n) in {"명단", "임금대장", "roster"}), names[0] if names else None)
    meta = next((n for n in names if _norm_header(n) in {"사업장", "회사"}), None)
    return roster, meta


def _fill_entry(entry):
    entry = copy.deepcopy(entry)
    if _blank(entry.get("periodLabel")):
        label = period_label(entry)
        if label:
            entry["periodLabel"] = label
    return entry


def expand(data):
    """엑셀 명단을 펼치고 기간 이름을 채운 입력. 원본 dict 는 바꾸지 않는다."""
    data = copy.deepcopy(data or {})
    forbidden = list(data.get("_sensitiveColumns") or [])
    entries = []
    roster = data.get("roster")
    if roster:
        path = resolve_roster_path(roster)
        if path is None:
            data["_rosterError"] = str(roster)
        else:
            try:
                sheets = read_workbook(path)
            except (OSError, zipfile.BadZipFile, ET.ParseError, KeyError, ValueError):
                data["_rosterError"] = str(roster)
            else:
                roster_name, meta_name = _pick_sheets(sheets)
                got, bad = rows_to_entries(sheets.get(roster_name) or [])
                entries.extend(got)
                forbidden.extend(bad)
                if meta_name:
                    _apply_meta(data, _meta_map(sheets.get(meta_name) or []))
    for entry in data.get("entries") or []:
        if isinstance(entry, dict):
            entries.append(_fill_entry(entry))
    data["entries"] = entries
    data["_sensitiveColumns"] = forbidden
    data["groupBy"] = normalize_group(data.get("groupBy"))
    return data


def document_from_xlsx(path):
    return {"doc": "wage_ledger", "roster": str(path)}


def check_entries(data, rep, result=None):
    from ..checks import (_hourly_exact, mw_basis, ordinary_wage_notice, ORDINARY_BASIS)

    if data.get("_rosterError"):
        rep.add("error", "L_ROSTER",
                f"엑셀 명단 파일을 찾지 못했습니다. 경로를 확인해 주세요. ({data['_rosterError']})",
                "엑셀 명단")
    for col in data.get("_sensitiveColumns") or []:
        if "계좌" in str(col) or "account" in str(col).lower():
            rep.add("error", "SENSITIVE_ACCOUNT",
                    f"엑셀 명단에 '{col}' 열이 있습니다. 계좌번호는 받지 않아 그 열은 빼 두었습니다.",
                    "개인정보 보호법 §3(최소 수집)")
        else:
            rep.add("error", "SENSITIVE_RRN",
                    f"엑셀 명단에 '{col}' 열이 있습니다. 주민등록번호 대신 생년월일만 적어 주세요. 그 열은 빼 두었습니다.",
                    "개인정보 보호법 §24의2(주민등록번호 처리 제한)")
    entries = data.get("entries") or []
    bundle = (result or {}).get("entries") or []
    if not entries:
        rep.add("missing", "L_EMPTY", "임금대장에 적을 근로자 줄이 없습니다.", B)
    if (data.get("workplace") or {}).get("size5plus") is None and entries:
        rep.add("info", "L_SIZE_UNKNOWN",
                "상시 근로자가 5명 이상인지 비어 있어 4명 이하로 보았습니다. 5명 이상이면 알려 주세요.",
                "근로기준법 §11②, 시행령 §27③")
    if entries and not size5plus(data):
        rep.add("info", "L_FOUR_OR_FEWER",
                "상시 4명 이하 사업장입니다. 근로시간수와 연장·야간·휴일근로 시간수는 적지 않아도 됩니다.",
                "근로기준법 시행령 §27③제1호")
    gross = deductions = net = 0
    rows = []
    for index, entry in enumerate(entries, start=1):
        label = who(entry, index)
        emp = entry.get("employee") or {}
        rep.need(emp.get("name"), "L_NAME", f"{label} 성명", B + " 제1항제1호")
        if not daily_under_30(entry):
            if _blank(emp.get("birth")) and _blank(emp.get("employeeNo")):
                rep.add("missing", "L_ID", f"{label} — 생년월일이나 사원번호 칸이 비어 있습니다. 누구인지 알 수 있게 둘 중 하나는 적어 주세요.", B + " 제1항제2호")
        elif _is_daily(entry):
            rep.add("info", "L_DAILY30",
                    f"{label} — 사용기간이 30일 미만인 일용근로자라 생년월일·사원번호와 임금 계산기초는 적지 않아도 됩니다.",
                    "시행령 §27②")
        if _is_daily(entry) and not daily_under_30(entry) and usage_days(entry) is None:
            rep.add("info", "L_DAILY_UNKNOWN",
                    f"{label} — 일용으로 표시됐지만 사용기간을 알 수 없어, 30일 미만 생략은 적용하지 않았습니다.",
                    "시행령 §27②")
        rep.need(emp.get("hiredOn"), "L_HIRED", f"{label} 고용 연월일", B + " 제1항제3호")
        rep.need(emp.get("job"), "L_JOB", f"{label} 종사하는 업무", B + " 제1항제4호")
        if not daily_under_30(entry):
            if _blank(calc_basis_text(entry)):
                rep.add("missing", "L_BASIS", f"{label} — 임금과 가족수당을 계산하는 기초 칸이 비어 있습니다.", B + " 제1항제5호")
            elif not family_basis_ok(entry):
                rep.add("missing", "L_FAMILY_BASIS", f"{label} — 가족수당이 있는데 가족 수 등 계산기초가 비어 있습니다.", B + " 제1항제5호")
        if _blank(entry.get("workDays")):
            rep.add("missing", "L_DAYS", f"{label} — 근로일수 칸이 비어 있습니다.", B + " 제1항제6호")
        omit = hours_may_omit(data, entry)
        if not omit and _blank(entry.get("totalHours")):
            rep.add("missing", "L_HOURS", f"{label} — 근로시간수 칸이 비어 있습니다.", B + " 제1항제7호")
        hours = entry.get("hours") or {}
        if not omit:
            for key, hour_label in OT_KEYS:
                if isinstance(entry.get("hours"), dict) and key in entry["hours"] and _blank(entry["hours"][key]):
                    rep.add("missing", "L_OT", f"{label} — {hour_label}근로 시간 칸이 비어 있습니다. 시킨 시간만 적으면 됩니다.", B + " 제1항제8호")
        if entry.get("hoursExempt") and size5plus(data):
            rep.add("info", "L_ART63",
                    f"{label} — 근로기준법 제63조에 해당하는 근로자로 표시돼 근로시간수를 적지 않아도 됩니다. 해당하는지는 사장님이 확인해 주세요.",
                    "시행령 §27③제2호")
        if not wage_present(entry):
            rep.add("missing", "L_WAGE", f"{label} — 기본급·수당 등 임금 내역 금액이 비어 있습니다.", B + " 제1항제9호")
        for extra in entry.get("extraEarnings") or []:
            if _blank(extra.get("name")):
                rep.add("missing", "L_WAGE", f"{label} — 이름 없는 수당이 있습니다.", B + " 제1항제9호")
            if _blank(extra.get("amount")):
                rep.add("missing", "L_WAGE", f"{label} — '{extra.get('name') or '수당'}' 금액이 비어 있습니다.", B + " 제1항제9호")
        for kind in entry.get("inKind") or []:
            for key, piece in (("item", "품명"), ("qty", "수량"), ("value", "평가총액")):
                if _blank(kind.get(key)):
                    rep.add("missing", "L_INKIND", f"{label} — 현물로 준 임금의 {piece}이 비어 있습니다.", B + " 제1항제9호")
        for extra in entry.get("otherDeductions") or []:
            if _blank(extra.get("name")):
                rep.add("missing", "L_DEDUCT_NAME", f"{label} — 공제 항목 이름이 비어 있습니다.", B + " 제1항제10호")
            if _blank(extra.get("amount")):
                rep.add("missing", "L_DEDUCT_AMT", f"{label} — 공제 금액이 비어 있습니다.", B + " 제1항제10호")
            if _blank(extra.get("basis")):
                rep.add("warn", "L_DEDUCT_BASIS",
                        f"{label} — '{extra.get('name') or '공제'}'의 근거(법령·단체협약 등)를 적어 주세요.",
                        "근로기준법 §43①")
        if _blank(entry.get("payDate")):
            rep.add("warn", "L_PAYDATE",
                    f"{label} — 임금지급일이 비어 있습니다. 소득세는 실제로 준 날짜로 계산합니다.",
                    "소득세법 §134①")
        item = bundle[index - 1] if index - 1 < len(bundle) else None
        if not item:
            continue
        calc = item["result"]
        pay = entry.get("pay") or {}
        fixed = [x for x in entry.get("extraEarnings") or []
                 if not x.get("variable") and not x.get("bonus") and (x.get("amount") or 0) > 0]
        if fixed and pay.get("type") in ("monthly", "hourly") and not pay.get("ordinaryMonthly"):
            has_hours = any((entry.get("hours") or {}).get(k) for k, _ in OT_KEYS)
            rep.add("warn", "ORDINARY_WAGE_CHECK",
                    f"{label} — " + ordinary_wage_notice([x.get("name") for x in fixed], has_hours),
                    ORDINARY_BASIS)
        tax = entry.get("incomeTax") or data.get("incomeTax") or {}
        fam = tax.get("family")
        if tax.get("mode", "table") == "table" and (fam or 1) >= 2 and tax.get("children8to20") is None and tax.get("childrenUnder20") is None:
            rep.add("info", "P_CHILDREN",
                    f"{label} — 공제대상 가족 중 8세 이상 20세 이하 자녀가 몇 명인지 알려 주세요. 없으면 0명으로 계산합니다.",
                    "소득세법 시행령 [별표 2] 제3호")
        if fam is None and tax.get("mode", "table") == "table":
            rep.add("info", "P_FAMILY",
                    f"{label} — 공제대상 가족 수(본인 포함)를 모르면 본인 1명으로 계산합니다.",
                    "소득세법 시행령 [별표 2]")
        mw = calc.get("minimumWage") or {}
        if pay.get("type") == "hourly":
            mw = _hourly_exact(mw, {"type": "시급", "amount": pay.get("hourlyWage")})
        if mw.get("violated"):
            base_date = entry.get("periodTo") or entry.get("periodFrom") or entry.get("payDate")
            rep.add("error", "MIN_WAGE",
                    f"{label} — 이번 달 임금이 최저임금보다 적어 보입니다: 시간당 {mw['effectiveHourly']:,}원 < {mw['appliedMinHourly']:,}원.",
                    mw_basis(base_date))
        if calc.get("netPay", 0) < 0:
            rep.add("error", "L_NEGATIVE", f"{label} — 공제액이 지급액보다 많습니다.", "근로기준법 §43①")
        if not size5plus(data) and any((entry.get("hours") or {}).get(k) for k, _ in OT_KEYS):
            rep.add("info", "L_FIVE_UNDER",
                    f"{label} — 5인 미만이라 연장·야간·휴일에 가산을 붙이지 않고 일한 시간만큼만 계산했습니다.",
                    "근로기준법 §56, 시행령 [별표 1]")
        for warning in (calc.get("meta") or {}).get("warnings") or []:
            if str(warning).startswith("🔴"):
                continue
            rep.add("info", "ENGINE_NOTE", f"{label} — {warning}", "계산 엔진")
        gross += calc["earnings"]["grossPay"]
        deductions += calc["deductions"]["totalDeductions"]
        net += calc["netPay"]
        rows.append({
            "name": emp.get("name"),
            "month": period_label(entry),
            "gross": calc["earnings"]["grossPay"],
            "totalDeductions": calc["deductions"]["totalDeductions"],
            "netPay": calc["netPay"],
            "hoursOmitted": omit and _blank(entry.get("totalHours")),
        })
    if rows:
        rep.derived["gross"] = gross
        rep.derived["totalDeductions"] = deductions
        rep.derived["netPay"] = net
        rep.derived["rows"] = rows
        rep.derived["count"] = len(rows)


def _bucket_key(group, entry):
    if group == "worker":
        emp = entry.get("employee") or {}
        return (emp.get("name") or "", emp.get("birth") or "", emp.get("employeeNo") or "")
    return (period_label(entry), entry.get("periodFrom") or "")


def _bucket_title(group, entry):
    if group == "worker":
        emp = entry.get("employee") or {}
        title = emp.get("name") or "(성명 없음)"
        if not _blank(emp.get("birth")):
            title += f" · {ymd(emp.get('birth'))}"
        return title
    return f"{period_label(entry) or '기간 미상'}분"


def render(data, rep, result, footer):
    employer = data.get("employer") or {}
    group = normalize_group(data.get("groupBy"))
    pairs = []
    entries = data.get("entries") or []
    bundle = (result or {}).get("entries") or []
    for index, entry in enumerate(entries):
        item = bundle[index] if index < len(bundle) else None
        if item:
            pairs.append((entry, item))
    if group == "worker":
        pairs.sort(key=lambda pair: ((pair[0].get("employee") or {}).get("name") or "", pair[0].get("periodFrom") or ""))
    else:
        pairs.sort(key=lambda pair: (pair[0].get("periodFrom") or period_label(pair[0]), (pair[0].get("employee") or {}).get("name") or ""))
    span = ""
    labels = [period_label(e) for e, _ in pairs if period_label(e)]
    if labels:
        span = labels[0] if labels[0] == labels[-1] else f"{labels[0]} ~ {labels[-1]}"
    subtitle = " · ".join(x for x in (employer.get("name"), span, "근로자별" if group == "worker" else "월별") if x)
    doc = Doc("임 금 대 장", subtitle=subtitle or None, footer=footer, base_size=8, landscape=True)
    size_text = "상시 5명 이상" if size5plus(data) else "상시 4명 이하"
    doc.table([
        ["사업장", v(employer.get("name")), "대표", v(employer.get("ceo"))],
        ["주소", v(employer.get("address")), "인원 규모", size_text],
        ["묶음", "근로자별" if group == "worker" else "월별", "줄 수", f"{len(pairs)}줄"],
    ], widths=[28, 110, 28, 102], shade_first_col=True, size=8)
    head = ["성명", "생년월일·사원번호", "고용 연월일", "종사 업무", "계산기초", "근로일수", "근로시간수",
            "연장·야간·휴일근로", "임금 내역별 금액", "공제 항목·금액", "차인지급액"]
    widths = [18, 26, 20, 18, 30, 12, 14, 26, 44, 42, 18]
    grouped = groupby(pairs, key=lambda pair: _bucket_key(group, pair[0]))
    any_row = False
    for _key, chunk in grouped:
        chunk = list(chunk)
        any_row = True
        doc.h(_bucket_title(group, chunk[0][0]))
        rows = [head]
        gross = deducted = net = 0
        for entry, item in chunk:
            emp = entry.get("employee") or {}
            omit = hours_may_omit(data, entry)
            basis = calc_basis_text(entry)
            if daily_under_30(entry) and _blank(basis):
                basis = "생략 가능(시행령 제27조제2항)"
            rows.append([
                v(emp.get("name")),
                id_text(entry),
                ymd(emp.get("hiredOn")),
                v(emp.get("job")),
                basis or v(None),
                v(entry.get("workDays"), "일"),
                hours_text(entry, omit),
                ot_text(entry, omit),
                wage_text(entry, item),
                deduct_text(data, entry, item),
                f"{item['result']['netPay']:,}",
            ])
            gross += item["result"]["earnings"]["grossPay"]
            deducted += item["result"]["deductions"]["totalDeductions"]
            net += item["result"]["netPay"]
        doc.table(rows, widths=widths, header=True, size=7)
        doc.p(f"이 묶음 합계 — 임금 총액 {gross:,}원, 공제 {deducted:,}원, 차인지급 {net:,}원", size=8)
    if not any_row:
        doc.p("적을 근로자 줄이 없습니다. 빈칸은 비워 두었습니다.")
    if not size5plus(data):
        doc.p("상시 4명 이하 사업장: 시행령 제27조제3항제1호에 따라 근로시간수와 연장·야간·휴일근로 시간수는 적지 않을 수 있습니다.", size=8, gray=True)
    doc.p("근거: 근로기준법 제48조제1항(법률 제21533호, 시행 2026-10-08), 시행령 제27조(대통령령 제35436호, 시행 2025-10-23). 2026-11-24 법제처 국가법령정보센터 원문.", size=8, gray=True)
    doc.p("임금대장은 마지막으로 써 넣은 날부터 3년간 보존합니다(근로기준법 제42조, 시행령 제22조제1항제2호·제2항제3호).", size=8, gray=True)
    doc.p("4대보험료는 공단 고지액, 소득세는 국세청 간이세액표가 최종 기준입니다. 숫자는 임금명세서와 같은 계산을 썼습니다.", size=8, gray=True)
    return doc
