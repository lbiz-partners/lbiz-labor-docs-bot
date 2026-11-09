// 급여 계산 엔진 — 월 급여 → 4대보험·소득세 공제 → 실수령액
// 근거: 근로기준법 §56(가산수당), 4대보험 각 법, 소득세법(간이세액표)
// 요율은 rates-2026.mjs 단일 소스 사용. node 정확계산용.
//
// 사용:
//   import { calcPayroll } from './payroll.mjs';
//   const r = calcPayroll(input);
//   node payroll.mjs <input.json>   (CLI: 결과 JSON + 요약표 출력)
//
// 입력(input):
// {
//   baseSalary: 2400000,            // 월 기본급(원)
//   ordinaryMonthly: 2400000,       // 월 통상임금(가산수당 산정 기준). 미지정 시 baseSalary
//   ordinaryHours: 209,             // 통상임금 산정기준시간(주40h=209). 시급 환산 분모
//   taxableAllowance: 0,            // 과세 제수당 합계(직책·자격 등)
//   bonus: 0,                       // 상여(당월 지급분, 과세)
//   mealAllowance: 0,               // 식대(월 20만까지 비과세)
//   carAllowance: 0,                // 자가운전보조금(월 20만까지 비과세)
//   childcareAllowance: 0,          // 출산·보육수당(월 20만까지 비과세)
//   otherTaxFree: 0,                // 기타 비과세
//   overtimeHours: 0,               // 연장근로시간(평일 8h 초과)
//   nightHours: 0,                  // 야간(22~06) 겹친 시간
//   holidayHoursWithin8: 0,         // 휴일근로 8h 이내
//   holidayHoursOver8: 0,           // 휴일근로 8h 초과
//   fiveUnder: false,               // 상시 5인 미만 → 가산수당 0(§56 미적용, 로드맵 주의)
//   otherDeductions: 0,             // 기타공제(노조비·가불 등)
//   employerSize: 'under150',       // 고용보험 사업주분 구간(근로자분과 무관)
//   pensionPeriod: '2026H2',        // 국민연금 상·하한 적용기(2026H1/2026H2)
//   incomeTax: {                    // 소득세 산정 방식
//     mode: 'table',                // 'table'(기본·간이세액표 자동조회)|'manual'|'approx'|'none'
//     family: 1,                    // mode:table/approx — 공제대상 가족 수(본인 포함, 1~11)
//     manualTax: 0,                 // mode:manual — 홈택스/간이세액표 조회값(월 소득세)
//     childrenUnder20: 0,           // 8~20세 자녀 수(자녀공제)
//     selectRatio: 1.0,             // 80/100/120% 선택(0.8/1.0/1.2)
//   },
//   rateOverride: { nationalPension: 0.09, health: 0.0709 }  // (선택) 실제 요율 강제
// }

import { getRates } from './rates-2026.mjs';
import { lookupWithholding, SIMPLIFIED_TAX_2026 } from './income-tax-table-2026.mjs';

// ── 입력 방어 공통 계약 (v3.4.2) ──────────────────────────────
// 결함 클래스 A(조용한 값 소실) 박멸용 공통 블록.
//   num(v, field)    숫자/숫자문자열("200000", " 200,000 ", "200000원")은 변환 + 변환 사실 경고.
//                    해석 불가(NaN·"abc"·객체)는 0 + '어떤 필드가 빠졌는지' 경고. 조용한 소실 금지.
//                    미입력(undefined/null/"")은 종전대로 조용히 0 — 정상 입력이므로 경고하지 않는다.
//   numNN(v, field)  위 + 도메인상 음수 불가 필드(임금·매출·잔고·기간)에서 음수 경고.
//   bool(v, field)   "false"/"0"/"N"/"아니오"/"없음" 등 문자열 falsy 를 올바로 해석 + 변환 경고.
//                    (기존 !! 는 fiveUnder:"false" 를 true 로 읽어 5인 미만 오판 → 가산수당 과소지급)
//   _show(v)         경고문에 '실제 입력값'을 표시. JSON.stringify(NaN)==='null' 이라 NaN 입력이
//                    값(null)로 찍혔는데 null 은 이 엔진에서 무경고 정상값이라 혼동을 유발했다.
// 엔진 자기완결(외부 import 금지) 제약상 JS 엔진 5종(payroll·severance·worktime·
// annual-leave·jaemu/engine.mjs)에 같은 계약·같은 경고문구로 복제해 둔다.
// 한 곳을 고치면 나머지 4곳도 반드시 같이 고칠 것(회귀 케이스 '5개 엔진 입력계약 동등' 이 감시한다).
let _coerceLog = [];
const _resetCoerce = () => { _coerceLog = []; };
const _drainCoerce = () => { const l = [...new Set(_coerceLog)]; _coerceLog = []; return l; };
function _show(v) {
  if (typeof v === 'number') return Number.isNaN(v) ? 'NaN' : String(v);
  if (v === undefined) return 'undefined';
  if (v === null) return 'null';
  try { const s = JSON.stringify(v); return s === undefined ? String(v) : s; } catch { return String(v); }
}
function num(v, field) {
  if (typeof v === 'number' && isFinite(v)) return v;          // 숫자 — 기존 동작 그대로
  if (v === undefined || v === null || v === '') return 0;     // 미입력 — 경고 없음
  if (typeof v === 'string') {
    const t = v.replace(/[\s,]/g, '').replace(/원$/, '');
    if (/^[+-]?(?:\d+(?:\.\d+)?|\.\d+)$/.test(t)) {
      const n = Number(t);
      if (isFinite(n)) {
        _coerceLog.push(`입력 "${field || '숫자 항목'}" 값이 문자열(${_show(v)})이라 숫자 ${n.toLocaleString('ko-KR')}(으)로 변환해 계산했습니다 — 입력 파일에서 따옴표를 빼고 숫자로 넣으세요.`);
        return n;
      }
    }
    if (/%\s*$/.test(v)) {
      // 퍼센트 표기는 필드마다 단위가 달라(비율 0.8 vs 이율 5) 자동 환산하면 새 오류를 만든다.
      _coerceLog.push(`⚠️ 입력 "${field || '숫자 항목'}" 값(${_show(v)})은 백분율 표기라 이 필드의 단위와 어긋납니다 — 0으로 처리했습니다. % 기호를 빼고 숫자로 넣으세요(비율 필드는 0.8, 이율 필드는 5).`);
      return 0;
    }
  }
  _coerceLog.push(`⚠️ 입력 "${field || '숫자 항목'}" 값(${_show(v)})을 숫자로 해석할 수 없어 0으로 처리했습니다 — 이 항목이 계산에서 빠졌으니 입력을 확인하세요.`);
  return 0;
}
function numNN(v, field) {
  const n = num(v, field);
  if (n < 0)
    _coerceLog.push(`⚠️ 입력 "${field || '숫자 항목'}" 값이 음수(${n.toLocaleString('ko-KR')})입니다 — 이 항목은 음수가 될 수 없습니다(임금·매출·잔고·기간 등). 부호를 확인하세요. 이 값으로 산출된 금액은 신뢰하지 마십시오.`);
  return n;
}
const _TRUE = ['true', '1', 'y', 'yes', '예', '네', '있음', '해당', 'o', '참'];
const _FALSE = ['false', '0', 'n', 'no', '아니오', '아니요', '없음', '미해당', '해당없음', 'x', '거짓'];
function bool(v, field) {
  if (typeof v === 'boolean') return v;                        // 불리언 — 기존 동작 그대로
  if (v === undefined || v === null || v === '') return false; // 미입력 — 경고 없음
  if (typeof v === 'number' && isFinite(v)) {
    _coerceLog.push(`입력 "${field || '예/아니오 항목'}" 값이 숫자(${v})라 ${v !== 0 ? '예(true)' : '아니오(false)'}로 해석했습니다 — true/false 로 넣으세요.`);
    return v !== 0;
  }
  if (typeof v === 'string') {
    const t = v.trim().toLowerCase();
    if (_TRUE.includes(t) || _FALSE.includes(t)) {
      const b = _TRUE.includes(t);
      _coerceLog.push(`입력 "${field || '예/아니오 항목'}" 값이 문자열(${_show(v)})이라 ${b ? '예(true)' : '아니오(false)'}로 해석했습니다 — 따옴표를 빼고 true/false 로 넣으세요.`);
      return b;
    }
  }
  _coerceLog.push(`⚠️ 입력 "${field || '예/아니오 항목'}" 값(${_show(v)})을 예/아니오로 해석할 수 없어 '아니오(false)'로 처리했습니다 — 입력을 확인하세요.`);
  return false;
}
// unit원 미만 절사. 부동소수점 오차 보정(예: 3,000,000×0.009=26999.9999→27,000)
const floorTo = (v, unit) => Math.floor((v + 1e-6) / unit) * unit;

