"""점검기 — 빈칸(필수 기재사항)·최저임금·주휴/연장 계산·독소조항·민감정보.

판정이 아니라 '확인해 보시라'는 알림이다. level:
  missing : 법에 적어야 하는 칸이 비었음(빈칸으로 인쇄됨)
  error   : 법정 기준에 어긋나 보이는 값(그대로 쓰면 위험)
  warn    : 다시 보시라 / 전문가 확인이 필요할 수 있음
  info    : 참고
"""
import re
from dataclasses import dataclass, field, asdict

from . import calc
from .timeutil import (DAYS, age_on, break_minutes, day_work_hours, months_between,
                       monthly_paid_hours, night_minutes, parse_date, span_minutes,
                       weekly_holiday_hours)

MIN_WAGE_2026 = 10320  # 고용노동부고시 제2025-47호 (엔진 rates-2026.mjs 와 같은 값; 시험이 대조)
MIN_WAGE_2027 = 10700  # 고용노동부고시 제2026-60호(2026.8.5 고시, 2027.1.1~12.31 적용; engine/calc.mjs MINWAGE_EXTRA 와 같은 값; 시험이 대조)
# 연도별 최저임금(시급, 고시). 서류 기준일(계약 시작일·임금계산기간)의 연도 값으로 판정한다.
MIN_WAGE = {
    2026: (MIN_WAGE_2026, "고용노동부고시 제2025-47호"),
    2027: (MIN_WAGE_2027, "고용노동부고시 제2026-60호"),
}


def mw_year(date_str):
    """기준일의 연도 → 등록된 최저임금 연도(없으면 가장 가까운 앞 연도, 그보다 앞이면 첫 연도)."""
    d = parse_date(date_str) if date_str else None
    y = d.year if d else 2026
    if y in MIN_WAGE:
        return y
    prev = [k for k in MIN_WAGE if k < y]
    return max(prev) if prev else min(MIN_WAGE)


def mw_hour(date_str):
    return MIN_WAGE[mw_year(date_str)][0]


def mw_basis(date_str):
    y = mw_year(date_str)
    hour, notice = MIN_WAGE[y]
    return f"최저임금법 §6 · {notice}({y}년 시급 {hour:,}원)"


def _later_years(start_str, end_str):
    """기준일 뒤에 시작하는 등록 연도 중, 계약이 그 해 1월 1일까지 이어지는 연도들."""
    s = parse_date(start_str) if start_str else None
    if not s:
        return []
    e = parse_date(end_str) if end_str else None
    out = []
    for y in sorted(MIN_WAGE):
        if y > s.year and (e is None or e.year >= y):
            out.append(y)
    return out


@dataclass
class Finding:
    level: str
    code: str
    msg: str
    basis: str = ""

    def as_dict(self):
        return asdict(self)


@dataclass
class Report:
    findings: list = field(default_factory=list)
    derived: dict = field(default_factory=dict)

    def add(self, level, code, msg, basis=""):
        self.findings.append(Finding(level, code, msg, basis))

    def need(self, value, code, label, basis):
        if value is None or value == "" or value == [] or value == {}:
            self.add("missing", code, f"'{label}' 칸이 비어 있습니다.", basis)
            return False
        return True

    def has(self, level):
        return any(f.level == level for f in self.findings)

    def codes(self, level=None):
        return [f.code for f in self.findings if level is None or f.level == level]

    def as_dict(self):
        return {"findings": [f.as_dict() for f in self.findings], "derived": self.derived}


# ───────────────────────── 민감정보 ─────────────────────────
RRN = re.compile(r"(?<!\d)\d{6}\s*-?\s*[1-8]\d{6}(?!\d)")
SECRET_WORDS = re.compile(r"비밀번호|password|PIN번호|보안카드|OTP", re.I)


def _walk(obj, path=""):
    if isinstance(obj, dict):
        for k, val in obj.items():
            yield from _walk(val, f"{path}.{k}" if path else k)
    elif isinstance(obj, list):
        for i, val in enumerate(obj):
            yield from _walk(val, f"{path}[{i}]")
    elif isinstance(obj, str):
        yield path, obj


def scan_sensitive(data, rep: Report):
    for path, s in _walk(data):
        if RRN.search(s):
            rep.add("error", "SENSITIVE_RRN",
                    f"'{path}'에 주민등록번호(외국인등록번호) 전체로 보이는 값이 있습니다. 서류에는 생년월일만 쓰고, 번호 전체는 넣지 마세요.",
                    "개인정보 보호법 §24의2(주민등록번호 처리 제한)")
        if SECRET_WORDS.search(s):
            rep.add("error", "SENSITIVE_SECRET",
                    f"'{path}'에 비밀번호·보안정보로 보이는 말이 있습니다. 이런 정보는 받지도 적지도 않습니다.",
                    "개인정보 보호법 §3(최소 수집)")


def mask_sensitive(data):
    """민감정보를 가려서 돌려준다(렌더링 전 안전장치)."""
    if isinstance(data, dict):
        return {k: mask_sensitive(x) for k, x in data.items()}
    if isinstance(data, list):
        return [mask_sensitive(x) for x in data]
    if isinstance(data, str):
        return RRN.sub(lambda m: m.group(0)[:6] + "-*******", data)
    return data


