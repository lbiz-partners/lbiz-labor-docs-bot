"""임금명세서 — 근로기준법 §48②·시행령 §27의2 6개 호. 숫자는 전부 원본 급여 엔진 결과."""
from ..docx_builder import Doc, v, won


def build_engine_input(data):
    p = data.get("pay") or {}
    h = data.get("hours") or {}
    it = data.get("incomeTax") or {}
    ins = data.get("insurance") or {}
    extra = data.get("extraEarnings") or []
    taxable_extra = sum(x.get("amount") or 0 for x in extra if not x.get("taxFree") and not x.get("bonus"))
    bonus = sum(x.get("amount") or 0 for x in extra if x.get("bonus"))
    taxfree_other = sum(x.get("amount") or 0 for x in extra if x.get("taxFree") and x.get("kind") not in ("meal", "car", "childcare"))
    meal = sum(x.get("amount") or 0 for x in extra if x.get("kind") == "meal")
    car = sum(x.get("amount") or 0 for x in extra if x.get("kind") == "car")
    care = sum(x.get("amount") or 0 for x in extra if x.get("kind") == "childcare")
    inkind = sum(x.get("value") or 0 for x in data.get("inKind") or [])
    inp = {
        "payDate": data.get("payDate"),
        "fiveUnder": not bool((data.get("workplace") or {}).get("size5plus")),
        "taxableAllowance": taxable_extra + inkind, "bonus": bonus,
        "mealAllowance": meal, "carAllowance": car, "childcareAllowance": care, "otherTaxFree": taxfree_other,
        "overtimeHours": h.get("overtime") or 0, "nightHours": h.get("night") or 0,
        "holidayHoursWithin8": h.get("holidayWithin8") or 0, "holidayHoursOver8": h.get("holidayOver8") or 0,
        "otherDeductions": sum(x.get("amount") or 0 for x in data.get("otherDeductions") or []),
        "incomeTax": {"mode": it.get("mode", "table"), "childrenUnder20": it.get("childrenUnder20", 0),
                      **({"family": it["family"]} if it.get("family") is not None else {}),
                      **({"manualTax": it["manualTax"]} if it.get("manualTax") is not None else {})},
    }
    ov = {}
    if ins.get("pension") is False:
        ov["nationalPension"] = 0
    if ins.get("health") is False:
        ov["health"] = 0
    if ins.get("employment") is False:
        ov["employment"] = 0
    if ov:
        inp["rateOverride"] = ov
    typ = p.get("type")
    if typ == "monthly":
        inp["baseSalary"] = p.get("baseSalary")
        if p.get("ordinaryMonthly"):
            inp["ordinaryMonthly"] = p["ordinaryMonthly"]  # 통상임금(정기·일률 고정수당 포함 시 사장님이 직접 입력)
        if p.get("ordinaryHours"):
            inp["ordinaryHours"] = p["ordinaryHours"]
    elif typ == "hourly" and p.get("mode") == "actual":
        hw = p.get("hourlyWage") or 0
        base = round(hw * (p.get("workedHours") or 0))
        hol = round(hw * (p.get("weeklyHolidayHours") or 0))
        inp["baseSalary"] = base + hol
        inp["ordinaryMonthly"] = hw * 209
        inp["ordinaryHours"] = 209
        inp["_split"] = {"base": base, "holiday": hol}
        # 최저임금 점검은 실제 시급·주 소정시간 기준으로
        inp["_mw"] = {"hourlyWage": hw, "weeklyHours": p.get("weeklyHours")}
    elif typ == "hourly":
        inp["hourlyWage"] = p.get("hourlyWage")
        inp["weeklyHours"] = p.get("weeklyHours")
    return inp


def _fmt_h(x):
    return f"{x:g}"