// ── 명시적 0 존중 계약 (v3.4.4) ──────────────────────────────
// 결함 클래스: `numNN(x) || 기본값` 은 '미입력' 과 '사장님이 일부러 넣은 0' 을 구분하지 못한다
// (numNN 은 둘 다 0 을 돌려주므로 반환값으로는 판정 불가). 그래서 무보수 대표·4대보험
// 적용제외 사업장이 넣은 0 이 조용히 표준요율·기본값으로 되살아나, 넣지도 않은 보험료가 공제됐다.
// _explicitZero(v) 는 '입력 원본이 0 으로 읽히는 경우' 만 true 로 판정한다.
//   · 미입력(undefined/null/'')          → false : 종전대로 기본값 폴백, 경고 없음
//   · 해석 불가("abc"·객체·NaN)          → false : 종전대로 기본값 폴백 + numNN 이 경고
//   · 0 / "0" / " 0 원" / 0.0 / "+0.00"  → true  : 존중하거나, 대체한다면 반드시 고지
const _blank = (v) => v === undefined || v === null || v === '';
function _explicitZero(v) {
  if (_blank(v)) return false;
  if (typeof v === 'number') return isFinite(v) && v === 0;
  if (typeof v === 'string') {
    const t = v.replace(/[\s,]/g, '').replace(/원$/, '');
    return /^[+-]?(?:0+(?:\.0*)?|\.0+)$/.test(t);
  }
  return false;
}

// ── 도메인 전용 입력 파서 ────────────────────────────────────
// 소득세 선택비율(소득세법 시행령 §194①단서) — 근로자가 80/100/120% 중 택1, 미선택 100%.
// 기존 `itIn.selectRatio || T.defaultRatio` 는 "100%" 같은 문자열을 그대로 곱해
// 소득세·지방소득세·실수령액을 전부 NaN 으로 만들었고 경고도 0건이었다.
// 법정 3값만 허용하고, 그 밖의 값은 100%로 되돌리며 반드시 경고를 남긴다(조용한 소실 금지).
function selectRatioOf(v, T) {
  const allowed = T.selectRatios || [0.8, 1.0, 1.2];
  const def = T.defaultRatio ?? 1.0;
  if (v === undefined || v === null || v === '') return def;      // 미선택 — 경고 없음
  let n = null;
  if (typeof v === 'number' && isFinite(v)) n = v;
  else if (typeof v === 'string') {
    const t = v.trim().replace(/[\s,]/g, '').replace(/%$/, '');
    if (/^\d+(?:\.\d+)?$/.test(t)) n = Number(t);
  }
  if (n != null) {
    if (n > 2) n = n / 100;                                       // 80·100·120 → 0.8·1.0·1.2
    const hit = allowed.find(a => Math.abs(a - n) < 1e-9);
    if (hit != null) {
      if (typeof v !== 'number' || v > 2)
        _coerceLog.push(`입력 "incomeTax.selectRatio" 값(${_show(v)})을 소득세 선택비율 ${Math.round(hit * 100)}%(=${hit})로 해석했습니다 — 0.8 / 1.0 / 1.2 중 하나를 숫자로 넣으세요.`);
      return hit;
    }
  }
  _coerceLog.push(`⚠️ 입력 "incomeTax.selectRatio" 값(${_show(v)})은 소득세 선택비율(80%·100%·120% = 0.8 / 1.0 / 1.2)이 아닙니다 — 기본 ${Math.round(def * 100)}%로 계산했습니다. 원천징수 선택비율을 확인하세요.`);
  return def;
}
// 공제대상 가족 수(본인 포함, 간이세액표 1~11). num() 밖이라 "가족3명" 같은 해석 불가 값이
// 조용히 1명으로 강등되어 소득세가 과다징수됐다(실측 3,000,000원 기준 월 42,410원 과다).
function famOf(v) {
  // 2026-08-16 — 미입력은 여기서 경고하지 않는다. _coerceLog 는 '입력이 강제변환됐다'는
  //   채널이고, family 미입력은 변환이 아니라 **정보 부족**이라 성격이 다르다(경고로 올리면
  //   부양가족 없는 정상 케이스에서 매번 오탐이 난다 — 회귀 4케이스가 이를 감시한다).
  //   대신 taxNote 에 '입력 없음 — 본인 1명 가정'을 실어 사장님이 되짚을 수 있게 한다.
  if (v === undefined || v === null || v === '') return 1;
  let n = null;
  if (typeof v === 'number' && isFinite(v)) n = v;
  else if (typeof v === 'string') {
    const t = v.replace(/[\s,]/g, '').replace(/명$/, '');
    if (/^\d+(?:\.\d+)?$/.test(t)) {
      n = Number(t);
      _coerceLog.push(`입력 "incomeTax.family" 값이 문자열(${_show(v)})이라 공제대상 가족 ${n}명으로 변환해 계산했습니다 — 따옴표를 빼고 숫자로 넣으세요.`);
    }
  }
  if (n == null || !isFinite(n) || n < 1) {
    _coerceLog.push(`⚠️ 입력 "incomeTax.family" 값(${_show(v)})을 공제대상 가족 수로 해석할 수 없어 1명으로 계산했습니다 — 가족 수가 실제보다 적으면 소득세가 과다 징수됩니다. 본인 포함 1~11 사이 숫자로 넣으세요.`);
    return 1;
  }
  const f = Math.floor(n);
  if (f > 11) {
    _coerceLog.push(`입력 "incomeTax.family" 값(${_show(v)})이 간이세액표 상한(11명)을 넘어 11명으로 계산했습니다.`);
    return 11;
  }
  return f;
}