# ───────────────────────── 독소조항 ─────────────────────────
TOXIC = [
    # (code, level, regex, 설명, 근거)
    ("TOXIC_PENALTY", "error", r"위약금|위약벌|손해배상\s*(액|금)?\s*(을|를)?\s*(예정|미리)|벌금|그만두면.{0,12}(원|배상|물어)",
     "근로계약을 지키지 않을 때 낼 돈(위약금·손해배상액)을 미리 정하는 조항은 넣을 수 없습니다.", "근로기준법 §20(위약 예정의 금지)"),
    ("TOXIC_TRAINING_REFUND", "warn", r"교육비.{0,10}(반환|상환|물어)|연수비.{0,10}(반환|상환)",
     "교육비 반환 약정은 실제 쓴 비용·합리적 기간이면 유효할 수도, 일률 정액이면 위약 예정으로 무효일 수도 있습니다. 공인노무사 확인을 권합니다.", "근로기준법 §20"),
    ("TOXIC_SETOFF", "error", r"(가불|전차금|대여금|빌려준|선불).{0,15}(공제|상계|차감|뺀|제하)",
     "빌려준 돈(가불·대여금)을 임금에서 빼고 주는 조항은 넣을 수 없습니다.", "근로기준법 §21(전차금 상계의 금지)"),
    ("TOXIC_FORCED_SAVING", "error", r"강제\s*저축|적립금|예치금|보증금|저축.{0,6}(하여야|해야)|공탁",
     "저축·보증금을 강제하거나 회사가 맡아 두는 조항은 넣을 수 없습니다.", "근로기준법 §22(강제 저금의 금지)"),
    ("TOXIC_KEEP_ID", "error", r"(여권|외국인등록증|신분증|통장|도장).{0,8}(보관|맡|관리)",
     "근로자의 여권·신분증·통장·도장을 회사가 보관하면 안 됩니다.", "출입국관리법 §33의3, 외국인 표준근로계약서(별지 제6호서식) 9번 안내문"),
    ("TOXIC_SEVERANCE_INCLUDED", "error", r"퇴직금.{0,10}(포함|분할|매월|미리)",
     "퇴직금을 월급에 나눠 포함하는 약정은 퇴직금 지급으로 인정되지 않습니다.", "근로자퇴직급여 보장법 §8②(중간정산 사유 제한)"),
    ("TOXIC_NO_INSURANCE", "warn", r"(4대\s*보험|사회\s*보험).{0,10}(미가입|가입하지|안\s*함|제외)|3\.3\s*%|사업소득",
     "근로자인데 4대보험을 빼거나 3.3% 사업소득으로 처리하면 나중에 문제가 될 수 있습니다. 근로자인지 애매하면 공인노무사 확인을 권합니다.", "4대 사회보험 각 법(근로자 1명 이상 사업장 가입 의무)"),
    ("TOXIC_INCLUSIVE_WAGE", "warn", r"포괄|모든\s*수당.{0,6}포함|제\s*수당.{0,6}포함|연장.{0,6}수당.{0,6}포함",
     "'수당 포함' 식 포괄임금은 시간·금액을 나눠 적지 않으면 최저임금·가산수당 미달이 될 수 있습니다.", "근로기준법 §56, 최저임금법 §6"),
    ("TOXIC_FINE_DEDUCT", "warn", r"(지각|결근|조퇴|실수).{0,12}(공제|벌금|차감).{0,6}\d",
     "지각·결근 때 정액을 떼는 감급은 한도(1회 평균임금 1일분의 1/2, 총액은 1임금지급기 임금총액의 1/10)가 있고 취업규칙 근거가 필요합니다.", "근로기준법 §95(제재 규정의 제한)"),
    ("TOXIC_FREE_DISMISSAL", "warn", r"(언제든지|즉시|통보\s*없이).{0,6}해고|해고.{0,6}(이의|문제)\s*(없|제기하지)",
     "해고는 30일 전 예고(또는 예고수당)가 필요하고, 5인 이상은 정당한 이유도 필요합니다. 해고 관련은 공인노무사 상담을 권합니다.", "근로기준법 §23, §26"),
    ("TOXIC_NONCOMPETE", "warn", r"경업|동종\s*(업계|업종).{0,10}(취업|금지)|퇴사\s*후.{0,10}금지",
     "퇴사 뒤 경쟁업체 취업을 막는 조항은 보상·기간·지역에 따라 무효일 수 있습니다. 공인노무사·변호사 확인을 권합니다.", "헌법 §15(직업선택의 자유), 판례"),
    ("TOXIC_WAIVE", "error", r"(최저임금|주휴|연차|퇴직금).{0,8}(적용하지|없음|포기|청구하지|지급하지)",
     "법으로 정한 권리(최저임금·주휴·연차·퇴직금)를 포기·배제하는 조항은 무효입니다.", "근로기준법 §15(이 법을 위반한 근로계약), 최저임금법 §6③"),
]


def scan_toxic(texts, rep: Report, five_plus=True):
    for t in texts or []:
        if not t:
            continue
        for code, level, rx, msg, basis in TOXIC:
            if re.search(rx, t):
                lv = level
                # 연차 포기는 5인 미만이면 법정 의무가 아니므로 경고로만
                if code == "TOXIC_WAIVE" and "연차" in t and not five_plus:
                    lv = "info"
                rep.add(lv, code, f"「{t[:40]}」 — {msg}", basis)


# ───────────────────────── 근로계약서 공통 ─────────────────────────
def contract_schedule(work):
    """요일별 (시작,끝,휴게분,실근로h) 을 만든다."""
    work = work or {}
    sched = {}
    per = work.get("schedule") or {}
    for d in DAYS:
        if d in per:
            s = per[d]
            st, en = s.get("start"), s.get("end")
            br = s.get("breakMin") if s.get("breakMin") is not None else break_minutes(s.get("breaks"))
        elif d in (work.get("days") or []):
            st, en = work.get("start"), work.get("end")
            br = work.get("breakMin") if work.get("breakMin") is not None else break_minutes(work.get("breaks"))
        else:
            continue
        hours = day_work_hours(st, en, br)
        sched[d] = {"start": st, "end": en, "breakMin": br, "hours": hours,
                    "nightMin": night_minutes(st, en)}
    return sched


def _min_break_required(work_min):
    # 근로시간 4시간에 30분, 8시간에 1시간 이상 (§54)
    if work_min >= 480:
        return 60
    if work_min >= 240:
        return 30
    return 0


