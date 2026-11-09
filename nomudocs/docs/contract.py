"""근로계약서 — 정규직 / 기간제 / 단시간(알바) / 연소자(18세 미만).
틀은 고용노동부 「표준 근로계약서」(2025 개정 배포본) 항목 순서를 따르고,
원본 nomu-people templates/employment-contract.md 의 §17 필수항목·5인 미만 분기를 반영했다."""
from ..docx_builder import BLANK, Doc, box, v, won, ymd
from ..timeutil import DAYS, monthly_paid_hours, weekly_holiday_hours

TITLES = {
    "regular": ("표준 근로계약서", "(기간의 정함이 없는 경우)"),
    "fixed": ("표준 근로계약서", "(기간의 정함이 있는 경우)"),
    "parttime": ("단시간근로자 표준 근로계약서", None),
    "minor": ("연소근로자(18세 미만인 자) 표준 근로계약서", None),
}


def _wage_lines(data, rep, five_plus, kind):
    w = data.get("wage") or {}
    weekly = rep.derived.get("weeklyHours") or 0
    typ, amt = w.get("type"), w.get("amount")
    rows = [["구성항목", "금액", "비고"]]
    rows.append([f"기본급({v(typ, empty='월급·시급·일급')})", won(amt), w.get("baseNote", "")])
    for a in w.get("allowances") or []:
        rows.append([v(a.get("name")), won(a.get("amount")),
                     ("비과세 " if a.get("taxFree") else "") + ("매월 고정" if a.get("monthlyRegular", True) else "비정기") + (" · " + a["note"] if a.get("note") else "")])
    b = w.get("bonus") or {}
    rows.append(["상여금", won(b.get("amount")) if b.get("amount") else "없음", b.get("note", "")])
    fo = (data.get("work") or {}).get("fixedOvertime") or {}
    if fo.get("hoursMonthly"):
        rows.append(["고정 연장근로수당", won(fo.get("amount")), f"월 {fo['hoursMonthly']}시간분(시간·금액 구분 표기)"])
    calc = []
    if typ == "월급":
        hrs = monthly_paid_hours(weekly) or 209
        calc.append(f"월급제: 위 금액은 월 소정근로시간과 유급주휴시간을 합한 월 {hrs}시간분 임금입니다.")
    elif typ == "시급":
        calc.append("시급제: 시급 × 실제 일한 소정근로시간으로 계산합니다.")
        if weekly >= 15:
            hh = weekly_holiday_hours(weekly)
            calc.append(f"주휴수당: 1주 소정근로일을 개근하면 1주에 {hh:g}시간분(시급 × {hh:g}시간)을 따로 지급합니다.")
        else:
            calc.append("1주 소정근로시간이 15시간 미만이라 주휴수당은 생기지 않습니다(근로기준법 제18조제3항).")
    elif typ == "일급":
        calc.append("일급제: 일급 × 실제 근무일수로 계산합니다.")
    if five_plus:
        calc.append("연장·야간(오후 10시~오전 6시)·휴일 근로를 하면 통상임금의 50%를 더해 지급합니다(근로기준법 제56조).")
        if kind == "parttime":
            calc.append("정해진 근로시간을 넘겨 일하면(법정근로시간 이내라도) 통상임금의 50% 이상을 더해 지급합니다(기간제법 제6조제3항). 초과근로는 근로자 동의를 받아 1주 12시간 이내로 합니다.")
    else:
        calc.append("연장·야간·휴일 근로를 하면 일한 시간만큼 통상시급으로 지급합니다(상시 5인 미만 사업장: 근로기준법 제56조 가산 의무 적용 제외).")
    if w.get("calcNote"):
        calc.append(w["calcNote"])
    pd = w.get("payDay")
    pay = [f"임금지급일: {v(w.get('payCycle'), empty='매월')} {v(pd)}일 (지급일이 휴일이면 그 전날 지급)",
           f"지급방법: {box(w.get('payMethod') == '직접')} 근로자에게 직접 지급   {box(w.get('payMethod') == '계좌')} 근로자 명의 예금통장에 입금"]
    return rows, calc, pay


