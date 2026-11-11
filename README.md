# 노무 서류 도우미

사장님이 입력한 내용으로 근로계약서·증명서·임금명세서를 **채우고, 계산하고, 빈칸을 점검**하는 도구. 판단·대리 작성·상담은 하지 않는다(공인노무사법 업무 영역과 선 긋기).

만든 곳: **엘비즈파트너스**. 저작권·라이선스·원본 계산 엔진 출처는 [NOTICE.md](NOTICE.md).

## 구조
```
nomudocs/            파이썬 패키지
  checks.py          점검(§17 빈칸, 최저임금, 통상임금 확인 알림, 휴게·근로시간, 주휴·공휴일, 연소자, 외국인, 증명서, 명세서, 독소조항, 민감정보)
  calc.py            node 계산 엔진 호출
  generate.py        점검 → DOCX → PDF → PNG, 점검결과.json
  docs/              서류별 양식(contract, foreign, certificates, payslip)
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

## 입력 키 메모(임금명세서)
- `insuranceMonth`(YYYY-MM): 4대보험을 몇 월분으로 떼는지. 없으면 임금계산기간의 달.
- `pay.ordinaryMonthly`: 월 통상임금(고정 수당을 넣기로 사장님이 정했을 때만).
- `incomeTax.children8to20`: 공제대상 가족 중 8세 이상 20세 이하 자녀 수(소득세법 시행령 [별표 2] 제3호). 옛 키 `childrenUnder20`도 받는다.

## 판 기록
- v1.3: 통상임금 확인 알림, 증명서 근속기간 년·개월·일(올림 없음), 증명서 날짜가 거꾸로면 만들지 않음, 바닥글·만든 곳 표시, 2027 요율 상태 문구, 자녀 공제 「8세 이상 20세 이하」.
- v1.2: 임금명세서 연도 기준(소득세 = 지급일, 4대보험 = 몇 월분).

## 남은 일
- 2027 최저임금(시급 10,700원·월 2,236,300원, 고용노동부고시 제2026-60호)은 반영함(2026-11-09). 2027 국민연금 요율(근로자 5.00%, 법률 제20903호 부칙 제4조)도 반영함(v1.2).
- 남은 것: 2027 건강보험·장기요양·고용보험 요율 등록(시행령 공포본 확인 뒤), 2027.7월분부터의 국민연금 상·하한, 2027 간이세액표 개정 여부 — 원문 확인 뒤 추가([확인 필요]).
- 임금명세서 연도 기준(v1.2): 소득세·지방소득세는 지급일, 4대보험은 몇 월분 보험료인지. 자세한 근거는 RATES_CHECK.md 「엔진 보정」 5번.
- 외국인 농·축·어업용 별지 제6호의2서식.
- 근로기준법 §60·§61 개정(2026-12-10, 2027-06-10 시행) 반영 시 연차 문구 점검.
