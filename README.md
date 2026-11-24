# 노무 서류 도우미

사장님이 입력한 내용으로 근로계약서·증명서·임금명세서·임금대장을 **채우고, 계산하고, 빈칸을 점검**하는 도구. 판단·대리 작성·상담은 하지 않는다(공인노무사법 업무 영역과 선 긋기).

만든 곳: **엘비즈파트너스**. 라이선스: **MIT** ([LICENSE](LICENSE), Copyright (c) 2026 엘비즈파트너스(LBIZ Partners)). 계산 엔진(`engine/vendor/`)도 엘비즈파트너스가 만든 것입니다. 자세한 출처는 [NOTICE.md](NOTICE.md).

## 구조
```
nomudocs/            파이썬 패키지
  checks.py          점검(§17 빈칸, 최저임금, 통상임금 확인 알림, 휴게·근로시간, 주휴·공휴일, 연소자, 외국인, 증명서, 명세서, 독소조항, 민감정보)
  calc.py            node 계산 엔진 호출
  generate.py        점검 → DOCX → PDF → PNG, 점검결과.json
  docs/              서류별 양식(contract, foreign, certificates, payslip, ledger)
  docx_builder.py    A4·표·글꼴(맑은 고딕 → Noto Sans CJK KR로 대체 렌더)
  render.py          LibreOffice(DOCX→PDF), pdftoppm(PDF→PNG)
  timeutil.py        날짜·시간 계산(증명서 근속기간 년·개월·일 포함)
engine/calc.mjs      원본 .mjs 엔진 다리(연도별 기준값·보정)
engine/vendor/       원본 엔진 사본(수정 없음, 출처는 NOTICE.md)
render/fonts.conf    한글 글꼴 대체 설정(FONTCONFIG_FILE로만 적용, 시스템 설정 안 건드림)
samples/             서류별 예시 입력(가짜 값) = 입력 형식 견본
tests/               자동 시험(unittest)
docs/bot-instructions-draft/  봇 지침·스킬·카드 문구 초안(실제 봇에는 아직 안 넣음)
RATES_CHECK.md       기준값 교차확인표
OTHER_DOCS.md        다른 서류 포함 제안
NOTICE.md            만든 곳·저작권·라이선스·출처
LICENSE              MIT 라이선스 전문
```
`out/`(예시 산출물)은 `make_samples.py`를 돌리면 생기고 저장소에는 넣지 않는다.

## 사용
```
python3 -m nomudocs check samples/contract_regular.json
python3 -m nomudocs make  samples/contract_regular.json out/contract_regular
python3 make_samples.py                      # 예시 전부
python3 -m unittest discover -s tests -v     # 시험
```
필요: Python 3.10+, python-docx, node 18+, (PDF용) LibreOffice + Noto Sans CJK KR, poppler-utils.

## 설계 원칙
- 입력은 사장님 말 그대로, 값 지어내기 없음. 빈칸은 빈칸으로 출력하고 점검에서 알린다.
- 주민번호 전체·비밀번호가 입력에 있으면 서류를 만들지 않는다(`Blocked`).
- 서류마다 바닥글: "이 서류는 사업주가 직접 입력한 내용으로 만든 양식입니다(적용한 기준값은 함께 만든 점검결과에 적혀 있습니다). 내용 확인과 교부 책임은 사업주에게 있습니다."
- 계산은 원본 엔진 그대로 + 다리 보정. 점검 문장에는 조문 근거를 붙인다. 원문으로 확인 못 한 값은 [확인 필요]로 표시한다.
- 통상임금에 넣을지 같은 판단은 하지 않는다. 빠뜨리지 않게 사장님께 묻는 알림(`ORDINARY_WAGE_CHECK`)만 낸다.

## 설치
봇은 「노무서류 시작하기」 스킬 3절 순서로 **최신 정식 릴리즈**를 받는다(하루 한 번만 새 판 확인, 검사·시험이 모두 통과할 때만 교체). 손으로 받을 때:
```
TAG=$(curl -fsSL https://api.github.com/repos/lbiz-partners/lbiz-labor-docs-bot/releases/latest | python3 -c "import sys,json; print(json.load(sys.stdin)['tag_name'])")
git clone --depth 1 --branch "$TAG" https://github.com/lbiz-partners/lbiz-labor-docs-bot ~/nomu-tool
cd ~/nomu-tool && sha256sum -c MANIFEST.txt
python3 -m unittest discover -s tests
```
필요한 것: python-docx, node 18+, (PDF용) LibreOffice와 Noto Sans CJK KR.