// 시급제 월 급여 환산 — 소정근로 임금 + 주휴수당(근로기준법 §55)
// weeklyHours(주 소정근로), weeksPerMonth(기본 4.345=365/7/12)
export function hourlyToMonthly(hourlyWage, weeklyHours, weeksPerMonth = 365 / 7 / 12) {
  const hw = numNN(hourlyWage, 'hourlyWage'), wh = numNN(weeklyHours, 'weeklyHours');
  // 2026-08-15 — 세 번째 인자에 가드가 없어 문자열·NaN 이 오면 월 환산액이 전부 NaN 이 됐다.
  const wpm = numNN(weeksPerMonth, 'weeksPerMonth');
  const weekly = hw * wh;                                   // 주 소정근로 임금
  // 주휴수당: 4주 평균 주 15h 이상 + 개근 시. 주휴시간 = min(주소정,40)/40 × 8h
  const holidayHours = wh >= 15 ? Math.min(wh, 40) / 40 * 8 : 0;
  const weeklyHoliday = hw * holidayHours;                  // 주휴수당(주)
  return {
    hourlyWage: hw, weeklyHours: wh,
    weeklyHolidayHours: +holidayHours.toFixed(2),
    monthlyContractPay: Math.round(weekly * wpm),  // 소정근로 월 임금
    monthlyHolidayPay: Math.round(weeklyHoliday * wpm), // 주휴수당 월 환산
    monthlyBase: Math.round((weekly + weeklyHoliday) * wpm), // 합계(=기본급)
    note: wh < 15 ? '주 15시간 미만(초단시간) → 주휴수당 미발생(§18③)' : '주휴수당 포함',
  };
}