def render(data, rep, result, footer):
    er, emp = data.get("employer") or {}, data.get("employee") or {}
    p = data.get("pay") or {}
    h = data.get("hours") or {}
    e, dd = result["earnings"], result["deductions"]
    hourly_ord = result["input"]["hourlyOrdinary"]
    five_plus = bool((data.get("workplace") or {}).get("size5plus"))
    d = Doc("임 금 명 세 서", subtitle=f"{v(data.get('periodLabel'), empty='　　년 　월')}분", footer=footer)
    d.table([
        ["사업장", v(er.get("name")), "성명", v(emp.get("name"))],
        ["생년월일(사원번호)", v(emp.get("birth") or emp.get("employeeNo")), "부서/직급", v(emp.get("dept"))],
        ["임금지급일", v(data.get("payDate")), "임금계산기간", f"{v(data.get('periodFrom'))} ~ {v(data.get('periodTo'))}"],
        ["근무일수", v(data.get("workDays"), "일"), "총 근로시간", v(data.get("totalHours"), "시간")],
    ], widths=[34, 53, 30, 57], shade_first_col=True)

    # 지급 항목
    rows = [["지급 항목", "금액(원)", "계산방법"]]
    split = (data.get("_engine_input") or {}).get("_split")
    if p.get("type") == "hourly" and p.get("mode") == "actual":
        rows.append(["기본급", f"{split['base']:,}", f"시급 {p['hourlyWage']:,}원 × {_fmt_h(p.get('workedHours') or 0)}시간"])
        rows.append(["주휴수당", f"{split['holiday']:,}", f"시급 {p['hourlyWage']:,}원 × 이번 달 주휴 합계 {_fmt_h(p.get('weeklyHolidayHours') or 0)}시간"])
    elif p.get("type") == "hourly":
        rows.append(["기본급(주휴 포함)", f"{e['baseSalary']:,}", f"시급 {p.get('hourlyWage'):,}원 × (주 {_fmt_h(p.get('weeklyHours'))}시간 + 주휴) × 월 평균 4.345주"])
    else:
        rows.append(["기본급", f"{e['baseSalary']:,}", "월 고정"])
    m = 1.5 if five_plus else 1.0
    if h.get("overtime"):
        rows.append(["연장근로수당", f"{e['overtimePay']:,}", f"통상시급 {hourly_ord:,}원 × {m:g} × 연장 {_fmt_h(h['overtime'])}시간"])
    if h.get("night"):
        rows.append(["야간근로수당", f"{e['nightPay']:,}", f"통상시급 {hourly_ord:,}원 × 0.5 × 야간 {_fmt_h(h['night'])}시간" if five_plus else f"야간 {_fmt_h(h['night'])}시간 (5인 미만 가산 없음)"])
    if h.get("holidayWithin8"):
        rows.append(["휴일근로수당(8시간 이내)", f"{e['holiday8Pay']:,}", f"통상시급 {hourly_ord:,}원 × {m:g} × 휴일 {_fmt_h(h['holidayWithin8'])}시간"])
    if h.get("holidayOver8"):
        rows.append(["휴일근로수당(8시간 초과)", f"{e['holidayOver8Pay']:,}", f"통상시급 {hourly_ord:,}원 × {2.0 if five_plus else 1.0:g} × 휴일 {_fmt_h(h['holidayOver8'])}시간"])
    for x in data.get("extraEarnings") or []:
        rows.append([v(x.get("name")) + (" (비과세)" if x.get("taxFree") else ""), f"{(x.get('amount') or 0):,}", v(x.get("method"), empty="-")])
    for x in data.get("inKind") or []:
        rows.append([f"현물: {v(x.get('item'))}", f"{(x.get('value') or 0):,}", f"수량 {v(x.get('qty'))} · 평가총액"])
    rows.append(["지급액 합계(임금 총액)", f"{e['grossPay']:,}", ""])
    d.h("① 지급 내역")
    d.table(rows, widths=[48, 32, 94], header=True)

    # 공제
    fam = (data.get("incomeTax") or {}).get("family")
    rows = [["공제 항목", "금액(원)", "비고"],
            ["국민연금", f"{dd['nationalPension']:,}", "근로자 부담분 4.75%"],
            ["건강보험", f"{dd['healthInsurance']:,}", "근로자 부담분 3.595% (10원 미만 절사)"],
            ["장기요양보험", f"{dd['longTermCare']:,}", "건강보험료 × 0.9448/7.19 (10원 미만 절사)"],
            ["고용보험", f"{dd['employmentInsurance']:,}", "근로자 부담분 0.9%"],
            ["소득세", f"{dd['incomeTax']:,}", f"간이세액표 · 공제대상 가족 {fam if fam is not None else 1}명(본인 포함)"
             + (f" · 8~20세 자녀 {(data.get('incomeTax') or {}).get('childrenUnder20')}명" if (data.get('incomeTax') or {}).get('childrenUnder20') else "")],
            ["지방소득세", f"{dd['localIncomeTax']:,}", "소득세의 10%"]]
    for x in data.get("otherDeductions") or []:
        rows.append([v(x.get("name")), f"{(x.get('amount') or 0):,}", "근거: " + v(x.get("basis"))])
    rows.append(["공제액 합계", f"{dd['totalDeductions']:,}", ""])
    d.h("② 공제 내역")
    d.table(rows, widths=[48, 32, 94], header=True)

    d.h("③ 실지급액")
    d.table([["지급액 합계", f"{e['grossPay']:,}원"], ["(−) 공제액 합계", f"{dd['totalDeductions']:,}원"],
             ["실지급액", f"{result['netPay']:,}원"]], widths=[60, 114], shade_first_col=True)
    d.p("※ 4대보험료는 공단 고지액, 소득세는 국세청 간이세액표가 최종 기준입니다. 이 명세서는 근로기준법 제48조제2항에 따라 임금 지급 때마다 교부하고 3년간 보관합니다.", gray=True, size=8)
    return d