## 입력 키 메모(임금대장)
`doc` 는 `wage_ledger`. 계산은 임금명세서와 같은 엔진이다(4대보험·소득세·`insuranceMonth`·연도별 요율표를 따로 두지 않는다).
- `entries[]`: 근로자 한 사람·한 달. `employee.name`(성명), `employee.birth` 또는 `employee.employeeNo`(생년월일·사원번호), `employee.hiredOn`(고용 연월일), `employee.job`(종사하는 업무), `pay`(임금 계산기초·기본급), `workDays`(근로일수), `totalHours`(근로시간수), `hours`(연장·야간·휴일근로 시간수), `extraEarnings`·`inKind`(내역별 금액·현물), `otherDeductions`(공제 항목·금액).
- `groupBy`: `month`(월별, 기본) 또는 `worker`(근로자별).
- `workplace.size5plus`: false 이면 상시 4명 이하. 시행령 제27조제3항제1호에 따라 근로시간수·연장·야간·휴일근로 시간수는 비워도 된다. `hoursExempt: true` 는 사장님이 근로기준법 제63조에 해당한다고 표시한 경우(해당 여부는 판단하지 않음)에 같은 생략.
- 사용기간 30일 미만 일용(`employment.type: "daily"`, 고용 연월일부터 임금계산 끝날까지 30일 미만)은 시행령 제27조제2항에 따라 생년월일·사원번호와 계산기초를 비워도 된다.
- `roster`: 엑셀 명단 경로(`.xlsx`). `python3 -m nomudocs check 명단.xlsx` 처럼 파일을 바로 넣어도 된다. 첫 시트(또는 `명단`)가 줄, `사업장` 시트가 사업장 이름·상시 5인 이상 여부·묶음. 추가 설치 없이 읽는다. 예시: `samples/wage_ledger_roster.xlsx`. 수당 비과세 칸은 `보육` 또는 `출산`, 6세 이하 자녀 수는 `6세이하자녀수` 칸.
- 주민등록번호 칸과 계좌번호 칸은 없다. 그 열이 있으면 값은 받지 않고 서류를 만들지 않는다.

## 임금대장 근거 (2026-11-24 확인)
법제처 국가법령정보센터에서 연 현행 조문이다.

- 근로기준법 제48조. [시행 2026. 10. 8.] [법률 제21533호, 2026. 4. 7., 일부개정]
  https://www.law.go.kr/LSW/lsLinkProc.do?joNo=004800&lsNm=%EA%B7%BC%EB%A1%9C%EA%B8%B0%EC%A4%80%EB%B2%95&mode=11
- 근로기준법 시행령 제27조. [시행 2025. 10. 23.] [대통령령 제35436호, 2025. 4. 8., 일부개정]
  https://www.law.go.kr/lsLinkProc.do?joNo=002700&lsClsCd=L&lsNm=%EA%B7%BC%EB%A1%9C%EA%B8%B0%EC%A4%80%EB%B2%95+%EC%8B%9C%ED%96%89%EB%A0%B9&mode=11

제48조(임금대장 및 임금명세서) ① 사용자는 각 사업장별로 임금대장을 작성하고 임금과 가족수당 계산의 기초가 되는 사항, 임금액, 그 밖에 대통령령으로 정하는 사항을 임금을 지급할 때마다 적어야 한다. <개정 2021.5.18>

제27조(임금대장의 기재사항) ①사용자는 법 제48조제1항에 따른 임금대장에 다음 각 호의 사항을 근로자 개인별로 적어야 한다. <개정 2021.10.14, 2021.11.19>
1. 성명
2. 생년월일, 사원번호 등 근로자를 특정할 수 있는 정보
3. 고용 연월일
4. 종사하는 업무
5. 임금 및 가족수당의 계산기초가 되는 사항
6. 근로일수
7. 근로시간수
8. 연장근로, 야간근로 또는 휴일근로를 시킨 경우에는 그 시간수
9. 기본급, 수당, 그 밖의 임금의 내역별 금액(통화 외의 것으로 지급된 임금이 있는 경우에는 그 품명 및 수량과 평가총액)
10. 법 제43조제1항 단서에 따라 임금의 일부를 공제한 경우에는 그 금액
②사용기간이 30일 미만인 일용근로자에 대해서는 제1항제2호 및 제5호의 사항을 적지 않을 수 있다. <개정 2021.10.14>
③다음 각 호의 어느 하나에 해당하는 근로자에 대해서는 제1항제7호 및 제8호의 사항을 적지 않을 수 있다. <개정 2021.10.14>
1. 법 제11조제2항에 따른 상시 4명 이하의 근로자를 사용하는 사업 또는 사업장의 근로자
2. 법 제63조 각 호의 어느 하나에 해당하는 근로자

