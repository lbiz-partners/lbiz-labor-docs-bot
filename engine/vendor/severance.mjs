// 퇴직금 계산 엔진 — 평균임금 → 퇴직금 → 퇴직소득세(개산)
// 근거: 근로자퇴직급여보장법 §4·§8·§9, 근로기준법 §2(평균임금), 소득세법
// 요율·공제표는 rates-2026.mjs 사용. node 정확계산용.
//
// 사용:
//   import { calcSeverance } from './severance.mjs';
//   node severance.mjs <input.json>
//
// 입력(input):
// {
//   hireDate: '2019-03-01',          // 입사일
//   lastWorkingDay: '2026-02-28',    // 마지막 근무일(재직 마지막 날)
//   weeklyHours: 40,                 // 주 소정근로시간(15h 이상이어야 대상)
//   // 평균임금 산정용: 산정사유발생일(=lastWorkingDay+1) 직전 3개월
//   last3MonthsWage: 8400000,        // 최근 3개월 임금총액(기본급+고정수당 등 합계)
//   periodDays: 90,                  // 그 3개월의 달력상 총일수(89~92). 미지정 시 자동계산
//   annualBonus: 0,                  // 직전 1년간 정기상여 총액(×3/12 가산)
//   annualLeaveAllowance: 0,         // 전년도 지급 연차수당(×3/12 가산)
//   ordinaryDailyWage: 0,            // 1일 통상임금(평균임금 최저보장 비교용). 0이면 비교 생략
//   excludedDays: 0,                 // 제외기간 일수(수습·육아휴직 등)
//   excludedWage: 0,                 // 제외기간 임금(총액·일수에서 차감)
//   taxedSince: '2010-12-01',        // 5인 미만 사업장이면 퇴직금 기산일(이후 근속분만)
//   fiveUnder: false,                // 5인 미만 여부(퇴직금은 적용됨 — 안내용)
// }

import { getRates } from './rates-2026.mjs';

// ── 입력 방어 공통 계약 (v3.4.2) ──────────────────────────────
// 결함 클래스 A(조용한 값 소실) 박멸용 공통 블록.
//   num(v, field)    숫자/숫자문자열("9000000", " 9,000,000 ", "9000000원")은 변환 + 변환 사실 경고.
//                    해석 불가(NaN·"abc"·객체)는 0 + '어떤 필드가 빠졌는지' 경고. 조용한 소실 금지.
//                    미입력(undefined/null/"")은 종전대로 조용히 0 — 정상 입력이므로 경고하지 않는다.
//   numNN(v, field)  위 + 도메인상 음수 불가 필드(임금·기간)에서 음수 경고.
//                    (last3MonthsWage:-9000000 이 퇴직금 -21,016,438원을 경고 0건으로 산출했다)
//   bool(v, field)   "false"/"0"/"N"/"아니오"/"없음" 등 문자열 falsy 를 올바로 해석 + 변환 경고.
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

// ── 명시적 0 존중 계약 (v3.4.4) ──────────────────────────────
// 결함 클래스: `numNN(x) || 기본값` 은 '미입력' 과 '사장님이 일부러 넣은 0' 을 구분하지 못한다
// (numNN 은 둘 다 0 을 돌려주므로 반환값으로는 판정 불가).
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

function daysBetween(a, b) { // 양 끝 포함 일수
  const d = (new Date(b) - new Date(a)) / 86400000;
  return Math.round(d) + 1;
}