def render(data, rep, kind, footer):
    er, emp, c = data.get("employer") or {}, data.get("employee") or {}, data.get("contract") or {}
    work = data.get("work") or {}
    five_plus = bool((data.get("workplace") or {}).get("size5plus"))
    weekly = rep.derived.get("weeklyHours") or 0
    sched = rep.derived.get("schedule") or {}
    t, sub = TITLES[kind]
    d = Doc(t, sub, footer=footer)
    d.p(f"{v(er.get('name'))}(이하 \"사업주\"라 함)과(와) {v(emp.get('name'))}(이하 \"근로자\"라 함)은 다음과 같이 근로계약을 체결한다.", space_after=6)

    # 1. 기간
    if kind == "regular" or (kind in ("parttime", "minor") and not c.get("endDate")):
        d.h(f"1. 근로개시일: {ymd(c.get('startDate'))}부터 (기간의 정함 없음)")
    else:
        d.h(f"1. 근로계약기간: {ymd(c.get('startDate'))}부터 {ymd(c.get('endDate'))}까지")
    pr = data.get("probation") or {}
    if pr.get("months"):
        d.p(f"   수습기간: 근로개시일부터 {pr['months']}개월" + (" (수습 중 임금은 아래 6번 비고에 적은 금액)" if pr.get("reducedPay") else ""))
    d.h(f"2. 근무장소: {v(c.get('place'))}")
    d.h(f"3. 업무의 내용: {v(c.get('duties'))}")

    # 4. 소정근로시간
    uniform = not work.get("schedule") and work.get("start")
    if uniform:
        brk = work.get("breakMin")
        bt = ""
        if work.get("breaks"):
            bt = ", ".join(f"{b['start']}~{b['end']}" for b in work["breaks"] if isinstance(b, dict))
        d.h(f"4. 소정근로시간: {v(work.get('start'))}부터 {v(work.get('end'))}까지 (휴게시간: {bt or v(brk, '분')})")
        d.p(f"   1일 {v(round(max((s['hours'] or 0) for s in sched.values()), 2) if sched else None, '시간')} · 1주 {v(round(weekly, 2) if sched else None, '시간')}")
    else:
        d.h("4. 근로일 및 근로일별 근로시간")
    if kind in ("parttime",) or not uniform:
        rows = [["요일"] + DAYS, ["근로시간"], ["시업"], ["종업"], ["휴게시간"]]
        for dd in DAYS:
            s = sched.get(dd)
            rows[1].append(f"{s['hours']:g}시간" if s and s["hours"] is not None else "-")
            rows[2].append(v(s and s["start"], empty="-"))
            rows[3].append(v(s and s["end"], empty="-"))
            rows[4].append(v(s and s["breakMin"], "분", empty="-"))
        d.table(rows, widths=[22] + [21] * 7, header=True, shade_first_col=True)
        d.p(f"   1주 소정근로시간 합계: {weekly:g}시간")

    # 5. 근무일/휴일
    days = list(sched.keys())
    hol = work.get("weeklyHoliday")
    if weekly >= 15:
        htxt = f"주휴일 매주 {v(hol)}요일(1주 소정근로일 개근 시 유급)"
    else:
        htxt = "1주 소정근로시간 15시간 미만으로 유급주휴일 없음(근로기준법 제18조제3항)"
    d.h(f"5. 근무일/휴일: 매주 {len(days)}일({'·'.join(days) or BLANK}) 근무, {htxt}")
    ph = work.get("publicHolidaysPaid")
    if ph is True:
        d.p("   관공서 공휴일·대체공휴일: 유급휴일로 함" + ("(근로기준법 제55조제2항)" if five_plus else "(사업주가 정해 주는 것)"))
    elif ph is False:
        d.p("   관공서 공휴일·대체공휴일: 유급휴일 아님" + ("" if five_plus else "(상시 5인 미만 사업장: 근로기준법 제55조제2항 적용 제외)"))
    else:
        d.p(f"   관공서 공휴일·대체공휴일: {box(False)} 유급휴일  {box(False)} 해당 없음")

    # 6. 임금
    d.h("6. 임금")
    rows, calc_lines, pay = _wage_lines(data, rep, five_plus, kind)
    if pr.get("months") and pr.get("reducedPay"):
        rows.append(["수습기간 중 임금", won(pr.get("wage")), f"수습 {pr['months']}개월 이내"])
    d.table(rows, widths=[50, 40, 84], header=True)
    d.p("   계산방법", bold=True)
    d.lines(["- " + x for x in calc_lines], indent=True)
    d.lines(["- " + x for x in pay], indent=True)

    # 7. 연차
    n = 7
    if weekly < 15:
        lv = "1주 소정근로시간 15시간 미만으로 연차유급휴가는 생기지 않음(근로기준법 제18조제3항)"
    elif five_plus:
        lv = "연차유급휴가는 근로기준법 제60조에서 정하는 바에 따라 부여함"
        if kind == "parttime":
            lv += "(통상근로자의 근로시간에 비례하여 부여 — 근로기준법 시행령 [별표 2])"
    else:
        lv = (data.get("annualLeaveCustom") or
              "상시 5인 미만 사업장으로 근로기준법 제60조 연차유급휴가는 적용되지 않음")
    d.h(f"{n}. 연차유급휴가: {lv}")
    n += 1
    if kind == "minor":
        m = data.get("minor") or {}
        d.h(f"{n}. 가족관계증명서 및 동의서")
        d.p(f"   - 가족관계기록사항에 관한 증명서 제출 여부: {box(m.get('familyCertificate'))} 제출함")
        d.p(f"   - 친권자 또는 후견인의 동의서 구비 여부: {box(m.get('guardianConsent'))} 구비함")
        n += 1
    ins = data.get("insurance") or {}
    d.h(f"{n}. 사회보험 적용여부: {box(ins.get('employment'))} 고용보험  {box(ins.get('industrial'))} 산재보험  {box(ins.get('pension'))} 국민연금  {box(ins.get('health'))} 건강보험")
    n += 1
    law = "근로기준법 제17조, 제67조 이행" if kind == "minor" else "근로기준법 제17조 이행"
    d.h(f"{n}. 근로계약서 교부")
    d.p(f"   사업주는 근로계약을 체결함과 동시에 본 계약서를 사본하여 근로자의 교부 요구와 관계없이 근로자에게 교부함({law})")
    n += 1
    d.h(f"{n}. 근로계약, 취업규칙 등의 성실한 이행의무")
    d.p("   사업주와 근로자는 각자가 근로계약, 취업규칙, 단체협약을 지키고 성실하게 이행하여야 함")
    n += 1
    d.h(f"{n}. 기타")
    if kind == "minor":
        d.p("   - 13세 이상 15세 미만인 자(중학교 재학 중인 18세 미만인 자 포함)는 고용노동부장관으로부터 취직인허증을 교부받아야 함")
        d.p("   - 오후 10시부터 오전 6시까지 및 휴일에는 근로시키지 않음(근로기준법 제70조제2항 — 본인 동의와 고용노동부장관 인가가 있는 경우 제외)")
    for s in data.get("specialTerms") or []:
        d.p(f"   - {s}")
    d.p("   - 이 계약에 정함이 없는 사항은 근로기준법령에 의함")

    # 서명
    d.p("")
    d.p(ymd(data.get("signDate")), align="center", space_after=6, keep_with_next=True)
    d.table([
        ["(사업주)", f"사업체명: {v(er.get('name'))}   (전화: {v(er.get('phone'))})\n주    소: {v(er.get('address'))}\n대 표 자: {v(er.get('ceo'))}                    (서명)"],
        ["(근로자)", f"주    소: {v(emp.get('address'))}\n연 락 처: {v(emp.get('phone'))}\n성    명: {v(emp.get('name'))}                    (서명)"],
        ["교부 확인", "위 근로계약서 1부를 받았습니다.        근로자                    (서명)"],
    ], widths=[24, 150], shade_first_col=True, keep_together=True)

    if kind == "minor":
        _consent(d, data)
    return d