def _wage_numbers(data, weekly_hours, daily_hours):
    """최저임금 엔진 입력으로 바꾼다."""
    w = data.get("wage") or {}
    typ, amt = w.get("type"), w.get("amount")
    allowances = w.get("allowances") or []
    regular_taxable = sum(a.get("amount") or 0 for a in allowances
                          if a.get("monthlyRegular", True) and not a.get("taxFree") and a.get("kind") != "car")
    meal = sum(a.get("amount") or 0 for a in allowances if a.get("kind") == "meal")
    car = sum(a.get("amount") or 0 for a in allowances if a.get("kind") == "car")
    base_date = (data.get("contract") or {}).get("startDate") or data.get("signDate") or "2026-11-09"
    inp = {"payDate": base_date, "taxableAllowance": regular_taxable,
           "mealAllowance": meal, "carAllowance": car}
    if typ == "시급":
        inp.update({"hourlyWage": amt, "weeklyHours": weekly_hours})
    elif typ == "일급":
        if daily_hours:
            inp.update({"hourlyWage": (amt or 0) / daily_hours, "weeklyHours": weekly_hours})
    else:  # 월급
        inp.update({"baseSalary": amt, "ordinaryHours": monthly_paid_hours(weekly_hours) or 209})
    return inp


def check_contract(data, kind, rep: Report):
    """kind: regular | fixed | parttime | minor"""
    emp, er, c = data.get("employee") or {}, data.get("employer") or {}, data.get("contract") or {}
    work, wage = data.get("work") or {}, data.get("wage") or {}
    five_plus = bool((data.get("workplace") or {}).get("size5plus"))
    if (data.get("workplace") or {}).get("size5plus") is None:
        rep.add("missing", "SIZE", "상시 근로자가 5명 이상인지(5인 이상 여부)를 정해 주세요. 연차·가산수당·공휴일 적용이 달라집니다.",
                "근로기준법 §11, 시행령 §7 [별표 1]")

    rep.need(er.get("name"), "EMPLOYER_NAME", "사업장 이름", "근로기준법 §17(당사자 특정)")
    rep.need(er.get("ceo"), "EMPLOYER_CEO", "대표자", "근로기준법 §17")
    rep.need(emp.get("name"), "EMPLOYEE_NAME", "근로자 성명", "근로기준법 §17")
    rep.need(c.get("startDate"), "START", "근로 시작일", "근로기준법 §17, 기간제법 §17 1호")
    rep.need(c.get("place"), "PLACE", "일하는 곳(근무장소)", "근로기준법 시행령 §8 1호, 기간제법 §17 5호")
    rep.need(c.get("duties"), "DUTIES", "하는 일(업무내용)", "근로기준법 시행령 §8 1호, 기간제법 §17 5호")

    if kind == "fixed" or (kind in ("parttime", "minor") and c.get("endDate")):
        if rep.need(c.get("endDate"), "END", "계약 끝나는 날", "기간제법 §17 1호"):
            s, e = parse_date(c.get("startDate")), parse_date(c.get("endDate"))
            if s and e:
                if e <= s:
                    rep.add("error", "END_BEFORE_START", "계약 끝나는 날이 시작일보다 빠르거나 같습니다.", "기간제법 §17 1호")
                elif (e - s).days > 731:
                    rep.add("warn", "OVER_2Y", "계약기간이 2년을 넘습니다. 기간제는 원칙적으로 2년을 넘기면 기간 정함 없는 근로자로 봅니다.",
                            "기간제법 §4")

    sched = contract_schedule(work)
    rep.derived["schedule"] = sched
    if not sched:
        rep.add("missing", "HOURS", "일하는 요일과 시작·끝 시각(소정근로시간)이 비어 있습니다.", "근로기준법 §17①2호·②")
    weekly = sum(v["hours"] or 0 for v in sched.values())
    daily_max = max([v["hours"] or 0 for v in sched.values()] or [0])
    days_n = len(sched)
    daily_typ = (weekly / days_n) if days_n else None
    rep.derived.update({"weeklyHours": round(weekly, 2), "dailyMaxHours": round(daily_max, 2), "workDays": days_n})

    for d, s in sched.items():
        if s["hours"] is None:
            rep.add("missing", "HOURS_DAY", f"{d}요일 시작·끝 시각이 비었습니다.", "근로기준법 §17①2호")
            continue
        need = _min_break_required(span_minutes(s["start"], s["end"]) - (s["breakMin"] or 0))
        if (s["breakMin"] or 0) < need:
            rep.add("error", "BREAK", f"{d}요일 휴게 {s['breakMin'] or 0}분 — 근로 {s['hours']:.1f}시간이면 휴게를 {need}분 이상 줘야 합니다.",
                    "근로기준법 §54(5인 미만 포함)")

    # 법정근로시간·연소자 근로시간
    if kind == "minor":
        if daily_max > 7 + 1e-9 or weekly > 35 + 1e-9:
            rep.add("error", "MINOR_HOURS", f"18세 미만은 소정근로 1일 7시간·1주 35시간을 넘길 수 없습니다(지금 1일 최대 {daily_max:.1f}h, 주 {weekly:.1f}h).",
                    "근로기준법 §69")
        if any(s["nightMin"] for s in sched.values()):
            if not (data.get("minor") or {}).get("nightApproval"):
                rep.add("error", "MINOR_NIGHT", "18세 미만은 밤 10시~아침 6시에 일을 시킬 수 없습니다(본인 동의 + 고용노동부 인가가 있을 때만 예외).",
                        "근로기준법 §70②")
        if any(d in ("일",) for d in sched) and work.get("weeklyHoliday") != "일" and not (data.get("minor") or {}).get("holidayApproval"):
            pass
    else:
        if daily_max > 8 + 1e-9 or weekly > 40 + 1e-9:
            lv = "error" if five_plus else "warn"
            rep.add(lv, "OVER_LEGAL", f"정해진 근로시간(소정근로)이 1일 8시간·1주 40시간을 넘습니다(1일 최대 {daily_max:.1f}h, 주 {weekly:.1f}h). 넘는 시간은 연장근로로 따로 적어야 합니다.",
                    "근로기준법 §50·§2①8호" + ("" if five_plus else " (5인 미만은 §50 미적용이지만 시간 구분 기재 권장)"))

    # 단시간: 근로일·근로일별 시간
    if kind == "parttime":
        if not (work.get("schedule") or work.get("days")):
            lv = "missing" if five_plus else "warn"
            rep.add(lv, "PT_SCHEDULE", "단시간 근로자는 일하는 날과 그날그날의 근로시간을 적어야 합니다.",
                    "기간제법 §17 6호" + ("" if five_plus else " (4인 이하 사업장은 6호 미적용 — 시행령 [별표 1]. 그래도 적어 두는 게 안전)"))
        if weekly >= 40:
            rep.add("warn", "PT_NOT_SHORT", "주 40시간 이상이면 단시간 근로자가 아닐 수 있습니다. 정규직·기간제 양식을 쓰세요.", "근로기준법 §2①9호")

    # 휴일
    if weekly >= 15:
        if not work.get("weeklyHoliday"):
            rep.add("missing", "WEEKLY_HOLIDAY", "주휴일(쉬는 요일)을 정해 주세요. 주 15시간 이상이면 유급 주휴일이 있습니다.", "근로기준법 §55①, §17①3호")
        elif work.get("weeklyHoliday") in sched:
            rep.add("warn", "HOLIDAY_IS_WORKDAY", f"주휴일({work.get('weeklyHoliday')}요일)이 일하는 요일과 겹칩니다.", "근로기준법 §55①")
    else:
        rep.add("info", "UNDER15", f"주 소정근로 {weekly:.1f}시간(15시간 미만)이라 주휴일·연차가 생기지 않습니다.", "근로기준법 §18③")
    ph = work.get("publicHolidaysPaid")
    if five_plus and ph is False:
        rep.add("error", "PUBLIC_HOLIDAY", "5인 이상 사업장은 빨간날(관공서 공휴일·대체공휴일)을 유급휴일로 줘야 합니다.", "근로기준법 §55②")
    if ph is None:
        rep.add("missing" if five_plus else "info", "PUBLIC_HOLIDAY_UNSET",
                "공휴일을 유급휴일로 주는지 정해 주세요." if five_plus else "5인 미만은 공휴일 유급휴일 의무가 없습니다. 줄지 말지 정하면 계약서에 적어 드립니다.",
                "근로기준법 §55②")

    # 임금
    rep.need(wage.get("type"), "WAGE_TYPE", "임금 형태(월급·시급·일급)", "근로기준법 §17①1호·②")
    rep.need(wage.get("amount"), "WAGE_AMOUNT", "임금 금액", "근로기준법 §17①1호·②")
    rep.need(wage.get("payDay"), "PAY_DAY", "임금 지급일", "근로기준법 §17② (지급방법), §43②(매월 1회 이상 일정한 날)")
    rep.need(wage.get("payMethod"), "PAY_METHOD", "지급 방법(계좌·직접)", "근로기준법 §17② (지급방법)")

    # 최저임금 (엔진)
    if wage.get("type") and wage.get("amount") and sched:
        inp = _wage_numbers(data, weekly, daily_typ)
        pr = data.get("probation") or {}
        if pr.get("months"):
            ys = 99 if kind == "regular" else _contract_years(c)
            inp.update({"probation": bool(pr.get("reducedPay")), "probationMonths": pr.get("months"),
                        "contractYears": ys, "simpleLabor": bool(data.get("simpleLabor"))})
            if pr.get("months") > 3 and pr.get("reducedPay"):
                rep.add("error", "PROBATION_LONG", "수습 중 최저임금 감액은 3개월까지만 됩니다.", "최저임금법 §5②, 시행령 §3")
        try:
            mw = calc.minwage(inp)
            mw = _hourly_exact(mw, wage)
            rep.derived["minimumWage"] = {k: mw.get(k) for k in ("signal", "effectiveHourly", "appliedMinHourly", "hours", "comparableWage", "shortfallMonthly", "violated")}
            rep.derived["minimumWage"]["year"] = mw.get("minWageYear") or mw.get("usingYear")
            if mw.get("violated"):
                rep.add("error", "MIN_WAGE", f"최저임금보다 적어 보입니다: 시간당 {mw['effectiveHourly']:,}원 < {mw['appliedMinHourly']:,}원 (월 {mw['shortfallMonthly']:,}원 부족, 환산 {mw['hours']}시간 기준, 기준일 {inp['payDate']}).",
                        mw_basis(inp["payDate"]))
            for wmsg in mw.get("warnings") or []:
                if "수습" in wmsg:
                    rep.add("warn", "PROBATION", wmsg, "최저임금법 §5②, 시행령 §3")
            # 계약이 다음 해(등록된 새 연도)까지 이어지면 그해 1월 1일부터의 최저임금도 미리 본다
            for y in _later_years(inp["payDate"], c.get("endDate")):
                mw2 = _hourly_exact(calc.minwage({**inp, "payDate": f"{y}-01-01"}), wage)
                if mw2.get("violated"):
                    now_h = wage["amount"] if wage.get("type") == "시급" else mw2["effectiveHourly"]
                    rep.add("warn", f"MIN_WAGE_{y}",
                            f"{y}-01-01부터는 최저임금이 시급 {MIN_WAGE[y][0]:,}원으로 오릅니다. 지금 임금(시간당 {now_h:,}원)은 {y}년부터 미달이니, 그 전에 임금을 올리거나 계약을 고쳐 주세요(월 {mw2['shortfallMonthly']:,}원 부족).",
                            mw_basis(f"{y}-01-01"))
        except calc.EngineError as e:
            rep.add("warn", "ENGINE", f"최저임금 계산을 못 했습니다: {e}")

    # 시급제 주휴
    if wage.get("type") == "시급" and weekly >= 15 and wage.get("amount"):
        h2m = calc.hourly_to_monthly(wage["amount"], weekly)
        rep.derived["hourly"] = h2m
        if wage.get("weeklyHolidayIncluded"):
            rep.add("warn", "HOLIDAY_PAY_INCLUDED", "'시급에 주휴수당 포함'으로 적으면 나중에 다툼이 잦습니다. 시급과 주휴수당을 나눠 적는 것을 권합니다.",
                    "근로기준법 §55①, 최저임금법 §6")

    # 고정 연장근로(포괄) 금액 점검
    fo = work.get("fixedOvertime") or {}
    if fo.get("hoursMonthly"):
        hourly = None
        if wage.get("type") == "시급":
            hourly = wage.get("amount")
        elif wage.get("type") == "월급" and wage.get("amount"):
            hourly = wage["amount"] / (monthly_paid_hours(weekly) or 209)
        if hourly:
            mult = 1.5 if five_plus else 1.0
            need_amt = hourly * fo["hoursMonthly"] * mult
            rep.derived["fixedOvertimeNeed"] = round(need_amt)
            if (fo.get("amount") or 0) + 1 < need_amt:
                rep.add("error", "FIXED_OT_SHORT", f"고정 연장수당 {fo.get('amount') or 0:,}원이 월 {fo['hoursMonthly']}시간분 계산값(약 {round(need_amt):,}원, 통상시급×{mult}배)보다 적습니다.",
                        "근로기준법 §56" + ("" if five_plus else " (5인 미만은 가산 없이 1.0배)"))
        if five_plus and weekly + fo["hoursMonthly"] / (365 / 7 / 12) > 52 + 1e-9:
            rep.add("error", "OVER_52", "정해진 연장근로를 더하면 주 52시간을 넘습니다.", "근로기준법 §53")
        if kind == "minor":
            if fo["hoursMonthly"] / (365 / 7 / 12) > 5 + 1e-9:
                rep.add("error", "MINOR_OT", "18세 미만의 연장근로는 1주 5시간까지입니다.", "근로기준법 §69 단서")

    # 상여·수당: 구성항목 표기
    for a in wage.get("allowances") or []:
        if not a.get("name"):
            rep.add("missing", "ALLOWANCE_NAME", "이름 없는 수당이 있습니다. 수당 이름을 적어 주세요.", "근로기준법 §17② (임금 구성항목)")

    # 사회보험
    ins = data.get("insurance")
    if ins is None:
        rep.add("missing", "INSURANCE", "4대보험 적용 여부를 정해 주세요.", "고용노동부 표준근로계약서 8번")
    elif weekly >= 15 and not all(ins.get(k, False) for k in ("employment", "industrial", "pension", "health")):
        rep.add("warn", "INSURANCE_PARTIAL", "주 15시간 이상 근로자인데 4대보험 중 빠진 것이 있습니다. 나이(국민연금 60세 이상 등)·예외 사유가 아니면 가입 대상입니다. 4대사회보험 정보연계센터에서 확인하세요.",
                "국민연금법·국민건강보험법·고용보험법·산재보험법")
    if ins is not None and not ins.get("industrial", False):
        rep.add("warn", "NO_INDUSTRIAL", "산재보험은 근로자를 1명이라도 쓰면 가입 대상입니다.", "산업재해보상보험법 §6")

    scan_toxic(data.get("specialTerms"), rep, five_plus)
    rep.need(data.get("signDate"), "SIGN_DATE", "계약 체결일", "근로기준법 §17②(교부)")

    if kind == "minor":
        check_minor(data, rep)