// 'YYYY-MM-DD' → UTC epoch(자정) + Y/M/D. TZ 드리프트 없이 달력 비교용.
function ymd(s) {
  const [Y, M, D] = String(s).slice(0, 10).split('-').map(Number);
  return { Y, M, D, t: Date.UTC(Y, M - 1, D) };
}
// 근속연수(소득세법 §48): 달력 기준 만근속연수 + 1년 미만 절상.
//   days/365 올림은 윤년 2일 누적으로 정수년 경계를 넘겨 1년 과다 산정됨 → 달력 기준으로 교정.
function creditYears(startStr, lastStr) {
  const h = ymd(startStr), l = ymd(lastStr);
  let y = l.Y - h.Y;
  if (l.t < Date.UTC(l.Y, h.M - 1, h.D)) y -= 1;        // 올해 근속기념일 전 → 완성연수 -1
  if (l.t > Date.UTC(h.Y + y, h.M - 1, h.D)) y += 1;    // 완성연수 하루라도 초과 → 절상 +1
  return Math.max(1, y);
}

export function calcSeverance(input = {}) {
  const warn = [];
  _resetCoerce();   // 문자열→숫자 변환 기록은 이 호출분만 모은다
  const hire = input.hireDate, last = input.lastWorkingDay;
  if (!hire || !last) throw new Error('hireDate·lastWorkingDay(입사일·마지막근무일) 필요');

  // 계산 연도 자동 인식: 퇴사일(마지막근무일) 기준. 미등록 연도면 직전값+경고.
  const R = getRates(last);
  const S = R.SEVERANCE;
  if (R.stale) warn.push(R.staleWarning);

  // 0) 자격 검증
  const tenureDays = daysBetween(hire, last);
  // ⚠️ v3.4.3 (A6): 종전 `numNN(...) || 40` 은 미입력과 '0' 을 구분하지 못했다.
  // numNN 은 undefined/null/'' 를 경고 없이 0 으로 돌려주고, 그 0 이 `|| 40` 으로
  // 40시간이 되어 **초단시간(주 15시간 미만) 근로자가 법정 퇴직금 대상으로 뒤집혔다.**
  // 미입력(항목 생략)일 때만 40시간을 기본값으로 쓰고, 그 사실을 warn 에 남긴다.
  const _whRaw = input.weeklyHours;
  const _whMissing = (_whRaw === undefined || _whRaw === null || _whRaw === '');
  const weeklyHours = _whMissing ? 40 : numNN(_whRaw, 'weeklyHours');
  if (_whMissing) warn.push('주 소정근로시간(weeklyHours) 미입력 — 통상 근로자 기준 40시간으로 계산했습니다. 초단시간(주 15시간 미만) 근로자라면 실제 시간을 반드시 입력하십시오.');
  // 명시적 0(v3.4.5) — 0 은 존중해 그대로 판정에 쓰되 조용히 넘기지 않는다. 0시간이면 아래
  // §minWeeklyHours 비교에서 eligible:false 로 뒤집혀 '퇴직금 대상 아님' 이 되는데, 종전엔
  // 경고가 0건이라 왜 대상에서 빠졌는지 알 수 없었다(severancePay 금액은 그대로 찍힌다).
  if (_explicitZero(_whRaw))
    warn.push('⚠️ 주 소정근로시간을 0시간으로 입력했습니다 — 주 15시간 미만(초단시간)으로 보아 법정 퇴직금 대상이 아닌 것으로 판정했습니다. 실제 주 소정근로시간을 입력하세요(통상 근로자는 40).');
  let eligible = true, ineligibleReason = '';
  if (tenureDays < 365) { eligible = false; ineligibleReason = '계속근로 1년 미만 → 법정 퇴직금 대상 아님'; }
  if (weeklyHours < S.minWeeklyHours) { eligible = false; ineligibleReason = '주 15시간 미만(초단시간) → 법정 퇴직금 대상 아님'; }

  // 5인 미만: 2010-12-01 이후 근속분만 산입
  let creditDays = tenureDays;
  let creditStart = hire; // 근속연수 계산의 기산일(5인 미만이면 fiveUnderSince로 당겨질 수 있음)
  const fiveUnder = bool(input.fiveUnder, 'fiveUnder');   // "false" 문자열을 truthy 로 읽던 결함 교정
  if (fiveUnder) {
    const since = new Date(input.taxedSince || S.fiveUnderSince);
    const hireD = new Date(hire);
    if (hireD < since) {
      creditDays = daysBetween(S.fiveUnderSince, last);
      creditStart = input.taxedSince || S.fiveUnderSince;
      warn.push(`5인 미만 사업장: 퇴직금은 ${S.fiveUnderSince} 이후 근속분(${creditDays}일)만 산입(그 이전 근속분 제외).`);
    }
    warn.push('5인 미만이라도 퇴직금은 적용됨(1년 이상·주15h 이상). 단 연장·야간·휴일 가산수당은 미적용이라 평균임금 구성이 다를 수 있음.');
  }

  // 1) 평균임금 산정
  // periodDays 미지정 시: 산정사유발생일(=마지막근무일+1) 직전 3개월 달력일수 자동계산(89~92)
  const periodDaysZero = _explicitZero(input.periodDays);
  let periodDays = numNN(input.periodDays, 'periodDays');
  if (!periodDays) {
    const eventDay = new Date(last); eventDay.setDate(eventDay.getDate() + 1);
    const start = new Date(eventDay); start.setMonth(start.getMonth() - 3);
    periodDays = Math.round((eventDay - start) / 86400000);
    // 0일은 1일 평균임금의 분모라 도메인상 불가능한 값 → 대체하되 조용히 바꾸지 않는다.
    if (periodDaysZero)
      warn.push(`⚠️ 평균임금 산정기간(periodDays)을 0일로 입력했습니다 — 0일은 1일 평균임금의 분모라 계산할 수 없는 값이어서 산정사유발생일 직전 3개월 달력일수 ${periodDays}일로 대체했습니다. 실제 산정기간 일수(보통 89~92)를 입력하세요.`);
  }
  const wageIn = input.last3MonthsWage;
  let wageSum = numNN(wageIn, 'last3MonthsWage');
  // 임금총액이 비었으면 퇴직금이 0원으로 나오는데 그 이유를 사장님이 알 방법이 없었다.
  if (_blank(wageIn))
    warn.push('⚠️ 임금총액(last3MonthsWage)이 비어 있습니다 — 평균임금이 0원이 되어 퇴직금도 0원으로 산출됩니다. 산정사유발생일 직전 3개월 임금총액을 입력하세요(근로기준법 §2①6).');
  // 명시적 0(v3.4.5) — 0 은 존중하되 결과가 크게 달라지므로 고지한다. 종전엔 미입력만 경고가
  // 있어, 0 을 넣으면 평균임금이 0원(또는 통상임금 최저보장액)으로 떨어져도 무경고였다.
  if (_explicitZero(wageIn))
    warn.push('⚠️ 임금총액(last3MonthsWage)을 0원으로 입력해 그대로 계산했습니다 — 평균임금이 0원이 되어, 1일 통상임금을 입력한 경우에만 그 금액(평균임금 최저보장)으로 퇴직금이 산출됩니다. 직전 3개월 임금총액을 확인하세요(근로기준법 §2①6).');
  // 제외기간 차감
  periodDays -= numNN(input.excludedDays, 'excludedDays');
  // 분모가 0 이하가 되면 아래에서 평균임금을 0 으로 두는데(0 나눗셈 회피), 종전엔 그 사실이
  // 경고 없이 '퇴직금 0원' 으로만 나와 사장님이 미지급 사유를 알 수 없었다.
  if (periodDays <= 0)
    warn.push(`⚠️ 제외기간(excludedDays ${numNN(input.excludedDays, 'excludedDays').toLocaleString('ko-KR')}일)을 빼고 나면 평균임금 산정기간이 ${periodDays}일이 됩니다 — 1일 평균임금의 분모가 0 이하라 평균임금·퇴직금을 산정하지 않고 0원으로 표시했습니다. 제외기간 일수를 확인하세요.`);
  wageSum -= numNN(input.excludedWage, 'excludedWage');
  // 연단위 항목 3개월 환산 가산
  const bonusAdd = numNN(input.annualBonus, 'annualBonus') * 3 / 12;
  const leaveAdd = numNN(input.annualLeaveAllowance, 'annualLeaveAllowance') * 3 / 12;
  const totalWage = wageSum + bonusAdd + leaveAdd;
  let avgDailyWage = periodDays > 0 ? totalWage / periodDays : 0;

  // 통상임금 최저보장
  const ordinaryDaily = numNN(input.ordinaryDailyWage, 'ordinaryDailyWage');
  let usedFloor = false;
  if (ordinaryDaily > 0 && avgDailyWage < ordinaryDaily) {
    avgDailyWage = ordinaryDaily;
    usedFloor = true;
    warn.push('평균임금이 1일 통상임금보다 적어 통상임금으로 대체(평균임금 최저보장, 근로기준법 §2②).');
  }
  // 0 이면 최저보장 비교를 생략하는 동작은 종전과 같다. 다만 '미입력' 과 '사장님이 넣은 0' 을
  // 같은 문구로 알리면 입력을 고칠 곳을 찾을 수 없어 문구만 분리한다(계산 결과는 동일).
  if (ordinaryDaily === 0 && !_explicitZero(input.ordinaryDailyWage))
    warn.push('1일 통상임금(ordinaryDailyWage) 미입력 — 평균임금 최저보장 비교 생략. 결근·휴직이 있던 분기면 과소 산정될 수 있어 통상임금 확인 권장.');
  if (_explicitZero(input.ordinaryDailyWage))
    warn.push('1일 통상임금(ordinaryDailyWage)을 0원으로 입력해 평균임금 최저보장(근로기준법 §2②) 비교를 생략했습니다 — 결근·휴직이 있던 분기면 퇴직금이 과소 산정될 수 있으니 1일 통상임금을 확인하세요.');

  // 2) 퇴직금
  let severance = avgDailyWage * 30 * (creditDays / 365);
  // 음수 퇴직금은 도메인상 불가능하다. 조용히 -21,016,438원 같은 값을 내보내면
  // 그대로 명세서·급여대장에 실린다 → 산출을 거부하고 이유를 명시한다.
  let refused = false;
  if (severance < 0) {
    refused = true;
    warn.push(`⚠️ 계산된 퇴직금이 음수(${Math.round(severance).toLocaleString('ko-KR')}원)라 산출을 거부했습니다 — 임금총액·제외기간 임금 입력의 부호를 확인하세요(평균임금 ${Math.round(avgDailyWage).toLocaleString('ko-KR')}원/일). 퇴직금은 0원으로 표시합니다.`);
    severance = 0;
    avgDailyWage = 0;
  }

  // 3) 퇴직소득세 개산 (근속연수는 달력 기준 절상값 사용)
  const creditYrs = creditYears(creditStart, last);
  const tax = eligible && !refused ? calcRetirementTax(severance, creditYrs, R) : null;
  // 문자열 숫자 변환·해석 불가 입력을 경고로 올린다(조용한 소실 금지). 숫자 입력만이면 빈 배열.
  warn.push(..._drainCoerce());

  return {
    eligible, ineligibleReason,
    tenure: { hireDate: hire, lastWorkingDay: last, tenureDays, creditDays, years: +(creditDays / 365).toFixed(2) },
    averageWage: {
      periodDays, wageSum: Math.round(wageSum),
      bonusAdd: Math.round(bonusAdd), leaveAdd: Math.round(leaveAdd),
      totalWage: Math.round(totalWage),
      avgDailyWage: Math.round(avgDailyWage), usedOrdinaryFloor: usedFloor,
    },
    severancePay: Math.round(severance),
    ...(refused ? { refused: true, refusedReason: '음수 퇴직금 — 입력 부호 오류로 판단해 산출 거부' } : {}),
    retirementTax: tax,
    meta: { asOf: R.META.asOf, payDue: `퇴직일부터 ${S.payDueDays}일 이내 지급(미지급 시 지연이자)`, warnings: warn },
  };
}