def _consent(d, data):
    m = data.get("minor") or {}
    g = m.get("guardian") or {}
    emp, er = data.get("employee") or {}, data.get("employer") or {}
    d.page_break()
    d.title("친권자(후견인) 동의서")
    d.h("○ 친권자(후견인) 인적사항")
    d.table([["성명", v(g.get("name"))], ["생년월일", v(g.get("birth"))], ["주소", v(g.get("address"))],
             ["연락처", v(g.get("phone"))], ["연소근로자와의 관계", v(g.get("relation"))]], widths=[45, 129], shade_first_col=True)
    d.h("○ 연소근로자 인적사항")
    age = None
    from ..timeutil import age_on
    age = age_on(emp.get("birth"), data.get("signDate"))
    d.table([["성명", f"{v(emp.get('name'))} (만 {v(age)}세)"], ["생년월일", v(emp.get("birth"))],
             ["주소", v(emp.get("address"))], ["연락처", v(emp.get("phone"))]], widths=[45, 129], shade_first_col=True)
    d.h("○ 사업장 개요")
    d.table([["회사명", v(er.get("name"))], ["회사주소", v(er.get("address"))], ["대표자", v(er.get("ceo"))],
             ["회사전화", v(er.get("phone"))]], widths=[45, 129], shade_first_col=True)
    d.p("")
    d.p(f"본인은 위 연소근로자 {v(emp.get('name'))}가 위 사업장에서 근로를 하는 것에 대하여 동의합니다.", space_after=10)
    d.p(ymd(None), align="center", space_after=10)
    d.p("친권자(후견인)                    (인)", align="right", space_after=14)
    d.p("첨    부: 가족관계증명서 1부")