def _hourly_exact(mw, wage):
    """시급제는 시급 자체를 최저시급과 바로 비교한다. 원본 엔진은 월 환산(×4.345주) 반올림 때문에
    시급이 최저시급과 '딱 같을 때' 1원 미만 차이로 위반으로 잘못 판정할 수 있다(실측: 10,320원 → 10,319원)."""
    if wage.get("type") == "시급" and wage.get("amount") and mw.get("violated"):
        if wage["amount"] >= mw.get("appliedMinHourly", MIN_WAGE[mw.get("minWageYear") or 2026][0]):
            mw = {**mw, "violated": False, "effectiveHourly": wage["amount"], "shortfallMonthly": 0,
                  "signal": "🟢 최저임금 이상", "note": "시급 직접 비교(엔진 월 환산 반올림 보정)"}
    return mw


def _contract_years(c):
    s, e = parse_date(c.get("startDate")), parse_date(c.get("endDate"))
    if s and e:
        return round((e - s).days / 365, 2)
    return 99


def check_minor(data, rep: Report):
    emp = data.get("employee") or {}
    m = data.get("minor") or {}
    age = age_on(emp.get("birth"), data.get("signDate") or (data.get("contract") or {}).get("startDate"))
    rep.derived["age"] = age
    if not rep.need(emp.get("birth"), "MINOR_BIRTH", "근로자 생년월일", "근로기준법 §66"):
        return
    if age is not None and age >= 18:
        rep.add("warn", "MINOR_NOT_MINOR", f"만 {age}세 — 18세 이상이면 연소자 양식이 아니라 일반 양식을 쓰세요.", "근로기준법 §66")
    if (age is not None and age < 15) or m.get("middleSchool"):
        if not m.get("employmentPermit"):
            who = f"만 {age}세" if (age is not None and age < 15) else "중학교 재학 중"
            rep.add("error", "MINOR_PERMIT", f"{who} — 15세 미만(중학교 재학 중인 18세 미만 포함)은 고용노동부장관의 취직인허증이 있어야 일할 수 있습니다.", "근로기준법 §64①")
    if not m.get("familyCertificate"):
        rep.add("missing", "MINOR_FAMILY_CERT", "나이를 증명하는 가족관계증명서를 받아 두었는지 표시해 주세요.", "근로기준법 §66")
    if not m.get("guardianConsent"):
        rep.add("missing", "MINOR_CONSENT", "친권자(후견인) 동의서를 받아 두었는지 표시해 주세요(동의서 양식이 함께 만들어집니다).", "근로기준법 §66")
    g = m.get("guardian") or {}
    if not g.get("name"):
        rep.add("missing", "GUARDIAN_NAME", "친권자(후견인) 성명이 비었습니다(동의서 칸).", "근로기준법 §66")
    rep.add("info", "MINOR_HAZARD", "18세 미만은 도덕·보건상 유해하거나 위험한 일(시행령 §40에서 정한 직종)에 쓸 수 없습니다. 업무를 한 번 더 확인하세요.", "근로기준법 §65, 시행령 §40")