// 퇴직소득세 (소득세법 — 근속연수공제·환산급여·환산산출세액)
function calcRetirementTax(severance, years, R) {
  const S = R.SEVERANCE;
  const n = Math.max(1, years); // 근속연수(달력 기준 절상값, calcSeverance에서 산정)
  // 근속연수공제
  const td = S.tenureDeduction.find(x => n <= x.upto) || S.tenureDeduction.at(-1);
  const tdBracketStart = { 5: 0, 10: 5, 20: 10, [Infinity]: 20 }[td.upto] ?? 0;
  const tenureDeduct = td.base + (n - tdBracketStart) * td.per;
  const afterTenure = Math.max(0, severance - tenureDeduct);
  if (afterTenure <= 0) return { years: n, tenureDeduct, taxBase: 0, retirementTax: 0, localTax: 0, total: 0, note: '근속연수공제 후 과세표준 0 — 퇴직소득세 없음' };

  // 환산급여
  const converted = afterTenure / n * 12;
  // 환산급여공제
  const cd = S.convertedDeduction.find(x => converted <= x.upto) || S.convertedDeduction.at(-1);
  const cdStart = { 8000000: 0, 70000000: 8000000, 100000000: 70000000, 300000000: 100000000, [Infinity]: 300000000 }[cd.upto] ?? 0;
  const convDeduct = cd.base + (converted - cdStart) * cd.rate;
  const taxBase = Math.max(0, converted - convDeduct);
  // 환산산출세액 → 산출세액
  const convertedTax = R.progressiveTax(taxBase);
  const retirementTax = floorTo10(convertedTax / 12 * n);
  const localTax = floorTo10(retirementTax * 0.10);
  return {
    years: n, tenureDeduct: Math.round(tenureDeduct), converted: Math.round(converted),
    convDeduct: Math.round(convDeduct), taxBase: Math.round(taxBase),
    retirementTax, localTax, total: retirementTax + localTax,
    note: '개산값. 정확액은 홈택스 퇴직소득세 계산 또는 세무대리인 확인',
  };
}
const floorTo10 = v => Math.floor(v / 10) * 10;