현행 시행령 제2호는 생년월일·사원번호다. 주민등록번호를 적던 옛 문구는 이 시행본에 없다.

## 입력 키 메모(임금명세서)
- `insuranceMonth`(YYYY-MM): 4대보험을 몇 월분으로 떼는지. 없으면 임금계산기간의 달.
- `pay.ordinaryMonthly`: 월 통상임금(고정 수당을 넣기로 사장님이 정했을 때만).
- `incomeTax.children8to20`: 공제대상 가족 중 8세 이상 20세 이하 자녀 수(소득세법 시행령 [별표 2] 제3호). 옛 키 `childrenUnder20`도 받는다.
- `childcareChildren`: 6세 이하 자녀 수. 보육수당 비과세 한도는 1명당 월 20만원(소득세법 §12 3호 머목).
- 수당 `kind`: `meal`(식대), `car`(자가운전), `childcare`(보육수당), `birth`(출산지원금, 전액 비과세). 출산지원금은 「출생일 2년 이내·최대 2회·친족 특수관계 제외」를 확인하는 알림을 낸다.
- 근로계약서 `work.breakWaivedByWorker`: 2026-12-10부터, 근로자가 휴게를 쓰지 않겠다고 명시적으로 요청한 경우 true. 4시간 구간에서만 error 대신 warn. '4시간인 경우'의 범위는 [확인 필요].

## 판 기록
- v1.5: 2027 건강보험 요율(7.19%) 등록. 장기요양·고용보험은 입법예고 중이라 미등록. 건강보험 상·하한은 걸린 계산만 [확인 필요]. 휴게 생략 단서(근로기준법 §54①, 2026-12-10). 보육수당은 6세 이하 자녀 수 × 20만원, 출산지원금은 전액 비과세. 외국인 숙소 경고에 외국인고용법 §22의2(2027-06-10) 근거.
- v1.4: 임금대장(근로기준법 제48조제1항, 시행령 제27조). 여러 근로자·여러 달, 월별/근로자별 묶음, 엑셀 명단. 계산은 임금명세서와 같은 엔진. 상시 4명 이하는 근로시간 항목을 빼도 됨. 주민등록번호·계좌번호 칸 없음.
- v1.3: 통상임금 확인 알림, 증명서 근속기간 년·개월·일(올림 없음), 증명서 날짜가 거꾸로면 만들지 않음, 바닥글·만든 곳 표시, 2027 요율 상태 문구, 자녀 공제 「8세 이상 20세 이하」.
- v1.2: 임금명세서 연도 기준(소득세 = 지급일, 4대보험 = 몇 월분).

## 남은 일
- 2027 최저임금(시급 10,700원·월 2,236,300원, 고용노동부고시 제2026-60호)은 반영함(2026-11-09). 2027 국민연금 요율(근로자 5.00%, 법률 제20903호 부칙 제4조)도 반영함(v1.2).
- 남은 것: 2027 장기요양·고용보험 요율(입법예고, 시행령 공포 전), 2027 건강보험 월 보험료 상·하한 고시, 2027.7월분부터의 국민연금 상·하한, 2027 간이세액표 개정 여부 — 원문 확인 뒤 추가([확인 필요]). 2027 건강보험 요율(1만분의 719)은 v1.5에서 등록함.
- 임금명세서 연도 기준(v1.2): 소득세·지방소득세는 지급일, 4대보험은 몇 월분 보험료인지. 자세한 근거는 RATES_CHECK.md 「엔진 보정」 5번.
- 외국인 농·축·어업용 별지 제6호의2서식.
- 근로기준법 §60·§61 개정(2026-12-10, 2027-06-10 시행) 반영 시 연차 문구 점검.
