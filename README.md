# 노무 서류 도우미 — 설계와 사용법

사장님이 입력한 내용으로 근로계약서·증명서·임금명세서를 **채우고, 계산하고, 빈칸을 점검**하는 도구. 판단·대리 작성·상담은 하지 않는다(공인노무사법 업무 영역과 선 긋기).

## 구조
```
build/
  nomudocs/            파이썬 패키지
    checks.py          점검(§17 빈칸, 최저임금, 휴게·근로시간, 주휴·공휴일, 연소자, 외국인, 증명서, 명세서, 독소조항, 민감정보)
    calc.py            node 계산 엔진 호출
    generate.py        점검 → DOCX → PDF → PNG, 점검결과.json
    docs/              서류별 양식(contract, foreign, certificates, payslip)
    docx_builder.py    A4·표·글꼴(맑은 고딕 → Noto Sans CJK KR로 대체 렌더)
    render.py          LibreOffice(DOCX→PDF), pdftoppm(PDF→PNG)
  engine/calc.mjs      원본 .mjs 엔진 브리지(보정 2건)
  engine/vendor/       원본 엔진 사본(수정 없음)
  render/fonts.conf    한글 글꼴 대체 설정(FONTCONFIG_FILE로만 적용, 시스템 설정 안 건드림)
  samples/             서류별 예시 입력(가짜 값) = 입력 형식 견본
  out/                 예시 산출물(DOCX·PDF·PNG·점검결과)
  tests/               자동 시험(unittest 31개)
  skills/              스킬 초안 2개
  BOT_INSTRUCTIONS.md  봇 지시문 초안
  RATES_CHECK.md       2026 기준값 교차확인표
  OTHER_DOCS.md        다른 서류 포함 제안
```

## 사용
```
python3 -m nomudocs check samples/contract_regular.json
python3 -m nomudocs make  samples/contract_regular.json out/contract_regular
python3 make_samples.py                      # 예시 9개 전부
python3 -m unittest discover -s tests -v     # 시험
```
필요: Python 3.10+, python-docx, node 18+, (PDF용) LibreOffice + Noto Sans CJK KR, poppler-utils.

## 설계 원칙
- 입력은 사장님 말 그대로, 값 지어내기 없음. 빈칸은 빈칸으로 출력하고 점검에서 알린다.
- 주민번호 전체·비밀번호가 입력에 있으면 서류를 만들지 않는다(`Blocked`).
- 서류마다 바닥글: "이 서류는 사업주가 직접 입력한 내용으로 만든 양식입니다(2026년 기준 · 2027년 최저임금 반영). 내용 확인과 교부 책임은 사업주에게 있습니다."
- 계산은 원본 엔진 그대로 + 브리지 보정. 점검 문장에는 조문 근거를 붙인다.

## 설치
```
git clone --depth 1 --branch v1 https://github.com/lbiz-partners/lbiz-labor-docs-bot ~/nomu-tool
cd ~/nomu-tool && sha256sum -c MANIFEST.txt
python3 -m unittest discover -s tests
```
필요한 것: python-docx, node 18+, (PDF용) LibreOffice와 Noto Sans CJK KR.

## 남은 일
- 2027 최저임금(시급 10,700원·월 2,236,300원, 고용노동부고시 제2026-60호)은 반영함(2026-11-09). 남은 것: 2027-01-01 전에 2027 4대보험(국민연금 10.0%·상하한, 건강보험 요율 등)·간이세액표 값 추가.
- 외국인 농·축·어업용 별지 제6호의2서식.
- 근로기준법 §60·§61 개정(2026-12-10, 2027-06-10 시행) 반영 시 연차 문구 점검.