export function calcPayroll(input = {}) {
  const warn = [];
  _resetCoerce();   // 문자열→숫자 변환 기록은 이 호출분만 모은다
  // 계산일 연도 자동 인식: input.year > 지급일 > 급여기간말 > 오늘. 미등록 연도면 직전값+경고.
  const R = getRates(input.year ?? input.payDate ?? input.payPeriodEnd);
  if (R.stale) warn.push(R.staleWarning);
  // 시급제 입력(hourlyWage + weeklyHours) → 월급(소정+주휴수당) 자동 환산
  let hourly = null;
  if (numNN(input.hourlyWage, 'hourlyWage') > 0) {
    hourly = hourlyToMonthly(input.hourlyWage, input.weeklyHours);
    warn.push(`시급제 환산: 시급 ${numNN(input.hourlyWage, 'hourlyWage').toLocaleString()}원 × 주 ${numNN(input.weeklyHours, 'weeklyHours')}h → 기본급(주휴 포함) ${hourly.monthlyBase.toLocaleString()}원 (${hourly.note}).`);
  }
  // 명시적 0(v3.4.5) — 시급 0원은 시급제 환산 분기(>0)를 타지 않아 월급(baseSalary) 기준으로
  // 계산이 넘어간다. 종전엔 그 전환이 무고지라 '시급을 넣었는데 왜 0원인가' 를 알 수 없었다.
  if (_explicitZero(input.hourlyWage))
    warn.push('⚠️ 시급(hourlyWage)을 0원으로 입력했습니다 — 시급제 환산을 하지 않고 월 기본급(baseSalary) 기준으로 계산했습니다. 시급제 근로자라면 실제 시급을 입력하세요.');
  const baseSalary = hourly ? hourly.monthlyBase : numNN(input.baseSalary, 'baseSalary');
  // 통상시급: 시급제면 입력 시급, 월급제면 통상임금/소정시간
  // 명시적 0 처리(v3.4.4) — 미입력만 조용히 폴백한다.
  //  · 통상임금 0 : 존중한다(무보수 대표 등). 대신 '가산수당이 전부 0 이 된다'는 결과를 고지.
  //  · 소정근로시간 0 : 시급 환산 분모라 유효하지 않은 값 → 209 로 되돌리되 조용히 바꾸지 않고 고지.
  const ordinaryMonthlyZero = _explicitZero(input.ordinaryMonthly);
  const ordinaryMonthlyNum = numNN(input.ordinaryMonthly, 'ordinaryMonthly');
  const ordinaryMonthly = ordinaryMonthlyZero ? 0 : (ordinaryMonthlyNum || baseSalary);
  if (ordinaryMonthlyZero)
    warn.push('⚠️ 통상임금(ordinaryMonthly)을 0원으로 입력해 그대로 계산했습니다 — 통상시급이 0원이 되어 연장·야간·휴일 가산수당이 전부 0원으로 산정됩니다. 기본급을 기준으로 삼으려면 이 항목을 비워두세요.');
  const ordinaryHoursZero = _explicitZero(input.ordinaryHours);
  const ordinaryHours = numNN(input.ordinaryHours, 'ordinaryHours') || R.MINWAGE.monthlyStdHours; // 209
  if (ordinaryHoursZero)
    warn.push(`⚠️ 소정근로시간(ordinaryHours)을 0시간으로 입력했습니다 — 0시간은 통상시급을 산정할 수 없는 값이라 기본 ${R.MINWAGE.monthlyStdHours}시간(주40h 기준)으로 대체해 계산했습니다. 실제 월 소정근로시간을 입력하세요.`);
  const hourlyOrdinary = hourly ? hourly.hourlyWage : (ordinaryHours > 0 ? ordinaryMonthly / ordinaryHours : 0);
  const fiveUnder = bool(input.fiveUnder, 'fiveUnder');

  // ── 1) 법정 가산수당 (근로기준법 §56) ─────────────────────
  const W = R.WORKTIME;
  const ot  = numNN(input.overtimeHours, 'overtimeHours');
  const ni  = numNN(input.nightHours, 'nightHours');
  const h8  = numNN(input.holidayHoursWithin8, 'holidayHoursWithin8');
  const h8p = numNN(input.holidayHoursOver8, 'holidayHoursOver8');

  // 가산 배율: 연장 1.5(=1+0.5), 야간 +0.5, 휴일 8h이내 1.5, 휴일 8h초과 2.0
  // 기본 근로분(1.0)은 통상임금/월급에 이미 포함되므로 '가산분'만 별도 계산
  let overtimePay = hourlyOrdinary * ot  * (1 + W.rateOvertime);          // 연장: 1.5배 전액
  let nightPay    = hourlyOrdinary * ni  * W.rateNight;                   // 야간: 0.5 가산만(겹침)
  let holiday8Pay = hourlyOrdinary * h8  * (1 + W.rateHolidayWithin8);    // 휴일8h이내: 1.5배
  let holidayOPay = hourlyOrdinary * h8p * (1 + W.rateHolidayOver8);      // 휴일8h초과: 2.0배

  if (fiveUnder) {
    // 5인 미만: §56 가산수당 원칙 미적용 → 가산분 0, 근로분만(1.0배)
    overtimePay = hourlyOrdinary * ot;
    nightPay    = 0;
    holiday8Pay = hourlyOrdinary * h8;
    holidayOPay = hourlyOrdinary * h8p;
    if (ot + ni + h8 + h8p > 0)
      warn.push('5인 미만: §56 가산수당 미적용으로 계산(근로분 1.0배만). ⚠️ 2026 하반기 5인 미만 가산수당 단계적 확대 예정 — 시행령 별표1 현행본으로 시행 여부 확인 필요.');
  }
  const overtimeTotal = overtimePay + nightPay + holiday8Pay + holidayOPay;

  // ── 2) 총 지급액 ──────────────────────────────────────────
  const taxableAllowance = numNN(input.taxableAllowance, 'taxableAllowance');
  const bonus = numNN(input.bonus, 'bonus');
  // 비과세(한도 적용)
  const tf = R.INCOME_TAX.taxFree;
  const meal = Math.min(numNN(input.mealAllowance, 'mealAllowance'), tf.meal);
  const car  = Math.min(numNN(input.carAllowance, 'carAllowance'), tf.carAllowance);
  const care = Math.min(numNN(input.childcareAllowance, 'childcareAllowance'), tf.childcare);
  const otherTaxFree = numNN(input.otherTaxFree, 'otherTaxFree');
  if (numNN(input.mealAllowance, 'mealAllowance') > tf.meal) warn.push(`식대 비과세 한도 초과분 ${(numNN(input.mealAllowance, 'mealAllowance')-tf.meal).toLocaleString()}원은 과세소득에 포함됨(월 20만 한도).`);
  const taxFreeTotal = meal + car + care + otherTaxFree;

  const grossPay = baseSalary + overtimeTotal + taxableAllowance + bonus + taxFreeTotal;
  // 과세대상 급여(비과세 제외) — 4대보험 보수월액·소득세 기준
  const taxableGross = grossPay - taxFreeTotal;

  // ── 3) 4대보험 근로자 공제 ────────────────────────────────
  const I = R.INSURANCE;
  const ov = input.rateOverride || {};
  // 요율 오버라이드의 명시적 0 은 '적용제외 사업장' 이라는 유효한 의사표시라 존중한다(v3.4.4).
  // 종전 `numNN(...) || 표준요율` 은 0 을 표준요율로 되살려, 적용제외인데도 보험료를 공제했다.
  // 미입력·해석불가는 종전대로 표준요율 폴백(경고 없음).
  const hiRateZero = _explicitZero(ov.health);
  const eiRateZero = _explicitZero(ov.employment);
  const hiRate = hiRateZero ? 0 : (numNN(ov.health, 'rateOverride.health') || I.health.rateTotal);
  const eiRate = eiRateZero ? 0 : (numNN(ov.employment, 'rateOverride.employment') || I.employment.rateWorker);
  if (hiRateZero)
    warn.push('건강보험 요율을 0%로 지정해 건강보험료·장기요양보험료를 0원으로 처리했습니다(적용제외 사업장으로 간주) — 장기요양보험은 건강보험 가입자에게 부과되므로 함께 0원입니다. 적용제외가 아니라면 rateOverride.health 를 비워두세요.');
  if (eiRateZero)
    warn.push('고용보험 요율을 0%로 지정해 고용보험 근로자 공제를 0원으로 처리했습니다(적용제외로 간주) — 적용제외가 아니라면 rateOverride.employment 를 비워두세요.');
  let nationalPension = 0, healthInsurance = 0, longTermCare = 0, employmentInsurance = 0;
  let npPeriodUsed = null;   // 실제로 적용한 국민연금 상·하한 적용기(무급월이면 null)
  const industrialAccident = 0; // 산재: 근로자 공제 없음(사업주 전액)

  if (taxableGross <= 0) {
    // 무급월(무급휴직 등) — 보수 0이면 근로자 공제 0. 하한액으로 음수 실수령 방지.
    warn.push('과세대상 급여가 0원 — 4대보험 근로자 공제 0 처리(무급월 가정). 실제 무급휴직 시 보험료 납부예외·정산은 공단 기준 확인.');
  } else {
    // 국민연금 — 요율 0 은 적용제외로 존중(연금보험료 0원)
    const npRateZero = _explicitZero(ov.nationalPension);
    const npRate = npRateZero ? 0 : (numNN(ov.nationalPension, 'rateOverride.nationalPension') || I.nationalPension.rateTotal);
    if (npRateZero)
      warn.push('국민연금 요율을 0%로 지정해 국민연금 근로자 공제를 0원으로 처리했습니다(적용제외로 간주) — 적용제외가 아니라면 rateOverride.nationalPension 을 비워두세요.');
    // 상·하한 적용기 — pensionPeriod 미지정 시 급여일(payDate)로 자동 판정(1~6월=H1, 7~12월=H2).
    // 무조건 2026H2 폴백은 상반기 고소득자의 기준소득월액 상한을 과대 적용하는 오류(과다공제)를 냈다.
    let npPeriod = input.pensionPeriod;
    if (!npPeriod) {
      const pd = input.payDate || input.payPeriodEnd;
      const d = pd ? new Date(pd) : null;
      npPeriod = (d && !isNaN(d.getTime())) ? `${d.getFullYear()}${d.getMonth() < 6 ? 'H1' : 'H2'}` : '2026H2';
    }
    // 등록되지 않은 적용기(오타 '2026H3'·미등록 연도 '2027H1')는 종전에 조용히 2026H2 표로
    // 되살아났다 — 기준소득월액 상한이 달라 고소득자 공제액이 바뀌는데 경고가 0건이었다.
    // 폴백 '값' 은 그대로 두고(기존 동작 불변) 반드시 고지한다.
    let npBaseTable = I.nationalPension.base[npPeriod];
    if (!npBaseTable) {
      warn.push(`⚠️ 국민연금 기준소득월액 상·하한 적용기(pensionPeriod) "${npPeriod}"가 이 엔진에 등록돼 있지 않아 2026H2(2026.7.1~) 표로 계산했습니다 — 등록된 적용기: ${Object.keys(I.nationalPension.base).join(', ')}. 상반기 급여면 2026H1 을 넣으세요(상한액이 달라 고소득자 공제액이 바뀝니다).`);
      npPeriod = '2026H2';
      npBaseTable = I.nationalPension.base['2026H2'];
    }
    npPeriodUsed = npPeriod;   // 출력에는 '실제로 쓴 적용기' 를 싣는다(입력을 그대로 되뇌지 않는다)
    let npBase = floorTo(taxableGross, 1000); // 기준소득월액 1,000원 미만 절사
    npBase = Math.min(Math.max(npBase, npBaseTable.floor), npBaseTable.cap);
    nationalPension = floorTo(npBase * npRate / 2, I.nationalPension.roundWorker);
    // 건강보험
    if (hiRateZero) {
      // 요율 0(적용제외) — 하한액 클램프까지 건너뛴다. 클램프를 태우면 0%인데도 하한 보험료가
      // 붙고, 장기요양은 hiRate 가 분모라 0 나눗셈(Infinity/NaN)이 된다.
      healthInsurance = 0;
      longTermCare = 0;
    } else {
      let hiPremiumTotal = taxableGross * hiRate;
      hiPremiumTotal = Math.min(Math.max(hiPremiumTotal, I.health.premiumFloorTotal), I.health.premiumCapTotal);
      healthInsurance = floorTo(hiPremiumTotal / 2, I.health.round);
      // 장기요양보험 = 건강보험료(총) × (장기요양료율 ÷ 건강보험료율), 근로자 1/2
      longTermCare = floorTo(hiPremiumTotal * (I.longTermCare.rateOfSalary / hiRate) / 2, I.longTermCare.round);
    }
    // 고용보험(실업급여분만 근로자)
    employmentInsurance = floorTo(taxableGross * eiRate, I.employment.roundWorker);
  }

  const insuranceTotal = nationalPension + healthInsurance + longTermCare + employmentInsurance;
  // 국민연금·건강보험 2026 변경분 '공단 대조' 런타임 안내는 비활성(요청에 따라 제거).

  // ── 4) 소득세 + 지방소득세 ────────────────────────────────
  const T = R.INCOME_TAX;
  const itIn = input.incomeTax || {};
  const mode = itIn.mode || 'table';
  const family = famOf(itIn.family);   // num() 밖이라 "가족3명" 이 조용히 1명으로 강등되던 결함 교정
  let incomeTax = 0, taxNote = '';
  if (mode === 'table') {
    incomeTax = lookupWithholding(taxableGross, family, (m) => warn.push(m));
    // 8~20세 자녀 세액공제 — 간이세액표 조회액에서 정액 차감(2026.3.1 개정). table 모드도 approx와 동일 적용.
    const kids = numNN(itIn.childrenUnder20, 'incomeTax.childrenUnder20');
    if (kids > 0) {
      const cc = R.INCOME_TAX.childCredit;
      const childDeduct = kids === 1 ? cc[1] : kids === 2 ? cc[2] : cc[2] + (kids - 2) * cc.perExtraOver3;
      incomeTax = Math.max(0, incomeTax - childDeduct);
    }
    // 2026-08-16 — family 를 안 준 경우와 1 을 준 경우를 산출물에서 구분한다.
    //   `dependents` 같은 다른 이름으로 넣으면 미입력으로 취급돼 조용히 본인 1명이 되고,
    //   월급 240만 기준 소득세가 31,000 → 38,000원으로 매달 7,000원 과다 공제된다(실측).
    const _famGiven = !(itIn.family === undefined || itIn.family === null || itIn.family === '');
    taxNote = `국세청 간이세액표(${SIMPLIFIED_TAX_2026.effective} 시행) 자동조회 — 과세급여×공제대상가족 ${family}명(본인 포함${_famGiven ? '' : ' · 입력 없어 본인 1명으로 가정 — 부양가족이 있으면 소득세가 실제보다 많이 나옵니다'})(100% 기준)`
      + (kids > 0 ? `, 8~20세 자녀 ${kids}명 공제 차감` : '');
  } else if (mode === 'manual') {
    incomeTax = numNN(itIn.manualTax, 'incomeTax.manualTax');
    taxNote = '홈택스/간이세액표 조회값(manual) 사용';
  } else if (mode === 'none') {
    incomeTax = 0;
    taxNote = '소득세 미산정(별도 처리)';
  } else { // approx — 거친 근사. 정확값은 홈택스
    incomeTax = approxIncomeTax(taxableGross, itIn, R, family);
    taxNote = '⚠️ 근사값. 정확한 월 원천징수액은 국세청 간이세액표/홈택스 자동조회 사용 필수';
    warn.push('소득세는 근사 계산. 간이세액표는 룩업표라 공식 재현 불가 — 홈택스 "근로소득 간이세액표 자동조회" 값으로 대체하세요.');
  }
  const ratio = selectRatioOf(itIn.selectRatio, T);
  incomeTax = Math.round(incomeTax * ratio);
  const localIncomeTax = floorTo(incomeTax * T.localTaxRate, T.localTaxRound);

  // ── 5) 공제 합계·실수령액 ────────────────────────────────
  const otherDeductions = numNN(input.otherDeductions, 'otherDeductions');
  const totalDeductions = insuranceTotal + incomeTax + localIncomeTax + otherDeductions;
  const netPay = grossPay - totalDeductions;
  if (netPay < 0) warn.push('⚠️ 실수령액이 음수입니다 — 공제액이 지급액을 초과. 저액/무급월 보험료 부과방식·기타공제 입력을 확인하세요.');
  // 문자열 숫자 변환·해석 불가·음수 입력을 경고로 올린다(조용한 소실 금지). 숫자 입력만이면 빈 배열.
  warn.push(..._drainCoerce());
  // 최저임금 판정 — checkMinimumWage 가 자체적으로 reset/drain 하므로 위 drain 이후에 호출해야 한다.
  // 위반이면(=사장님이 반드시 알아야 하는 사실) 급여 경고로도 승격한다.
  const minimumWage = checkMinimumWage(input);
  if (minimumWage.violated) warn.push(...minimumWage.warnings.filter(w => w.startsWith('🔴')));

  return {
    // pensionPeriod 는 '실제 계산에 쓴 적용기'. 종전엔 payDate 로 2026H1 을 적용해놓고
    // 출력에는 2026H2 라고 적어, 사장님이 공제액을 검산할 근거가 어긋났다.
    input: { fiveUnder, hourlyOrdinary: Math.round(hourlyOrdinary), ordinaryHours, pensionPeriod: npPeriodUsed || input.pensionPeriod || '2026H2' },
    minimumWage,
    earnings: {
      baseSalary,
      overtimePay: Math.round(overtimePay),
      nightPay: Math.round(nightPay),
      holiday8Pay: Math.round(holiday8Pay),
      holidayOver8Pay: Math.round(holidayOPay),
      overtimeTotal: Math.round(overtimeTotal),
      taxableAllowance, bonus,
      taxFree: { meal, car, childcare: care, other: otherTaxFree, total: taxFreeTotal },
      grossPay: Math.round(grossPay),
      taxableGross: Math.round(taxableGross),
    },
    deductions: {
      nationalPension, healthInsurance, longTermCare, employmentInsurance, industrialAccident,
      insuranceTotal,
      incomeTax, localIncomeTax, taxMode: mode, taxNote,
      otherDeductions,
      totalDeductions: Math.round(totalDeductions),
    },
    netPay: Math.round(netPay),
    meta: { asOf: R.META.asOf, warnings: warn },
  };
}