# ───────────────────────── 외국인 ─────────────────────────
def check_foreign(data, rep: Report):
    er, emp = data.get("employer") or {}, data.get("employee") or {}
    t = data.get("term") or {}
    w = data.get("work") or {}
    wage = data.get("wage") or {}
    five_plus = bool((data.get("workplace") or {}).get("size5plus"))
    B = "외국인고용법 시행규칙 [별지 제6호서식]"
    for k, lab in (("name", "업체명"), ("phone", "전화번호"), ("address", "소재지"), ("ceo", "사용자 성명"), ("bizNo", "사업자등록번호")):
        rep.need(er.get(k), "F_EMPLOYER_" + k.upper(), lab, B)
    for k, lab in (("name", "근로자 성명"), ("birth", "생년월일"), ("homeAddress", "본국주소")):
        rep.need(emp.get(k), "F_EMPLOYEE_" + k.upper(), lab, B)
    kind = t.get("kind")
    if kind not in ("new", "change"):
        rep.add("missing", "F_TERM_KIND", "신규·재입국자인지, 사업장변경자인지 골라 주세요.", B + " 1번")
    elif kind == "new":
        rep.need(t.get("months"), "F_TERM_MONTHS", "근로계약기간(개월)", B + " 1번")
    else:
        rep.need(t.get("from"), "F_TERM_FROM", "계약 시작일", B + " 1번")
        rep.need(t.get("to"), "F_TERM_TO", "계약 종료일", B + " 1번")
    pr = t.get("probation") or {}
    if pr.get("use") and (pr.get("months") or 0) > 3:
        rep.add("warn", "F_PROBATION", "수습기간이 3개월을 넘습니다. 최저임금 감액은 3개월까지만 가능합니다.", "최저임금법 §5②")
    rep.need(data.get("place"), "F_PLACE", "근로장소", B + " 2번")
    jd = data.get("job") or {}
    for k, lab in (("industry", "업종"), ("business", "사업내용"), ("duties", "직무내용")):
        rep.need(jd.get(k), "F_JOB_" + k.upper(), lab, B + " 3번(구체적 업무 반드시 기재)")
    domestic = jd.get("domesticOrCare", False)
    if not domestic:
        rep.need(w.get("start"), "F_START", "근로 시작 시각", B + " 4번")
        rep.need(w.get("end"), "F_END", "근로 끝 시각", B + " 4번")
        rep.need(w.get("breakMin"), "F_BREAK", "휴게시간(분)", B + " 5번")
    h = data.get("holidays") or {}
    if not any(h.get(k) for k in ("sunday", "saturday", "publicHoliday", "other")):
        rep.add("missing", "F_HOLIDAYS", "휴일을 골라 주세요(일요일·공휴일·토요일 등).", B + " 6번")
    if five_plus and h.get("publicHoliday") == "무급":
        rep.add("error", "PUBLIC_HOLIDAY", "5인 이상 사업장은 관공서 공휴일을 유급으로 줘야 합니다.", "근로기준법 §55②")
    rep.need(wage.get("monthlyOrdinary"), "F_WAGE_ORD", "월 통상임금", B + " 7번")
    rep.need((wage.get("basic") or {}).get("amount"), "F_WAGE_BASIC", "기본급", B + " 7번")
    pd = wage.get("payDay") or {}
    if not (pd.get("monthDay") or pd.get("weekday")):
        rep.add("missing", "F_PAYDAY", "임금지급일을 적어 주세요.", B + " 8번")
    rep.need(wage.get("payMethod"), "F_PAYMETHOD", "지급방법", B + " 9번")
    l, m = data.get("lodging") or {}, data.get("meals") or {}
    if l.get("provided") is None:
        rep.add("missing", "F_LODGING", "숙박시설 제공 여부를 골라 주세요.", B + " 10번")
    if m.get("provided") is None:
        rep.add("missing", "F_MEALS", "식사 제공 여부를 골라 주세요.", B + " 10번")
    if (l.get("costMonthly") or 0) > 0 or (m.get("costMonthly") or 0) > 0:
        rep.add("warn", "F_LODGING_COST", "숙식비를 받으려면 계약서에 금액을 적고, 월급에서 미리 떼려면 근로자 자국어로 된 서면 공제동의를 받아야 합니다. 여럿이 함께 살면 나눠서 부담합니다(1/n). 임금명세서에도 공제 내역을 적으세요.",
                "고용노동부 「외국인근로자 주거 관련 가이드라인」(2023.11.27 시행)")
    if l.get("provided") and l.get("type") in ("컨테이너", "조립식 패널"):
        rep.add("warn", "F_LODGING_TYPE", "컨테이너·조립식 패널 숙소는 가설건축물 축조신고 등 기준을 지켜야 하고, 숙소비는 지역 월세 최저액을 넘지 않게 하는 것이 원칙입니다.",
                "고용노동부 「외국인근로자 주거 관련 가이드라인」")

    # 최저임금 — 월 통상임금 ÷ 월 유급시간
    weekly = w.get("weeklyHours")
    if weekly is None and w.get("start") and w.get("end") and w.get("daysPerWeek"):
        weekly = day_work_hours(w["start"], w["end"], w.get("breakMin") or 0) * w["daysPerWeek"]
    rep.derived["weeklyHours"] = weekly
    if wage.get("monthlyOrdinary") and weekly:
        base_date = data.get("startDate") or data.get("signDate") or "2026-11-09"
        inp = {"baseSalary": wage["monthlyOrdinary"], "ordinaryHours": monthly_paid_hours(weekly) or 209, "payDate": base_date}
        mw = calc.minwage(inp)
        rep.derived["minimumWage"] = {k: mw.get(k) for k in ("signal", "effectiveHourly", "appliedMinHourly", "hours", "shortfallMonthly", "violated")}
        rep.derived["minimumWage"]["year"] = mw.get("minWageYear") or mw.get("usingYear")
        if mw.get("violated"):
            rep.add("error", "MIN_WAGE", f"월 통상임금이 최저임금보다 적어 보입니다: 시간당 {mw['effectiveHourly']:,}원 < {mw['appliedMinHourly']:,}원 (월 {mw['shortfallMonthly']:,}원 부족, 기준일 {base_date}).",
                    mw_basis(base_date))
        # 계약기간(개월)이 다음 해 1월 1일까지 이어지면 그해 최저임금도 미리 본다
        bd = parse_date(base_date)
        months = t.get("months") or 0
        if bd and months:
            end_y = bd.year + (bd.month - 1 + int(months)) // 12
            for y in _later_years(base_date, f"{end_y}-12-31"):
                if y > end_y:
                    continue
                mw2 = calc.minwage({**inp, "payDate": f"{y}-01-01"})
                if mw2.get("violated"):
                    rep.add("warn", f"MIN_WAGE_{y}",
                            f"{y}-01-01부터는 최저임금이 시급 {MIN_WAGE[y][0]:,}원(월 209시간 {MIN_WAGE[y][0] * 209:,}원)으로 오릅니다. 지금 월 통상임금은 {y}년부터 미달이니, 그 전에 임금을 올려 주세요(월 {mw2['shortfallMonthly']:,}원 부족).",
                            mw_basis(f"{y}-01-01"))
        pw = wage.get("probationWage")
        if pr.get("use") and pw:
            hrs = monthly_paid_hours(weekly) or 209
            floor90 = mw_hour(base_date) * 0.9 * hrs
            if pw + 1 < floor90:
                rep.add("error", "F_PROBATION_WAGE", f"수습 임금 {pw:,}원이 최저임금 90%({round(floor90):,}원)보다도 적습니다.", "최저임금법 §5②, 시행령 §3")
            if pw < mw_hour(base_date) * hrs:
                rep.add("warn", "F_PROBATION_SIMPLE", "수습 감액은 1년 이상 계약 + 3개월 이내 + 단순노무 직종이 아닐 때만 됩니다. 단순노무(고용노동부 고시 직종)면 감액할 수 없습니다.",
                        "최저임금법 §5② 단서, 시행령 §3")
    scan_toxic(data.get("specialTerms"), rep, five_plus)
    rep.need(data.get("signDate"), "SIGN_DATE", "계약 체결일", B)


