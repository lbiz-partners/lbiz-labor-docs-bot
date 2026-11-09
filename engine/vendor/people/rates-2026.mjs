// nomu-people 요율·규칙 (2026년 적용)
// ─────────────────────────────────────────────────────────────
// worktime.mjs(근로시간)·annual-leave.mjs(연차) 계산의 단일 소스.
// ⚠️ nomu-payroll/assets/rates-2026.mjs 와 공통값(MINWAGE·WORKTIME)을
//    공유한다. 갱신 시 양쪽을 함께 동기화할 것.
// ─────────────────────────────────────────────────────────────

export const META = { asOf: '2026-06', sync: 'nomu-payroll/assets/rates-2026.mjs 와 동기화' };

// 최저임금 (통상임금·주휴 산정 보조)
export const MINWAGE = {
  current: 2026,
  2026: { hour: 10320, month209: 2156880 },
  2025: { hour: 10030, month209: 2096270 },
  monthlyStdHours: 209,
  weeklyHolidayMinHours: 15,  // 주휴·연차 발생 최소(4주 평균 주 소정근로)
  // ▼ nomu-payroll/rates-2026.mjs MINWAGE와 공통(동기화 대상)
  probationDiscountRate: 0.10, // 수습 90% 지급 가능
  probationMaxMonths: 3,       // 1년↑계약·3개월내·비단순노무 한정
  confidence: 'high',
  src: '고용노동부 2026년 적용 최저임금 고시(시급 10,320원)',
};

// 근로시간·가산 (근로기준법 §50/§53/§54/§56)
export const WORKTIME = {
  dailyLegalHours: 8,
  weeklyLegalHours: 40,
  weeklyOvertimeCap: 12,
  weeklyMaxHours: 52,
  nightStartHour: 22,           // 22:00
  nightEndHour: 6,              // 익일 06:00
  rateOvertime: 0.5,
  rateNight: 0.5,
  rateHolidayWithin8: 0.5,
  rateHolidayOver8: 1.0,
  // 법정 휴게: 4h당 30분, 8h당 60분
  breakMinutes: (workMinutes) => workMinutes >= 480 ? 60 : (workMinutes >= 240 ? 30 : 0),
  confidence: 'high',
  src: '근로기준법 §50·§53·§54·§56',
  fiveUnderRoadmap: '5인 미만 §56 가산수당·§53 연장한도 원칙 미적용. 2026 하반기 가산수당 단계 확대 예정 — 시행령 별표1 시행 여부 확인',
};

// 연차유급휴가 (근로기준법 §60·§61)
export const ANNUAL_LEAVE = {
  baseDays: 15,                 // 1년 80%↑ 출근 시
  under1yMonthly: 1,            // 1년 미만 개근 1개월당 1일
  under1yMax: 11,
  bonusPer2yrs: 1,              // 3년↑ 매 2년 +1일
  maxDays: 25,                  // 상한(21년차 도달)
  attendanceThreshold: 0.8,     // 80% 출근율
  expireYears: 1,               // 발생일로부터 1년 미사용 시 소멸
  fiveUnderApplies: false,      // 5인 미만 적용 제외(§60·§61)
  // 사용촉진(§61) 시점
  promotion: {
    over1y: { first: '소멸 6개월 전 기준 10일 이내 미사용일수 통지·시기지정 촉구', second: '미지정 시 소멸 2개월 전까지 사용자 시기지정 통보' },
    under1y: { first: '최초 1년 끝나기 3개월 전 기준 10일 이내 촉구', second: '미지정 시 1개월 전까지 시기지정 통보', lastMonth: '추가발생분은 1개월 전 기준 5일 이내 촉구 → 10일 전까지 시기지정' },
  },
  confidence: 'high',
  src: '근로기준법 §60(연차)·§61(사용촉진). 미사용수당=1일 통상임금×미사용일수',
  note: '회계연도 기준 부여 가능하나 퇴직 시 입사일 기준과 비교해 불리하지 않게 정산 필수',
};

// ─────────────────────────────────────────────────────────────
// 연도 인식 레이어 — 계산일 연도에 맞춰 동작. WORKTIME(가산율 §56)·ANNUAL_LEAVE
// (연차 발생규칙 §60)는 법 개정 전 불변(연도 무관)이라 공통으로 둔다. 연도별로
// 바뀌는 건 MINWAGE(통상임금·주휴 환산 보조값)뿐. 새 연도는 YEARLY에 추가.
// 등록 안 된 연도로 계산하면 '직전값 + 갱신필요 경고'로 폴백한다.
// ─────────────────────────────────────────────────────────────
export const LATEST_YEAR = 2026;
export const REGISTERED_YEARS = [2026];   // ← 새 연도 추가 시 등록

const YEARLY = { 2026: { MINWAGE, META } };

function resolveYear(v) {
  if (v == null) return null;
  if (typeof v === 'number' && isFinite(v)) return Math.trunc(v);
  const m = String(v).match(/(\d{4})/);
  return m ? +m[1] : null;
}

export function getRates(yearOrDate) {
  const reqYear = resolveYear(yearOrDate) ?? new Date().getFullYear();
  const has = Object.prototype.hasOwnProperty.call(YEARLY, reqYear);
  const useYear = has ? reqYear : LATEST_YEAR;
  const Y = YEARLY[useYear];
  // 미등록 연도 = 그 해 정부 고시가 아직 반영되지 않았다는 뜻이다.
  // 조용한 폴백은 '틀린 최저임금으로 경고 0건 계산'을 만들기 때문에 stale:true + 명시 경고로 알린다.
  const stale = !has;
  const staleWarning = stale
    ? `⚠️ ${reqYear}년 값이 이 엔진에 등록돼 있지 않습니다. ` +
      `${useYear}년 최저임금(시급 ${Y.MINWAGE[useYear]?.hour?.toLocaleString() ?? '-'}원)으로 계산했으므로 ` +
      `실제와 다를 수 있습니다(등록 연도: ${REGISTERED_YEARS.join(', ')}). ` +
      `${reqYear}년 최저임금 고시를 확인해 rates-2026.mjs 의 MINWAGE·YEARLY 에 ${reqYear} 블록을 추가하십시오. ` +
      `통상임금·주휴수당·연차미사용수당 환산액이 과소 산정될 수 있습니다.`
    : null;
  return {
    year: reqYear, usingYear: useYear, stale, staleWarning,
    MINWAGE: Y.MINWAGE, WORKTIME, ANNUAL_LEAVE,
    META: { ...Y.META, year: reqYear, usingYear: useYear },
  };
}

export default getRates(LATEST_YEAR);
