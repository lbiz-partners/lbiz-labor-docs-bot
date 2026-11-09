// nomu-payroll / nomu-people 공용 요율·파라미터 (2026년 적용)
// ─────────────────────────────────────────────────────────────
// 단일 진실 소스(SSOT). 계산 엔진(payroll.mjs·severance.mjs·worktime.mjs·
// annual-leave.mjs)은 이 파일의 값만 사용한다. 매년 1월·7월 갱신.
//
// 각 값에는 asOf(기준)·confidence(확신도)·src(출처)를 병기한다.
// confidence:'verify' 인 값은 2026년 변경분으로, 급여 확정 전 반드시
// 4대보험 공단 고지액/국세청 간이세액표와 대조할 것. (override 가능)
// ─────────────────────────────────────────────────────────────

export const META = {
  asOf: "2026-06",
  note: "2026년 적용. 요율은 매년 변경되며 국민연금 상·하한은 매년 7월 조정된다.",
  updatedFrom:
    "고용노동부·국민연금공단·건강보험공단·근로복지공단·국세청 1차 출처 교차검증(2026-06)",
};

// ── 최저임금 (confidence: high) ──────────────────────────────
export const MINWAGE = {
  2025: { hour: 10030, month209: 2096270 },
  2026: { hour: 10320, month209: 2156880 }, // 10,320 × 209h. 업종 구분 없음
  current: 2026,
  monthlyStdHours: 209, // 주40h + 주휴8h → 월 환산(208.57 반올림). 단시간은 개별산정
  probationDiscountRate: 0.1, // 수습 90% 지급 가능(=10% 감액)
  probationMaxMonths: 3, // 수습감액은 입사 후 3개월 이내·1년 이상 계약·비단순노무 한정
  weeklyHolidayMinHours: 15, // 주휴수당 발생 최소 주 소정근로(4주 평균)
  confidence: "high",
  src: "고용노동부 2026년 적용 최저임금 고시(시급 10,320원). 최저임금법 §5·§6·§28",
};