// 소득세 거친 근사 (설명용 — 절대 신고용 아님)
// 간이세액표 부재 시 단순 연환산 누진 후 근로소득공제·기본공제 대략 반영.
function approxIncomeTax(monthlyTaxable, itIn, R, familyIn) {
  const family = familyIn ?? famOf(itIn.family);
  const annual = monthlyTaxable * 12;
  // 근로소득공제(개략)
  let earnDeduct;
  if (annual <= 5000000) earnDeduct = annual * 0.7;
  else if (annual <= 15000000) earnDeduct = 3500000 + (annual - 5000000) * 0.4;
  else if (annual <= 45000000) earnDeduct = 7500000 + (annual - 15000000) * 0.15;
  else if (annual <= 100000000) earnDeduct = 12000000 + (annual - 45000000) * 0.05;
  else earnDeduct = 14750000 + (annual - 100000000) * 0.02;
  const personalDeduct = 1500000 * family; // 기본공제 1인 150만
  const taxBase = Math.max(0, annual - earnDeduct - personalDeduct);
  const annualTax = R.progressiveTax(taxBase);
  // 근로소득세액공제 대략 55%(한도 무시) — 매우 거친 근사
  const afterCredit = annualTax * 0.55;
  let monthly = afterCredit / 12;
  // 자녀공제(월 정액)
  const kids = numNN(itIn.childrenUnder20, 'incomeTax.childrenUnder20');
  if (kids === 1) monthly -= R.INCOME_TAX.childCredit[1];
  else if (kids === 2) monthly -= R.INCOME_TAX.childCredit[2];
  else if (kids >= 3) monthly -= R.INCOME_TAX.childCredit[2] + (kids - 2) * R.INCOME_TAX.childCredit.perExtraOver3;
  return Math.max(0, monthly);
}