// ── CLI ──────────────────────────────────────────────────────
const isMain = await (async () => { try { const { fileURLToPath } = await import("node:url"); const { realpathSync } = await import("node:fs"); return !!process.argv[1] && realpathSync(fileURLToPath(import.meta.url)) === realpathSync(process.argv[1]); } catch { return false; } })(); // 한글·공백 경로 견고(realpath 비교)
if (isMain) {
  const fs = await import('node:fs');
  const path = process.argv[2];
  if (!path) { console.error('사용법: node severance.mjs <input.json>'); process.exit(1); }
  const r = calcSeverance(JSON.parse(fs.readFileSync(path, 'utf8')));
  const w = n => Number(n).toLocaleString('ko-KR');
  console.log(JSON.stringify(r, null, 2));
  console.log('\n=== 퇴직금 요약 ===');
  if (!r.eligible) { console.log('대상 아님: ' + r.ineligibleReason); }
  else {
    console.log(`근속: ${r.tenure.tenureDays}일(${r.tenure.years}년)  산입일수 ${r.tenure.creditDays}일`);
    console.log(`1일 평균임금: ${w(r.averageWage.avgDailyWage)}원${r.averageWage.usedOrdinaryFloor ? ' (통상임금 최저보장 적용)' : ''}`);
    console.log(`★ 퇴직금(세전): ${w(r.severancePay)}원`);
    if (r.retirementTax) console.log(`퇴직소득세(개산): ${w(r.retirementTax.retirementTax)} + 지방세 ${w(r.retirementTax.localTax)} = ${w(r.retirementTax.total)}원`);
  }
  if (r.meta.warnings.length) { console.log('\n[주의]'); r.meta.warnings.forEach(x => console.log(' - ' + x)); }
}

export default { calcSeverance };