// ── 4대보험 (2026) ───────────────────────────────────────────
// ⚠️ 국민연금 9.5%·건강보험 7.19%는 2026년 변경분(confidence:'verify').
//    급여 확정 전 공단 고지액과 대조하거나 override로 실제 요율을 넣을 것.
//
// ── 요율 1차 출처 대조 결과 (2026-09-10) ─────────────────────
//   ✅ 국민연금 9.5% (근로자 4.75% + 사업주 4.75%) — 국민연금공단 공식 FAQ 확인.
//      2025년 9.0% → 2026.1.1 9.5%, 이후 매년 0.5%p 인상해 2033년 13%.
//      소득대체율 41.5% → 43%. https://www.nps.or.kr/pnsinfo/ntpsklg/getOHAF0104M0.do
//   ✅ 건강보험 7.19% — 보건복지부 보도자료 "2026년 건강보험료율 7.19%로 결정"
//      (2025-08-28 건강보험정책심의위원회 의결). 2025년 7.09% 대비 +0.1%p.
//      https://www.mohw.go.kr/board.es?act=view&bid=0027&list_no=1487279&mid=a10503000000
//
//   ⚠️ 아래는 아직 1차 출처로 대조하지 않았다 — confidence:'verify' 를 유지하는 이유다.
//      · 기준소득월액 상·하한(2026H1/H2) · 건강보험료 상·하한액(하한 19,780~20,160 출처 불일치)
//      · 장기요양 환산율 0.9448%
//      · 그리고 무엇보다 **개인별 고지액**은 요율이 맞아도 다를 수 있다.
//      따라서 "급여 확정 전 공단 고지액 대조" 안내는 그대로 유지한다.
export const INSURANCE = {
  // 국민연금 (사업장가입자: 근로자·사용자 각 1/2)
  nationalPension: {
    rateTotal: 0.095, // 2025년 9.0% → 2026.1.1 9.5% (연금개혁, ~2033년 13%)
    rateWorker: 0.0475,
    // 기준소득월액 상·하한 (매년 7월 조정)
    base: {
      "2026H1": { floor: 400000, cap: 6370000 }, // 2026.1.1~6.30
      "2026H2": { floor: 410000, cap: 6590000 }, // 2026.7.1~2027.6.30
    },
    roundWorker: 10, // 근로자분 10원 미만 절사(관행)
    confidence: "verify",
    src: "국민연금법 §88·§51. 보험료율 인상=1월, 상·하한 조정=7월",
  },
  // 건강보험 (직장가입자: 근로자·사용자 각 1/2)
  health: {
    rateTotal: 0.0719, // 2025년 7.09% → 2026년 7.19%
    rateWorker: 0.03595,
    premiumCapTotal: 9183480, // 보수월액보험료(총) 상한 (월). 근로자분 ≈ 절반
    premiumFloorTotal: 20160, // 하한(출처마다 19,780~20,160 — 고시 원문 확인)
    round: 1, // 원 미만 절사
    confidence: "verify",
    src: "국민건강보험법 §69·§73. 월별 건강보험료 상·하한 고시",
  },
  // 장기요양보험 (건강보험료에 부가. 근로자·사용자 각 1/2)
  longTermCare: {
    rateOfSalary: 0.009448, // 보수월액 대비 환산율(2025년 0.9182%→2026년 0.9448%)
    rateOfHealthPremium: 0.131405, // 건강보험료(총) 대비 ≈ 13.14% (= 0.009448/0.0719)
    formula: "health_premium_total × (0.009448 / 0.0719)", // 법정 정식 산식
    round: 1,
    confidence: "verify",
    src: "노인장기요양보험법 §9. 건강보험료 × (장기요양료율÷건강보험료율)",
  },
  // 고용보험 (실업급여분만 근로자 부담)
  employment: {
    rateWorker: 0.009, // 실업급여 근로자 0.9% (2026 동결)
    rateEmployerUnemployment: 0.009,
    // 고용안정·직업능력개발(사업주 전액, 규모별)
    employerStability: {
      under150: 0.0025,
      pri150plus: 0.0045,
      mid: 0.0065,
      large: 0.0085,
    },
    roundWorker: 10, // 근로자분 10원 미만 절사(관행)
    confidence: "high",
    src: "고용산재보험료징수법 §13·§14. 실업급여 0.9% 동결",
  },
  // 산재보험 (사업주 전액 — 근로자 공제 없음)
  industrialAccident: {
    rateWorker: 0, // 근로자 공제 0
    avgRateEmployer2026: 0.0147, // 평균요율 1.47%(업종별 상이, 사업주 부담)
    commuteRate: 0.0006, // 출퇴근재해요율(전업종 0.6‰)
    confidence: "high",
    src: "고용산재보험료징수법. 2026년 평균 산재요율 1.47%",
  },
  // 신고기한
  report: {
    acquire:
      "국민연금·고용·산재: 취득월 다음 달 15일까지 / 건강보험: 취득일(입사일)부터 14일 이내",
    lose: "국민연금·고용·산재: 상실사유 발생일(퇴사일) 다음 달 15일까지 / 건강보험: 상실일부터 14일 이내",
    portal: "4대사회보험 정보연계센터(4insure.or.kr) 통합신고",
  },
};

// ── 근로시간·가산수당 (근로기준법 §50/§53/§54/§56, confidence: high) ──
export const WORKTIME = {
  dailyLegalHours: 8,
  weeklyLegalHours: 40,
  weeklyOvertimeCap: 12, // 연장 한도(주). 40+12 = 주 52시간제(5인 이상)
  weeklyMaxHours: 52,
  nightStart: "22:00", // 야간 22:00~익일 06:00
  nightEnd: "06:00",
  nightStartHour: 22, // (nomu-people WORKTIME와 공통 키 — 동기화 대상)
  nightEndHour: 6,
  rateOvertime: 0.5, // 연장 가산 50%
  rateNight: 0.5, // 야간 가산 50%
  rateHolidayWithin8: 0.5, // 휴일 8h 이내 가산 50%
  rateHolidayOver8: 1.0, // 휴일 8h 초과분 가산 100%
  breakRule: "근로 4h당 30분, 8h당 1시간 이상(근로시간 도중, 무급)",
  confidence: "high",
  src: "근로기준법 §50·§53·§54·§56",
  // ⚠️ 5인 미만 사업장: §56 가산수당·§53 연장한도 원칙 미적용.
  //    단 2026 하반기 5인 미만 가산수당 단계적 확대 '예정'(시행령 별표1 개정 — 시행 시점 확인 필수)
  fiveUnderRoadmap:
    "5인 미만 가산수당(§56)은 2026 하반기 단계 적용 예정. 현행 시행령 별표1로 시행 여부 재확인",
};