# ───────────────────────── 증명서 ─────────────────────────
ADVERSE = re.compile(r"징계|해고|권고사직|무단|불량|횡령|문제")


def check_cert(data, kind, rep: Report):
    er, emp = data.get("employer") or {}, data.get("employee") or {}
    B = "근로기준법 §39(사용증명서)"
    for k, lab in (("name", "회사명"), ("ceo", "대표자"), ("bizNo", "사업자등록번호"), ("address", "소재지")):
        rep.need(er.get(k), "C_EMPLOYER_" + k.upper(), lab, B)
    rep.need(emp.get("name"), "C_NAME", "성명", B)
    rep.need(emp.get("birth"), "C_BIRTH", "생년월일", B)
    rep.need(data.get("issueDate"), "C_ISSUE", "발급일", B)
    rep.need(data.get("purpose"), "C_PURPOSE", "발급 용도", "권장(용도 한정)")
    req = set(data.get("requestedItems") or [])
    rep.derived["requestedItems"] = sorted(req)
    if kind == "employment":
        rep.need(emp.get("joinDate"), "C_JOIN", "입사일", B)
        start = emp.get("joinDate")
        end = data.get("issueDate")
    else:
        periods = data.get("periods") or []
        if not periods:
            rep.add("missing", "C_PERIODS", "근무기간(시작~끝)·부서·직위 줄이 없습니다.", B)
        start = min((p.get("from") for p in periods if p.get("from")), default=None)
        end = max((p.get("to") for p in periods if p.get("to")), default=None)
        reason = emp.get("leaveReason")
        if reason and "leaveReason" not in req:
            rep.add("error", "C_REASON_UNREQUESTED", "퇴직사유는 근로자가 요청한 경우에만 적습니다. 요청이 없으면 빼 주세요.", "근로기준법 §39②")
        if reason and ADVERSE.search(reason):
            rep.add("warn", "C_REASON_ADVERSE", "퇴직사유에 불리하게 보일 수 있는 표현이 있습니다. 근로자가 요청한 내용 그대로인지 확인하세요.", "근로기준법 §39②, §40(취업 방해 금지)")
        if data.get("issueDate") and (parse_date(data["issueDate"]) - parse_date(end)).days > 365 * 3 if (end and data.get("issueDate")) else False:
            rep.add("info", "C_OVER_3Y", "퇴직 후 3년이 지난 청구는 법적 발급 의무 대상이 아닙니다(자율 발급은 가능).", "근로기준법 시행령 §19")
    if start and end:
        days = (parse_date(end) - parse_date(start)).days + 1
        rep.derived["tenureDays"] = days
        if days < 30:
            rep.add("info", "C_UNDER_30", "계속 30일 미만 근무자는 법적 청구 대상이 아닙니다(자율 발급은 가능).", "근로기준법 시행령 §19")
    if "salary" in req and not data.get("salary"):
        rep.add("missing", "C_SALARY", "임금 항목을 요청받았는데 금액이 비었습니다.", B)
    if data.get("salary") and "salary" not in req:
        rep.add("error", "C_SALARY_UNREQUESTED", "임금은 근로자가 요청한 경우에만 적습니다.", "근로기준법 §39②")


