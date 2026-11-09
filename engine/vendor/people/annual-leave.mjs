// 연차유급휴가 계산 엔진 — 근로기준법 §60·§61
// 입사일 기준 / 회계연도 기준 모두 지원. node 정확계산용.
//
// 사용:
//   import { calcAnnualLeave } from './annual-leave.mjs';
//   node annual-leave.mjs <input.json>
//
// 입력(input):
// {
//   hireDate: '2023-03-15',        // 입사일
//   asOf: '2026-06-05',            // 산정 기준일(미지정 시 오늘)
//   basis: '입사일' | '회계연도',   // 부여 방식
//   fiscalStart: '01-01',          // 회계연도 시작(MM-DD), basis:회계연도 시
//   attendanceRate: 1.0,           // 직전 1년 출근율(0~1). 0.8 미만이면 §60② 개근월 산식
//   fullAttendanceMonths: null,    // (출근율<0.8일 때) 직전 1년 중 개근한 개월 수(최대11). 미입력 시 0일+경고
//   usedDays: 0,                   // 사용한 연차(미사용수당 계산용)
//   ordinaryDailyWage: 0,          // 1일 통상임금(미사용수당 단가). 0이면 수당 생략
//   fiveUnder: false               // 5인 미만 → 연차 미적용(§60 제외)
// }

import R, { getRates } from './rates-2026.mjs';
const A = R.ANNUAL_LEAVE;   // 연차 발생규칙 §60 — 연도 무관(법 개정 전 불변)
// ── 입력 방어 공통 계약 (v3.4.2) ──────────────────────────────
// 결함 클래스 A(조용한 값 소실) 박멸용 공통 블록.
//   num(v, field)    숫자/숫자문자열("3", " 100,000 ")은 변환 + 변환 사실 경고.
//                    해석 불가(NaN·"abc"·객체)는 0 + '어떤 필드가 빠졌는지' 경고. 조용한 소실 금지.
//                    미입력(undefined/null/"")은 종전대로 조용히 0 — 정상 입력이므로 경고하지 않는다.
//   numNN(v, field)  위 + 도메인상 음수 불가 필드(일수·임금)에서 음수 경고.
//   bool(v, field)   "false"/"0"/"N"/"아니오"/"없음" 등 문자열 falsy 를 올바로 해석 + 변환 경고.
//                    (기존 truthy 판정은 fiveUnder:"false" 를 5인 미만으로 오판했다)
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
      // 퍼센트 표기는 필드마다 단위가 달라(출근율 0.8 vs 이율 5) 자동 환산하면 새 오류를 만든다.
      _coerceLog.push(`⚠️ 입력 "${field || '숫자 항목'}" 값(${_show(v)})은 백분율 표기라 이 필드의 단위와 어긋납니다 — 0으로 처리했습니다. % 기호를 빼고 숫자로 넣으세요(출근율은 0.8, 이율은 5).`);
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
const D = s => new Date(s + (s.length <= 10 ? 'T00:00:00' : ''));
const daysBetween = (a, b) => Math.floor((D(b) - D(a)) / 86400000);
const monthsCompleted = (a, b) => { // 입사응당일 기준 만료 개월수
  const x = D(a), y = D(b); let m = (y.getFullYear() - x.getFullYear()) * 12 + (y.getMonth() - x.getMonth());
  if (y.getDate() < x.getDate()) m -= 1;
  return Math.max(0, m);
};