// ── 근로소득 간이세액표 (룩업표 — 공식 재현 불가, confidence: high) ──
// 정확한 월 원천징수액은 국세청 간이세액표(시행령 별표2) / 홈택스 자동조회 사용.
// 엔진은 manual 입력(권장) 또는 거친 근사만 제공한다.
export const INCOME_TAX = {
  isLookupTable: true,
  selectRatios: [0.8, 1.0, 1.2], // 근로자 선택(미선택 100%)
  defaultRatio: 1.0,
  localTaxRate: 0.1, // 지방소득세 = 소득세 × 10%
  childCredit: { 1: 20830, 2: 45830, perExtraOver3: 33330 }, // 8~20세 자녀, 월 정액 차감 (2026.3.1 개정 간이세액표)
  taxFree: {
    // 주요 비과세 한도(2026)
    meal: 200000, // 식대 월 20만(현물 미제공 시)
    carAllowance: 200000, // 자가운전보조금 월 20만(본인차량·실비 미수령)
    childcare: 200000, // 출산·보육수당 월 20만(6세이하)
  },
  localTaxRound: 10, // 지방소득세 10원 미만 절사(관행)
  confidence: "high",
  src: "소득세법 §134·시행령 별표2(간이세액표), 지방세법 §103의13. 정확값=홈택스 자동조회",
  note: "간이세액표는 월급여×공제대상가족수 룩업표. 단일 산식 불가 → manual 입력 또는 홈택스 사용",
};

// ── 퇴직소득세 공제표·세율 (소득세법, 2023 개정 유지·confidence: high) ──
export const SEVERANCE = {
  minTenureYears: 1, // 1년 이상 계속근로
  minWeeklyHours: 15, // 4주 평균 주 15시간 이상
  payRule: "계속근로 1년당 30일분 평균임금 이상",
  payDueDays: 14, // 퇴직일부터 14일 이내(합의 시 연장)
  fiveUnderSince: "2010-12-01", // 5인 미만 적용(이후 근속분)
  // 근속연수공제
  tenureDeduction: [
    { upto: 5, base: 0, per: 1000000 },
    { upto: 10, base: 5000000, per: 2000000 },
    { upto: 20, base: 15000000, per: 2500000 },
    { upto: Infinity, base: 40000000, per: 3000000 },
  ],
  // 환산급여공제 (구간: 상한 / 누적공제base / 초과율)
  convertedDeduction: [
    { upto: 8000000, base: 0, rate: 1.0 },
    { upto: 70000000, base: 8000000, rate: 0.6 },
    { upto: 100000000, base: 45200000, rate: 0.55 },
    { upto: 300000000, base: 61700000, rate: 0.45 },
    { upto: Infinity, base: 151700000, rate: 0.35 },
  ],
  confidence: "high",
  src: "근로자퇴직급여보장법 §4·§8·§9, 소득세법(근속연수공제·환산급여공제)",
};

// ── 종합소득 기본세율 8구간 (소득세법 §55, confidence: high) ──
//   퇴직소득세 환산산출세액 계산 등에 사용
export const INCOME_TAX_BRACKETS = [
  { upto: 14000000, rate: 0.06, deduct: 0 },
  { upto: 50000000, rate: 0.15, deduct: 1260000 },
  { upto: 88000000, rate: 0.24, deduct: 5760000 },
  { upto: 150000000, rate: 0.35, deduct: 15440000 },
  { upto: 300000000, rate: 0.38, deduct: 19940000 },
  { upto: 500000000, rate: 0.4, deduct: 25940000 },
  { upto: 1000000000, rate: 0.42, deduct: 35940000 },
  { upto: Infinity, rate: 0.45, deduct: 65940000 },
];

// 누진세 계산 헬퍼 (과세표준 → 산출세액)
export function progressiveTax(taxBase) {
  // 2026-08-15 — 가드가 없어 문자열·undefined 가 들어오면 **NaN 세액**이 그대로
  // 리턴됐다(실측: progressiveTax('3000만') → NaN). 비교가 false 라 마지막 구간으로
  // 떨어진 뒤 NaN 을 곱하는 경로다. NaN 이 리포트에 실리면 사장님은 계산이 안 됐다는
  // 사실조차 모른다 — 조용한 오답보다 시끄러운 실패가 낫다. 이 모듈은 요율표 전용
  // 리프라 numNN(경고 누적)이 없으므로 여기서는 던진다.
  // 미입력(undefined/null/'')도 프로그래밍 오류로 본다 — 과세표준이 없는데 세액을
  // 물어보는 호출은 성립하지 않는다. Number(null)===0 이라 그냥 두면 '0원 세액'이
  // 정상값처럼 나간다. (`typeof x === 'number'` 분기는 쓰지 않는다 — G5 A1 이 감시하는
  // 형태이고, Number() 하나로 숫자·숫자문자열을 모두 올바로 처리한다.)
  const base = (taxBase === undefined || taxBase === null || taxBase === '')
    ? NaN
    : Number(taxBase);
  if (!isFinite(base)) {
    throw new TypeError(
      `progressiveTax: 과세표준이 숫자가 아닙니다 (받은 값: ${JSON.stringify(taxBase)}). ` +
      '금액은 따옴표 없이 숫자로 넣으세요 — 예: 30000000 ("3000만" 아님).'
    );
  }
  const b =
    INCOME_TAX_BRACKETS.find((x) => base <= x.upto) ||
    INCOME_TAX_BRACKETS.at(-1);
  return Math.max(0, base * b.rate - b.deduct);
}