# ───────────────────────── 임금명세서 ─────────────────────────
def check_payslip(data, rep: Report, result=None):
    emp = data.get("employee") or {}
    B = "근로기준법 §48②, 시행령 §27의2"
    rep.need(emp.get("name"), "P_NAME", "근로자 성명", B + " 1호")
    if not (emp.get("birth") or emp.get("employeeNo")):
        rep.add("missing", "P_ID", "생년월일이나 사원번호 등 근로자를 특정할 정보가 비었습니다.", B + " 1호")
    rep.need(data.get("payDate"), "P_PAYDATE", "임금지급일", B + " 2호")
    rep.need((data.get("employer") or {}).get("name"), "P_EMPLOYER", "사업장 이름", "권장")
    p = data.get("pay") or {}
    if not p.get("type"):
        rep.add("missing", "P_PAYTYPE", "임금 형태(월급/시급)를 정해 주세요.", B + " 4호")
    ot = data.get("hours") or {}
    if any(ot.get(k) for k in ("overtime", "night", "holidayWithin8", "holidayOver8")) and not data.get("calcNotes", True):
        pass
    for x in data.get("extraEarnings") or []:
        if not x.get("name"):
            rep.add("missing", "P_EXTRA_NAME", "이름 없는 지급 항목이 있습니다.", B + " 4호")
        if x.get("variable") and not x.get("method"):
            rep.add("missing", "P_EXTRA_METHOD", f"'{x.get('name')}'은 근무일수·시간에 따라 달라지는 항목이라 계산방법을 적어야 합니다.", B + " 5호")
    for x in data.get("inKind") or []:
        for k, lab in (("item", "품명"), ("qty", "수량"), ("value", "평가총액")):
            if not x.get(k):
                rep.add("missing", "P_INKIND", f"현물 지급 항목의 {lab}이 비었습니다.", B + " 4호")
    for x in data.get("otherDeductions") or []:
        if not x.get("basis"):
            rep.add("warn", "P_DEDUCT_BASIS", f"'{x.get('name')}' 공제의 근거(법령·단체협약·근로자 서면 동의 등)를 적어 주세요. 근거 없는 공제는 안 됩니다.", "근로기준법 §43①")
    fam = (data.get("incomeTax") or {}).get("family")
    if fam is None and (data.get("incomeTax") or {}).get("mode", "table") == "table":
        rep.add("info", "P_FAMILY", "공제대상 가족 수(본인 포함)를 모르면 본인 1명으로 계산합니다. 부양가족이 있으면 소득세가 실제보다 많이 나옵니다.", "소득세법 시행령 [별표 2]")
    if result:
        mw = result.get("minimumWage") or {}
        p_ = data.get("pay") or {}
        if p_.get("type") == "hourly":
            mw = _hourly_exact(mw, {"type": "시급", "amount": p_.get("hourlyWage")})
        rep.derived["minimumWage"] = {k: mw.get(k) for k in ("signal", "effectiveHourly", "appliedMinHourly", "hours", "shortfallMonthly", "violated")}
        rep.derived["minimumWage"]["year"] = mw.get("minWageYear") or mw.get("usingYear")
        if mw.get("violated"):
            bdate = data.get("periodTo") or data.get("periodFrom") or data.get("payDate")
            rep.add("error", "MIN_WAGE", f"이번 달 임금이 최저임금보다 적어 보입니다: 시간당 {mw['effectiveHourly']:,}원 < {mw['appliedMinHourly']:,}원 (기준: 임금계산기간 {bdate}).",
                    mw_basis(bdate))
        if result.get("netPay", 0) < 0:
            rep.add("error", "P_NEGATIVE", "공제액이 지급액보다 많습니다.", "근로기준법 §43①(전액 지급)")
        if p.get("type") == "hourly" and (p.get("weeklyHours") or 0) >= 15 and not p.get("weeklyHolidayHours") and p.get("mode") == "actual":
            rep.add("warn", "P_NO_HOLIDAY_PAY", "주 15시간 이상 일하는 시급 근로자인데 주휴수당 시간이 0입니다. 결근 주가 아니면 주휴수당을 넣어 주세요.", "근로기준법 §55①, §18③")
        for wmsg in (result.get("meta") or {}).get("warnings") or []:
            if wmsg.startswith("🔴"):
                continue
            rep.add("info", "ENGINE_NOTE", wmsg, "계산 엔진")
    five_plus = bool((data.get("workplace") or {}).get("size5plus"))
    if not five_plus and any((data.get("hours") or {}).get(k) for k in ("overtime", "night", "holidayWithin8", "holidayOver8")):
        rep.add("info", "P_FIVE_UNDER", "5인 미만이라 연장·야간·휴일에 50% 가산을 붙이지 않고 일한 시간만큼(1.0배)만 계산했습니다.", "근로기준법 §56, 시행령 [별표 1]")


DOC_KINDS = {
    "contract_regular": ("contract", "regular"),
    "contract_fixed": ("contract", "fixed"),
    "contract_parttime": ("contract", "parttime"),
    "contract_minor": ("contract", "minor"),
    "contract_foreign": ("foreign", None),
    "cert_employment": ("cert", "employment"),
    "cert_career": ("cert", "career"),
    "payslip": ("payslip", None),
}


def check(data, result=None) -> Report:
    rep = Report()
    scan_sensitive(data, rep)
    doc = data.get("doc")
    if doc not in DOC_KINDS:
        rep.add("error", "DOC", f"알 수 없는 서류 종류: {doc}. 가능한 값: {', '.join(DOC_KINDS)}")
        return rep
    fam, kind = DOC_KINDS[doc]
    if fam == "contract":
        check_contract(data, kind, rep)
    elif fam == "foreign":
        check_foreign(data, rep)
    elif fam == "cert":
        check_cert(data, kind, rep)
    else:
        check_payslip(data, rep, result)
    return rep