// 입사일 기준 누적 연차(만 근속연수 기반)
// fullAttendanceMonths: (선택) 직전 1년 중 '개근한 개월 수'. 80% 미만 출근자 산정용.
function byHire(hireDate, asOf, attendanceRate, fullAttendanceMonths) {
  const months = monthsCompleted(hireDate, asOf);
  const tenureYears = Math.floor(months / 12);
  const under1y = Math.min(A.under1yMax, months); // 1년 미만 월차(최대 11)

  let annual = 0, formula = '', warn = null;
  if (tenureYears < 1) {
    annual = 0; formula = `입사 1년 미만 — 월차 ${under1y}일(개근 1개월당 1일, 최대 11)`;
  } else if (attendanceRate >= A.attendanceThreshold) {
    annual = Math.min(A.maxDays, A.baseDays + Math.floor((tenureYears - 1) / 2) * A.bonusPer2yrs);
    formula = `${tenureYears}년차: 15 + 가산 ${annual - A.baseDays}일 = ${annual}일 (3년↑ 매2년 +1, 상한 25)`;
  } else {
    // 80% 미만 출근(§60②): '직전 1년 중 개근한 개월 수'만큼 부여(최대 11).
    // 개근 개월 수가 입력되지 않으면 단정하지 않고(0일 fabricate 금지) 확인을 요구한다.
    if (fullAttendanceMonths == null) {
      annual = 0;
      warn = '출근율 80% 미만 근로자는 §60②로 "직전 1년 중 개근한 개월 수(최대 11일)"만큼 연차가 발생합니다. 정확 산정을 위해 fullAttendanceMonths(개근 개월 수)를 입력하세요. (현재 미입력 → 0일로 표시)';
      formula = `출근율 80% 미만 → 개근 개월 수 입력 필요(§60②)`;
    } else {
      annual = Math.min(A.under1yMax, Math.max(0, Math.floor(fullAttendanceMonths)));
      formula = `출근율 80% 미만 → 개근 ${annual}개월 = ${annual}일(§60②, 최대 11)`;
    }
  }
  return { months, tenureYears, under1yMonthly: under1y, annualByYear: annual, formula, warn };
}

export function calcAnnualLeave(input = {}) {
  const warn = [];
  _resetCoerce();   // 문자열→숫자 변환 기록은 이 호출분만 모은다
  const hire = input.hireDate;
  if (!hire) throw new Error('hireDate(입사일) 필요');
  const asOf = input.asOf || new Date().toISOString().slice(0, 10);
  const yr = getRates(asOf);   // 산정 기준일의 연도 자동 인식
  if (yr.stale) warn.push(yr.staleWarning);
  // 미입력 판정은 존재 여부로 한다(== null 은 '' 를 놓쳐, 빈칸이 '출근율 0' 으로 읽혔다.
  // 그 결과 §60② 분기로 빠져 근속 7년차 연차 18일이 0일로 사라졌다).
  const att = _blank(input.attendanceRate) ? 1.0 : numNN(input.attendanceRate, 'attendanceRate');
  // 명시적 0 은 존중해 그대로 §60② 로 계산하되, 결과가 크게 달라지므로 사유를 고지한다.
  if (_explicitZero(input.attendanceRate))
    warn.push('출근율(attendanceRate)을 0으로 입력해 그대로 계산했습니다 — 출근율 80% 미만이라 §60②(직전 1년 중 개근한 개월 수)로 연차를 산정합니다. 정상 출근한 근로자라면 이 항목을 비워두거나 1.0 을 넣으세요.');
  if (att > 1) warn.push(`⚠️ 출근율(attendanceRate) 값이 ${att} 입니다 — 0~1 사이 비율로 넣으세요(80%면 0.8). 1을 넘으면 §60② 판정이 무력화됩니다.`);
  const basis = input.basis || '입사일';

  // fullAttendanceMonths: null/undefined 는 '미입력'(§60② 확인 요구) 신호라 num() 을 태우지 않고
  // 그대로 넘긴다. 값이 있으면 숫자로 강제 변환해 "5" 같은 문자열도 개근 5개월로 인식시킨다.
  const famIn = input.fullAttendanceMonths;
  const fam = (famIn === undefined || famIn === null || famIn === '')
    ? null : numNN(famIn, 'fullAttendanceMonths');

  if (bool(input.fiveUnder, 'fiveUnder')) {
    warn.push('5인 미만 사업장: 연차유급휴가(§60)·사용촉진(§61) 원칙 미적용. (취업규칙·계약으로 약정 시 그에 따름. 2027 상반기 5인 미만 연차 단계 확대 예정 — 시행 확인)');
  }

  const hireBased = byHire(hire, asOf, att, fam);
  if (hireBased.warn) warn.push(hireBased.warn);
  let granted, detail;

  if (basis === '회계연도') {
    // 회계연도 기준: 입사 첫해는 월차, 다음 회계연도 1.1에 전년 재직비례(15×재직일/365), 이후 매년 15+가산
    const fy = (input.fiscalStart || '01-01');
    const hireYear = D(hire).getFullYear();
    const firstFiscal = D(`${hireYear + 1}-${fy}`);  // 입사 다음 회계연도 시작
    const asOfD = D(asOf);
    const detailLines = [];
    if (asOfD < firstFiscal) {
      granted = hireBased.under1yMonthly;
      detailLines.push(`입사연도(첫 회계연도 도래 전): 월차 ${granted}일`);
    } else {
      const prevDays = daysBetween(hire, `${hireYear}-12-31`) + 1;
      const prorated = Math.round(A.baseDays * (prevDays / 365) * 10) / 10;
      // 회계연도 회차 = asOf 연도 - (입사 다음해) ... 단순화: 경과 회계연수
      const fiscalRounds = asOfD.getFullYear() - (hireYear + 1);
      // 가산은 입사일 기준 근속연수로 산정(불이익 금지)
      const tenureForBonus = hireBased.tenureYears;
      const regular = Math.min(A.maxDays, A.baseDays + Math.max(0, Math.floor((tenureForBonus - 1) / 2)) * A.bonusPer2yrs);
      granted = (fiscalRounds === 0) ? prorated : regular;
      detailLines.push(`첫 회계연도(${hireYear + 1}.${fy}) 비례부여: 15 × ${prevDays}/365 = ${prorated}일`);
      if (fiscalRounds > 0) detailLines.push(`이후 회계연도 정식부여: ${regular}일(가산은 입사일 기준 근속 ${tenureForBonus}년 반영)`);
      detailLines.push('⚠️ 퇴직 시 입사일 기준 누적과 비교해 부족분 추가지급 필수(불이익 금지).');
    }
    detail = { basis, lines: detailLines, hireBasedReference: hireBased };
    warn.push('회계연도 기준은 행정해석상 허용방식. 퇴직정산(입사일 기준 비교) 누락 시 연차수당 체불 리스크.');
  } else {
    granted = (hireBased.tenureYears < 1) ? hireBased.under1yMonthly : hireBased.annualByYear;
    detail = { basis, formula: hireBased.formula, ...hireBased };
  }

  // 미사용수당
  const used = numNN(input.usedDays, 'usedDays');
  if (used > granted)
    warn.push(`⚠️ 사용 연차(${used}일)가 부여 연차(${granted}일)를 초과합니다 — 잔여는 0일로 처리했습니다. 부여 기준(입사일/회계연도)·출근율 입력을 확인하세요.`);
  const unused = Math.max(0, granted - used);
  const dailyWage = numNN(input.ordinaryDailyWage, 'ordinaryDailyWage');
  const allowance = dailyWage > 0 ? Math.round(unused * dailyWage) : null;
  // 문자열 숫자 변환·해석 불가 입력을 경고로 올린다(조용한 소실 금지). 숫자 입력만이면 빈 배열.
  warn.push(..._drainCoerce());

  return {
    hireDate: hire, asOf, basis,
    grantedDays: granted,
    under1yMonthly: hireBased.under1yMonthly,
    tenureYears: hireBased.tenureYears,
    usedDays: used, unusedDays: unused,
    unusedAllowance: allowance,
    detail,
    meta: {
      asOf: yr.META.asOf, year: yr.year,
      expire: '발생일로부터 1년 미사용 시 소멸(사용촉진 적법이행 시 수당 면제)',
      promotion: A.promotion,
      warnings: warn,
    },
  };
}