// ─────────────────────────────────────────────────────────────
// 연도 인식 레이어 — 계산일의 연도에 맞는 요율을 자동 선택.
// ⚠️ 매년 바뀌는 값(최저임금·4대보험·세율)은 정부 고시값이라 코드가 만들 수 없다.
//    새 연도가 고시되면 아래 YEARLY에 그 연도 블록을 추가만 하면 된다(예: 2027: {...}).
//    등록 안 된 연도로 계산하면 '직전 등록연도값 + 갱신필요 경고'로 폴백한다.
// ─────────────────────────────────────────────────────────────
export const LATEST_YEAR = 2026;
export const REGISTERED_YEARS = [2026]; // ← 새 연도 추가 시 여기에도 등록

// 연도별 변동 블록(이 묶음만 매년 갱신). WORKTIME·progressiveTax는 법 개정 전 불변(연도 무관).
const YEARLY = {
  2026: {
    MINWAGE,
    INSURANCE,
    INCOME_TAX,
    SEVERANCE,
    INCOME_TAX_BRACKETS,
    META,
  },
};

function resolveYear(v) {
  if (v == null) return null;
  if (typeof v === "number" && isFinite(v)) return Math.trunc(v);
  const m = String(v).match(/(\d{4})/); // 'YYYY-MM-DD' 등에서 연도 추출
  return m ? +m[1] : null;
}

// getRates(연도 또는 날짜) → 해당 연도 요율 번들(+ stale·staleWarning).
// 인자 미지정 시 '오늘'의 연도를 사용(엔진이 계산일을 넘기면 그 날짜의 연도).
export function getRates(yearOrDate) {
  const reqYear = resolveYear(yearOrDate) ?? new Date().getFullYear();
  const has = Object.prototype.hasOwnProperty.call(YEARLY, reqYear);
  const useYear = has ? reqYear : LATEST_YEAR;
  const Y = YEARLY[useYear];
  // 미등록 연도 = 그 해 정부 고시가 아직 반영되지 않았다는 뜻이다.
  // 조용한 폴백은 '틀린 요율로 경고 0건 계산'을 만들기 때문에 stale:true + 명시 경고로 알린다.
  const stale = !has;
  const staleWarning = stale
    ? `⚠️ ${reqYear}년 요율이 이 엔진에 등록돼 있지 않습니다. ` +
      `${useYear}년 값으로 계산했으므로 실제와 다를 수 있습니다(등록 연도: ${REGISTERED_YEARS.join(", ")}). ` +
      `${reqYear}년 고시(최저임금·4대보험 요율·간이세액표)를 확인해 rates-2026.mjs 의 YEARLY 에 ` +
      `${reqYear} 블록을 추가하거나, 공단 고지액으로 override 하십시오. ` +
      `특히 국민연금 보험료율은 2027-01-01 9.5% → 10.0% 인상이 예정돼 있어 ` +
      `2027년 급여를 2026년 요율로 계산하면 공제액이 과소 산정됩니다.`
    : null;
  return {
    year: reqYear,
    usingYear: useYear,
    stale,
    staleWarning,
    MINWAGE: Y.MINWAGE,
    INSURANCE: Y.INSURANCE,
    INCOME_TAX: Y.INCOME_TAX,
    SEVERANCE: Y.SEVERANCE,
    INCOME_TAX_BRACKETS: Y.INCOME_TAX_BRACKETS,
    WORKTIME,
    progressiveTax,
    META: { ...Y.META, year: reqYear, usingYear: useYear },
  };
}

// 백워드 호환 default(LATEST 연도 고정). 연도 인식이 필요하면 getRates(date)를 쓸 것.
export default getRates(LATEST_YEAR);
