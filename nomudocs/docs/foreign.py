"""외국인근로자 표준근로계약서 — 외국인근로자의 고용 등에 관한 법률 시행규칙 [별지 제6호서식]
(제조업·건설업·서비스업용, 법제처 국가법령정보센터 서식 원문 기준) 항목을 한국어/영어로 그대로 옮겼다.
농업·축산업·어업은 [별지 제6호의2서식]을 따로 써야 한다(이 생성기 범위 밖)."""
from ..docx_builder import BLANK, Doc, box, v, won, ymd


def _c(flag):
    return box(bool(flag))


def render(data, rep, footer):
    er, emp = data.get("employer") or {}, data.get("employee") or {}
    t, w, h = data.get("term") or {}, data.get("work") or {}, data.get("holidays") or {}
    job, wage = data.get("job") or {}, data.get("wage") or {}
    l, m = data.get("lodging") or {}, data.get("meals") or {}
    d = Doc("표준근로계약서", "Standard Labor Contract", footer=footer, base_size=8.5)
    d.p("■ 외국인근로자의 고용 등에 관한 법률 시행규칙 [별지 제6호서식] 항목 기준", gray=True, size=7.5)
    d.p("아래 당사자는 다음과 같이 근로계약을 체결하고 이를 성실히 이행할 것을 약정한다.")
    d.p("The following parties to the contract agree to fully comply with the terms of the contract stated hereinafter.", space_after=4)

    d.table([
        ["사용자\nEmployer", f"업체명 Name of the enterprise\n{v(er.get('name'))}", f"전화번호 Phone number\n{v(er.get('phone'))}"],
        ["", f"소재지 Location of the enterprise\n{v(er.get('address'))}", ""],
        ["", f"성명 Name of the employer\n{v(er.get('ceo'))}", f"사업자등록번호(주민등록번호) Identification number\n{v(er.get('bizNo'))}"],
        ["근로자\nEmployee", f"성명 Name of the employee\n{v(emp.get('name'))}", f"생년월일 Birthdate\n{v(emp.get('birth'))}"],
        ["", f"본국주소 Address(Home Country)\n{v(emp.get('homeAddress'))}", ""],
    ], widths=[24, 85, 65], shade_first_col=True)

    pr = t.get("probation") or {}
    pm = pr.get("months")
    new, chg = t.get("kind") == "new", t.get("kind") == "change"
    term_ko = (f"- 신규 또는 재입국자: ( {v(t.get('months')) if new else '　'} ) 개월\n"
               f"- 사업장변경자: {ymd(t.get('from')) if chg else '　　년 　월 　일'} ~ {ymd(t.get('to')) if chg else '　　년 　월 　일'}\n"
               f"* 수습기간: {_c(pr.get('use'))}활용(입국일부터 {_c(pm == 1)}1개월 {_c(pm == 2)}2개월 {_c(pm == 3)}3개월 {_c(pm and pm not in (1, 2, 3))}{pm if pm and pm not in (1, 2, 3) else '　'}개월) {_c(pr.get('use') is False)}미활용\n"
               "※ 신규 또는 재입국자의 근로계약기간은 입국일부터 기산함(다만, 「외국인근로자의 고용 등에 관한 법률」 제18조의4제1항에 따라 재입국(성실재입국)한 경우는 입국하여 근로를 시작한 날부터 기산함).")
    term_en = (f"- Newcomer or Re-entering employee: ( {v(t.get('months')) if new else '　'} ) month(s)\n"
               f"- Employee who changed workplace: from ( {t.get('from') if chg else 'YY/MM/DD'} ) to ( {t.get('to') if chg else 'YY/MM/DD'} )\n"
               f"* Probation period: {_c(pr.get('use'))} Included (for {_c(pm == 1)} 1 month {_c(pm == 2)} 2 months {_c(pm == 3)} 3 months from entry date – or specify other: {pm if pm and pm not in (1, 2, 3) else '　'}), {_c(pr.get('use') is False)} Not included\n"
               "※ The employment term for newcomers and re-entering employees will begin on their date of arrival in Korea, while the employment of those who re-entered through the committed workers' system will commence on their first day of work as stipulated in Article 18-4 (1) of Act on Foreign Workers' Employment, etc.")
    shift = w.get("shift")
    sh = lambda k: _c(shift == k)
    rows = [
        ["1. 근로계약기간\n1. Term of Labor contract", term_ko + "\n\n" + term_en],
        ["2. 근로장소\n2. Place of employment", f"{v(data.get('place'))}\n※ 근로자를 이 계약서에서 정한 장소 외에서 근로하게 해서는 안 됨.\n※ The undersigned employee is not allowed to work apart from the contract enterprise."],
        ["3. 업무내용\n3. Description of work",
         f"- 업종 Industry: {v(job.get('industry'))}\n- 사업내용 Business description: {v(job.get('business'))}\n- 직무내용 Job description: {v(job.get('duties'))}\n"
         "※ 외국인근로자가 사업장에서 수행할 구체적인 업무를 반드시 기재\n※ Detailed duties and responsibilities of the employee must be stated"],
        ["4. 근로시간\n4. Working hours",
         f"{v(w.get('start'))} ~ {v(w.get('end'))}  (from {v(w.get('start'))} to {v(w.get('end'))})\n"
         f"- 1일 평균 시간외 근로시간 average daily over time: {v(w.get('avgOvertimeDaily'))}시간 hours\n"
         f"  (사업장 사정에 따라 변동 가능 changeable depending on the condition of a company: {v(w.get('overtimeMaxDaily'))}시간 이내 up to hour(s))\n"
         f"- 교대제 shift system ({sh('2조2교대')}2조2교대 2groups 2shifts, {sh('3조3교대')}3조3교대 3groups 3shifts, {sh('4조3교대')}4조3교대 4groups 3shifts, {sh('기타')}기타 etc.)\n"
         "※ 가사사용인, 개인간병인의 경우에는 기재를 생략할 수 있음. Employers of workers in domestic help, nursing can omit the working hours."],
        ["5. 휴게시간\n5. Recess hours", f"1일 {v(w.get('breakMin'))}분   ( {v(w.get('breakMin'))} ) minutes per day"],
        ["6. 휴일\n6. Holidays",
         f"{_c(h.get('sunday'))}일요일 {_c(h.get('publicHoliday'))}공휴일({_c(h.get('publicHoliday') == '유급')}유급 {_c(h.get('publicHoliday') == '무급')}무급) "
         f"{_c(h.get('saturday') == '매주')}매주 토요일 {_c(h.get('saturday') == '격주')}격주 토요일, {_c(h.get('other'))}기타({v(h.get('other'), empty='　')})\n"
         f"{_c(h.get('sunday'))}Sunday {_c(h.get('publicHoliday'))}Legal holiday({_c(h.get('publicHoliday') == '유급')}Paid {_c(h.get('publicHoliday') == '무급')}Unpaid) "
         f"{_c(h.get('saturday') == '매주')}Every saturday {_c(h.get('saturday') == '격주')}Every other Saturday {_c(h.get('other'))}etc.({v(h.get('other'), empty='　')})"],
    ]
    d.table(rows, widths=[34, 140], shade_first_col=True)

    basic = wage.get("basic") or {}
    bt = basic.get("type", "월")
    fx = wage.get("fixedAllowances") or []
    fx_ko = ", ".join(f"({a.get('name')} 수당: {won(a.get('amount'))})" for a in fx) or "(　 수당: 　원), (　 수당: 　원)"
    fx_en = ", ".join(f"({a.get('nameEn') or a.get('name')} benefits: {v(a.get('amount'))})won" for a in fx) or "( benefits: )won, ( benefits: )won"
    bonus = wage.get("bonus")
    five_plus = bool((data.get("workplace") or {}).get("size5plus"))
    pd = wage.get("payDay") or {}
    pm_ = wage.get("payMethod")
    ltypes = ["주택", "고시원", "오피스텔", "숙박시설", "컨테이너", "조립식 패널", "사업장 건물"]
    ltypes_en = ["Detached houses", "Goshiwans", "Studio-flats", "Lodging facilities(such as motels, hostels and pension hotels, etc.)", "Container boxes", "SIP panel constructions", "Rooms within the business building"]
    lt = l.get("type")
    lt_ko = ", ".join(f"{_c(lt == x)}{x}" for x in ltypes) + f", 기타 주택형태 시설({v(l.get('otherType'), empty='　') if lt == '기타' else '　'})"
    lt_en = ", ".join(f"{_c(lt == x)}{e}" for x, e in zip(ltypes, ltypes_en)) + f" – or specify other housing or boarding facilities ({l.get('otherType') if lt == '기타' else '　'})"
    ml = m.get("which") or []
    rows2 = [
        ["7. 임금\n7. Payment",
         f"1) 월 통상임금 ( {v(wage.get('monthlyOrdinary'))} )원\n"
         f"- 기본급[({_c(bt == '월')}월, {_c(bt == '시간')}시간, {_c(bt == '일')}일, {_c(bt == '주')}주)급] ( {v(basic.get('amount'))} )원\n"
         f"- 고정적 수당: {fx_ko}\n- 상여금 ( {v(bonus, empty='　')} 원)\n"
         f"* 수습기간 중 임금 ( {v(wage.get('probationWage'), empty='　')} )원, 수습시작일부터 3개월 이내 근무기간 ( {v(wage.get('probationFirst3Wage'), empty='　')} )원\n"
         "2) 연장, 야간, 휴일근로에 대해서는 통상임금의 50%를 가산하여 수당 지급(상시근로자 4인 이하 사업장에는 해당되지 않음)\n\n"
         f"1) Monthly Normal wages ( {v(wage.get('monthlyOrdinary'))} )won\n"
         f"- Basic pay[({_c(bt == '월')}Monthly, {_c(bt == '시간')}hourly, {_c(bt == '일')}daily, {_c(bt == '주')}weekly) wage] ( {v(basic.get('amount'))} )won\n"
         f"- Fixed benefits: {fx_en}\n- Bonus: ( {v(bonus, empty='　')} )won\n"
         f"* Wage during probation ( {v(wage.get('probationWage'), empty='　')} ) won, but for up to the first 3 months of probation period: ( {v(wage.get('probationFirst3Wage'), empty='　')} ) won\n"
         "2) Overtime, night shift or holiday will be paid 50% more than the employee's regular rate of pay(This is not applicable to business with 4 or less employees)."],
        ["8. 임금지급일\n8. Payment date",
         f"매월 ( {v(pd.get('monthDay'), empty='　')} )일 또는 매주 ( {v(pd.get('weekday'), empty='　')} )요일. 다만, 임금 지급일이 공휴일인 경우에는 전날에 지급함.\n"
         f"Every ( {v(pd.get('monthDay'), empty='　')} )th day of the month or every ( {v(pd.get('weekdayEn') or pd.get('weekday'), empty='　')} day) of the week. If the payment date falls on a holiday, the payment will be made on the day before the holiday."],
        ["9. 지급방법\n9. Payment methods",
         f"{_c(pm_ == '직접')}직접 지급, {_c(pm_ == '통장')}통장 입금\n※ 사용자는 근로자 명의로 된 예금통장 및 도장을 관리해서는 안 됨.\n"
         f"{_c(pm_ == '직접')}In person, {_c(pm_ == '통장')}By direct deposit transfer into the employee's account\n※ The employer must not keep the bankbook and the seal of the employee."],
        ["10. 숙식제공\n10. Accommodations and Meals",
         f"1) 숙박시설 제공\n- 숙박시설 제공 여부: {_c(l.get('provided') is True)}제공 {_c(l.get('provided') is False)}미제공\n"
         f"제공 시, 숙박시설의 유형({lt_ko})\n- 숙박시설 제공 시 근로자 부담금액: 매월 {v(l.get('costMonthly'), empty='　')} 원\n"
         f"2) 식사 제공\n- 식사 제공 여부: 제공({_c('조식' in ml)}조식, {_c('중식' in ml)}중식, {_c('석식' in ml)}석식) {_c(m.get('provided') is False)}미제공\n"
         f"- 식사 제공 시 근로자 부담금액: 매월 {v(m.get('costMonthly'), empty='　')} 원\n"
         "※ 근로자의 비용 부담 수준은 사용자와 근로자 간 협의(신규 또는 재입국자의 경우 입국 이후)에 따라 별도로 결정.\n\n"
         f"1) Provision of accommodations\n- Provision of accommodations: {_c(l.get('provided') is True)}Provided, {_c(l.get('provided') is False)}Not provided\n"
         f"(If provided, accommodation types: {lt_en})\n- Cost of accommodation paid by employee: {v(l.get('costMonthly'), empty='　')} won/month\n"
         f"2) Provision of meals\n- Provision of meals: {_c(m.get('provided') is True)}Provided({_c('조식' in ml)}breakfast, {_c('중식' in ml)}lunch, {_c('석식' in ml)}dinner), {_c(m.get('provided') is False)} Not provided\n"
         f"- Cost of meals paid by employee: {v(m.get('costMonthly'), empty='　')} won/month\n"
         "※ The amount of costs paid by employee, will be determined by mutual consultation between the employer and employee (Newcomers and re-entering employees will consult with their employers after arrival in Korea)."],
    ]
    d.table(rows2, widths=[34, 140], shade_first_col=True, size=7.8)
    d.p("11. 사용자와 근로자는 각자가 근로계약, 취업규칙, 단체협약을 지키고 성실하게 이행해야 한다.")
    d.p("11. Both employees and employers shall comply with collective agreements, rules of employment, and terms of labor contracts and be obliged to fulfill them in good faith.")
    d.p("12. 이 계약에서 정하지 않은 사항은 「근로기준법」에서 정하는 바에 따른다.")
    d.p("※ 가사서비스업 및 개인간병인에 종사하는 외국인근로자의 경우 근로시간, 휴일ㆍ휴가, 그 밖에 모든 근로조건에 대해 사용자와 자유롭게 계약을 체결하는 것이 가능합니다.", size=7.8)
    d.p("12. Other matters not regulated in this contract will follow provisions of the Labor Standards Act.")
    d.p("※ The terms and conditions of the labor contract for employees in domestic help and nursing can be freely decided through the agreement between an employer and an employee.", size=7.8, space_after=6)
    sd = data.get("signDate")
    d.p(f"{ymd(sd)}   ({sd.replace('-', '/') if sd else 'YY/MM/DD'})", align="center", space_after=6)
    d.table([["사용자: " + v(er.get("ceo")) + "            (서명 또는 인)\nEmployer:                        (signature)",
              "근로자: " + v(emp.get("name")) + "            (서명 또는 인)\nEmployee:                        (signature)"]], widths=[87, 87])
    if data.get("specialTerms"):
        d.p("※ 별도 약정(이 서식 밖 내용)은 근로기준법 등 법령에 어긋나지 않아야 합니다:", size=7.8)
        for s in data["specialTerms"]:
            d.p("   - " + s, size=7.8)
    return d