// ── CLI ──────────────────────────────────────────────────────
const isMain = await (async () => { try { const { fileURLToPath } = await import("node:url"); const { realpathSync } = await import("node:fs"); return !!process.argv[1] && realpathSync(fileURLToPath(import.meta.url)) === realpathSync(process.argv[1]); } catch { return false; } })(); // 한글·공백 경로 견고(realpath 비교)
if (isMain) {
  const fs = await import('node:fs');
  const path = process.argv[2];
  if (!path) { console.error('사용법: node annual-leave.mjs <input.json>'); process.exit(1); }
  const r = calcAnnualLeave(JSON.parse(fs.readFileSync(path, 'utf8')));
  const w = n => n == null ? '-' : Number(n).toLocaleString('ko-KR');
  console.log(JSON.stringify(r, null, 2));
  console.log(`\n=== 연차 요약 (${r.basis} 기준) ===`);
  console.log(`입사 ${r.hireDate} → 기준일 ${r.asOf} (근속 ${r.tenureYears}년)`);
  console.log(`★ 부여 연차: ${r.grantedDays}일  (사용 ${r.usedDays} / 잔여 ${r.unusedDays})`);
  if (r.unusedAllowance != null) console.log(`미사용 연차수당: ${w(r.unusedAllowance)}원 (${r.unusedDays}일 × 1일 통상임금)`);
  if (r.meta.warnings.length) { console.log('\n[주의]'); r.meta.warnings.forEach(x => console.log(' - ' + x)); }
}

export default { calcAnnualLeave };