// ═══════════════════════════════════════════════════════════════
// 최저임금 위반 판정 (최저임금법 §5·§6, 시행령 §3·§5)  — v3.4.2 신설
// ───────────────────────────────────────────────────────────────
// 제품이 광고하는 nomu-payroll 5개 모드 중 하나인데 판정 함수가 엔진에 아예 없었다
// (요율 데이터는 rates-2026.mjs MINWAGE 에만 있고 쓰는 코드가 없음).
//
// 산입 기준(보수적):
//  ① 비교 임금 = '소정근로에 대하여 매월 1회 이상 정기적으로 지급하는 임금'
//     - 산입: 기본급 + 매월 정기 지급 과세수당 + 통화로 지급하는 복리후생비(식대 등)
//       ※ 상여금·통화 복리후생비의 미산입 비율은 2024.1.1부터 0% → 전액 산입(§6④2·3)
//     - 제외: 연장·야간·휴일 가산수당(§6④1 — 소정근로 외 임금), 연차미사용수당
//     - 제외(보수적): 자가운전보조금(실비변상적) · 매월 정기지급이 아닌 상여(분기·명절)
//       → bonusMonthlyRegular:true 를 주면 상여를 산입한다.
//  ② 시간급 환산 = 비교 임금 ÷ 월 소정근로시간(주휴 포함, 주40h 기준 209h — 시행령 §5)
//  ③ 수습 감액(§5②·시행령 §3): 1년 이상 근로계약 + 수습 3개월 이내 + 단순노무 아님 → 90%까지
// 판정 기준이 불확실한 항목은 '산입하지 않음(=사장님에게 불리한 쪽)'으로 두어
// 위반을 놓치지 않게 했고, 어떤 항목을 왜 뺐는지 basis 에 전부 적는다.
export function checkMinimumWage(input = {}) {
  const warn = [];
  _resetCoerce();
  const R = getRates(input.year ?? input.payDate ?? input.payPeriodEnd);
  if (R.stale) warn.push(R.staleWarning);
  const MW = R.MINWAGE;
  const minHourly = MW[MW.current]?.hour ?? MW[2026].hour;

  // 소정근로 월 환산시간 — 시급제면 (주소정 + 주휴시간) × 4.345, 아니면 ordinaryHours(기본 209)
  let hours = numNN(input.ordinaryHours, 'ordinaryHours');
  let hourlyBase = null;
  if (numNN(input.hourlyWage, 'hourlyWage') > 0) {
    hourlyBase = hourlyToMonthly(input.hourlyWage, input.weeklyHours);
    if (!hours) {
      const wh = hourlyBase.weeklyHours;
      hours = +((wh + hourlyBase.weeklyHolidayHours) * (365 / 7 / 12)).toFixed(2);
    }
  }
  if (!hours) hours = MW.monthlyStdHours; // 209
  // 명시적 0(v3.4.4) — 폴백 자체는 종전과 같지만, 조용히 대체하지 않고 고지한다.
  if (_explicitZero(input.ordinaryHours))
    warn.push(`⚠️ 소정근로시간(ordinaryHours)을 0시간으로 입력했습니다 — 0시간으로는 시간급을 환산할 수 없어 ${hours}시간으로 판정했습니다. 실제 월 소정근로시간을 입력하세요.`);

  // ── 산입/제외 분해 ──
  const included = [], excluded = [];
  const push = (arr, label, amount, why) => { if (amount) arr.push({ label, amount: Math.round(amount), why }); };

  const base = hourlyBase ? hourlyBase.monthlyBase : numNN(input.baseSalary, 'baseSalary');
  push(included, '기본급(주휴 포함)', base, '소정근로 대가 — 최저임금법 §6④ 본문');

  // 미입력 판정은 값이 아니라 '존재 여부' 로 한다(=== undefined 만 보면 null·'' 이 false 로 읽혀
  // 매월 정기 수당이 통째로 산입에서 빠지고, 멀쩡한 급여가 🔴 최저임금 위반으로 오판정됐다).
  const allowRegular = _blank(input.allowanceMonthlyRegular) ? true : bool(input.allowanceMonthlyRegular, 'allowanceMonthlyRegular');
  const allow = numNN(input.taxableAllowance, 'taxableAllowance');
  if (allowRegular) push(included, '매월 정기 과세수당', allow, '매월 1회 이상 정기 지급 과세수당은 산입');
  else push(excluded, '과세수당(비정기)', allow, '매월 1회 이상 정기 지급이 아니면 미산입(§6④)');

  const meal = numNN(input.mealAllowance, 'mealAllowance');
  const care = numNN(input.childcareAllowance, 'childcareAllowance');
  const other = numNN(input.otherTaxFree, 'otherTaxFree');
  push(included, '식대(통화 지급)', meal, '통화로 지급하는 복리후생비 — 2024.1.1부터 전액 산입(§6④3)');
  push(included, '보육수당(통화 지급)', care, '통화로 지급하는 복리후생비 — 2024.1.1부터 전액 산입(§6④3)');
  push(included, '기타 통화 지급분', other, '통화로 지급하는 복리후생비 — 2024.1.1부터 전액 산입(§6④3)');

  const car = numNN(input.carAllowance, 'carAllowance');
  push(excluded, '자가운전보조금', car, '실비변상적 금품으로 보아 미산입(보수적 판단 — 실지급 성격이 임금이면 산입 가능, 노무사 확인)');

  const bonusRegular = bool(input.bonusMonthlyRegular, 'bonusMonthlyRegular');
  const bonus = numNN(input.bonus, 'bonus');
  if (bonusRegular) push(included, '상여(매월 정기)', bonus, '매월 1회 이상 정기 지급 상여 — 2024.1.1부터 전액 산입(§6④2)');
  else push(excluded, '상여(분기·명절 등)', bonus, '매월 1회 이상 정기 지급이 아니면 미산입(§6④2 단서)');

  // 가산수당은 언제나 제외 (§6④1 — 소정근로시간 외 임금)
  const otHours = numNN(input.overtimeHours, 'overtimeHours') + numNN(input.nightHours, 'nightHours')
    + numNN(input.holidayHoursWithin8, 'holidayHoursWithin8') + numNN(input.holidayHoursOver8, 'holidayHoursOver8');
  if (otHours > 0) excluded.push({ label: '연장·야간·휴일 가산수당', amount: null, why: '소정근로 외 임금이라 최저임금 비교에서 제외(§6④1)' });

  const comparable = included.reduce((s, x) => s + x.amount, 0);
  const effectiveHourly = hours > 0 ? comparable / hours : 0;

  // ── 수습 감액 (§5②·시행령 §3) ──
  const isProbation = bool(input.probation, 'probation');
  const contractYears = numNN(input.contractYears, 'contractYears');
  const simpleLabor = bool(input.simpleLabor, 'simpleLabor');
  const probationMonths = numNN(input.probationMonths, 'probationMonths');
  let appliedMinHourly = minHourly, probationNote = null;
  if (isProbation) {
    const okYears = contractYears >= 1;
    // '미입력' 판정은 값이 아니라 존재 여부로 한다(v3.4.5). 종전 `probationMonths === 0` 은
    // 미입력 신호로 값 0 을 쓰던 자리다(결과는 동일 — 0개월도 3개월 이내라 감액 요건 충족).
    const okMonths = _blank(input.probationMonths) || probationMonths <= MW.probationMaxMonths;
    if (okYears && okMonths && !simpleLabor) {
      appliedMinHourly = Math.ceil(minHourly * (1 - MW.probationDiscountRate));
      probationNote = `수습 감액 적용(§5②·시행령 §3): 1년 이상 계약 + 수습 ${MW.probationMaxMonths}개월 이내 + 단순노무 아님 → 최저 시급의 90%(${appliedMinHourly.toLocaleString()}원)`;
    } else {
      probationNote = `수습이라도 감액 불가 — ${!okYears ? '근로계약기간 1년 미만' : simpleLabor ? '단순노무 종사자(고용노동부 고시)' : `수습 ${MW.probationMaxMonths}개월 초과`}. 최저 시급 ${minHourly.toLocaleString()}원 전액 적용.`;
    }
    warn.push(probationNote);
  }
  const minMonthly = Math.round(appliedMinHourly * hours);

  const violated = comparable > 0 && effectiveHourly < appliedMinHourly;
  const shortfallHourly = violated ? Math.ceil(appliedMinHourly - effectiveHourly) : 0;
  const shortfallMonthly = violated ? Math.round(minMonthly - comparable) : 0;
  if (comparable <= 0)
    warn.push('⚠️ 최저임금 비교 대상 임금이 0원입니다 — 기본급(또는 시급×주소정근로시간)을 입력해야 위반 여부를 판정할 수 있습니다.');
  if (violated)
    warn.push(`🔴 최저임금 위반 소지: 산입임금 시간급 ${Math.floor(effectiveHourly).toLocaleString()}원 < 최저 시급 ${appliedMinHourly.toLocaleString()}원. 월 ${shortfallMonthly.toLocaleString()}원 부족(최저임금법 §6① 위반 시 3년 이하 징역 또는 2천만원 이하 벌금 §28①).`);

  warn.push(..._drainCoerce());
  return {
    mode: 'minimumWage',
    year: R.year, usingYear: R.usingYear,
    minHourly, appliedMinHourly, minMonthly,
    hours,
    comparableWage: comparable,
    effectiveHourly: Math.floor(effectiveHourly),
    violated,
    shortfallHourly, shortfallMonthly,
    signal: comparable <= 0 ? '⚪ 판정 불가(입력 부족)' : violated ? '🔴 최저임금 위반 소지' : '🟢 최저임금 이상',
    probation: isProbation ? { applied: appliedMinHourly < minHourly, note: probationNote } : null,
    included, excluded,
    basis: [
      `${R.usingYear}년 최저임금 시급 ${minHourly.toLocaleString()}원 · 월 환산(209h) ${(MW[MW.current]?.month209 ?? 0).toLocaleString()}원 — ${MW.src}`,
      '산입범위: 최저임금법 §6④ (상여금·통화 복리후생비 미산입 비율 2024.1.1부터 0% → 전액 산입)',
      '시간 환산: 최저임금법 시행령 §5 (소정근로시간 + 주휴시간)',
      '⚠️ 참고용 판정입니다. 수당의 성격(정기·일률·고정성) 다툼이 있으면 공인노무사 검토가 필요합니다.',
    ],
    warnings: warn,
  };
}

// ── CLI ──────────────────────────────────────────────────────
const isMain = await (async () => { try { const { fileURLToPath } = await import("node:url"); const { realpathSync } = await import("node:fs"); return !!process.argv[1] && realpathSync(fileURLToPath(import.meta.url)) === realpathSync(process.argv[1]); } catch { return false; } })(); // 한글·공백 경로 견고(realpath 비교)
if (isMain) {
  const fs = await import('node:fs');
  const path = process.argv[2];
  if (!path) { console.error('사용법: node payroll.mjs <input.json>'); process.exit(1); }
  const input = JSON.parse(fs.readFileSync(path, 'utf8'));
  const r = calcPayroll(input);
  const w = n => Number(n).toLocaleString('ko-KR');
  console.log(JSON.stringify(r, null, 2));
  console.log('\n=== 급여 요약 (2026 기준) ===');
  console.log(`지급: 기본급 ${w(r.earnings.baseSalary)} + 가산수당 ${w(r.earnings.overtimeTotal)} + 수당/상여 ${w(r.earnings.taxableAllowance + r.earnings.bonus)} + 비과세 ${w(r.earnings.taxFree.total)}`);
  console.log(`총지급액: ${w(r.earnings.grossPay)}원`);
  console.log(`공제: 국민연금 ${w(r.deductions.nationalPension)} / 건강 ${w(r.deductions.healthInsurance)} / 장기요양 ${w(r.deductions.longTermCare)} / 고용 ${w(r.deductions.employmentInsurance)} / 소득세 ${w(r.deductions.incomeTax)} / 지방세 ${w(r.deductions.localIncomeTax)}`);
  console.log(`총공제액: ${w(r.deductions.totalDeductions)}원`);
  console.log(`★ 실수령액: ${w(r.netPay)}원`);
  const m = r.minimumWage;
  console.log(`최저임금: ${m.signal}  산입임금 시간급 ${w(m.effectiveHourly)}원 vs 최저 ${w(m.appliedMinHourly)}원`
    + (m.violated ? `  → 월 ${w(m.shortfallMonthly)}원 부족` : ''));
  if (r.meta.warnings.length) { console.log('\n[주의]'); r.meta.warnings.forEach(x => console.log(' - ' + x)); }
}

export default { calcPayroll, checkMinimumWage, hourlyToMonthly };
