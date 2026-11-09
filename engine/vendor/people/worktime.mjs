// 근로시간 분해 엔진 — 출퇴근 → 총근로/연장/야간/휴일 시간 + (선택)가산수당
// 근거: 근로기준법 §50·§54·§56. node 정확계산용.
// ⚠️ 금액(가산수당)의 정식 계산·급여 반영은 nomu-payroll/payroll.mjs.
//    이 엔진은 '시간 분해'가 본업이고, 통상시급을 주면 참고 가산수당도 표시.
//
// 사용:
//   import { calcWorktime, calcWeek } from './worktime.mjs';
//   node worktime.mjs <input.json>
//
// 하루 입력(day):
// {
//   in: '09:00', out: '24:00',     // 출근/퇴근(24:00·25:30 등 자정 넘김 허용)
//   breakMin: null,                // 휴게(분). null이면 법정 최소 자동 적용
//   holiday: false,                // 휴일근로 여부(주휴일·약정휴일)
//   ordinaryHourly: 0,             // 통상시급(주면 참고 가산수당 계산)
//   fiveUnder: false               // 5인 미만 → 가산 0
// }
// 주간 입력(week): { days: [day, ...], fiveUnder, ordinaryHourly }

import R, { getRates } from './rates-2026.mjs';
const W = R.WORKTIME;   // 가산율 §56 — 연도 무관(법 개정 전 불변)
// ── 입력 방어 공통 계약 (v3.4.2) ──────────────────────────────
// 결함 클래스 A(조용한 값 소실) 박멸용 공통 블록.
//   num(v, field)    숫자/숫자문자열("60", " 1,000 ")은 변환 + 변환 사실 경고.
//                    해석 불가(NaN·"abc"·객체)는 0 + '어떤 필드가 빠졌는지' 경고. 조용한 소실 금지.
//                    미입력(undefined/null/"")은 종전대로 조용히 0 — 정상 입력이므로 경고하지 않는다.
//                    ※ day.breakMin 은 null 이 '법정 최소 자동 적용' 신호라 여기 오기 전에 걸러진다.
//   numNN(v, field)  위 + 도메인상 음수 불가 필드(시간·임금)에서 음수 경고.
//   bool(v, field)   "false"/"0"/"N"/"아니오"/"없음" 등 문자열 falsy 를 올바로 해석 + 변환 경고.
//                    (기존 !! 는 fiveUnder:"false"·holiday:"false" 를 true 로 읽었다)
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

// 'HH:MM' → 분. 24:00=1440, 25:30(익일) 가능.
// 기존 구현은 num() 을 안 거치고 String(t).split(':').map(Number) 라
// in:'abc' 를 NaN 으로 만들어 workH·regularH·nightH 가 전부 null 로 전파되는데
// 경고가 0건이었다(출퇴근 오타 한 글자로 근로시간 전체가 사라짐).
function toMin(t, field) {
  if (typeof t === 'number' && isFinite(t)) return t * 60;     // 숫자 — 기존 동작 그대로(시 단위)
  if (t === undefined || t === null || t === '') {
    _coerceLog.push(`⚠️ 입력 "${field}"(출퇴근 시각)이 비어 있어 근로시간을 계산할 수 없습니다 — 'HH:MM' 형식으로 넣으세요(자정 넘김은 24:00·25:30 처럼).`);
    return null;
  }
  const s = String(t).trim();
  const m = s.match(/^(\d{1,2}):([0-5]?\d)$/);
  if (m) return (+m[1]) * 60 + (+m[2]);
  if (/^\d{1,2}(?:\.\d+)?$/.test(s)) {                          // '9' → 9시
    const n = Number(s);
    _coerceLog.push(`입력 "${field}" 값(${_show(t)})을 ${n}시로 해석했습니다 — 'HH:MM' 형식(예: "09:00")으로 넣으세요.`);
    return n * 60;
  }
  _coerceLog.push(`⚠️ 입력 "${field}" 값(${_show(t)})을 시각으로 해석할 수 없어 근로시간을 계산하지 않았습니다 — 'HH:MM' 형식으로 넣으세요(자정 넘김은 24:00·25:30 처럼).`);
  return null;
}

// 근무구간 [s,e](분)과 야간대(22:00~익일06:00)의 교집합 분
function nightOverlapMin(s, e) {
  // 야간대를 당일 1320~1800(22:00~30:00=익일6:00)로 표현, 필요시 전일 야간(-120~360)
  let total = 0;
  const segs = [[1320, 1800], [1320 + 1440, 1800 + 1440], [1320 - 1440, 1800 - 1440]];
  for (const [ns, ne] of segs) total += Math.max(0, Math.min(e, ne) - Math.max(s, ns));
  return total;
}

export function calcWorktime(day = {}) {
  _resetCoerce();   // 문자열→숫자 변환 기록은 이 호출분만 모은다
  const holiday = bool(day.holiday, 'holiday');
  const s = toMin(day.in, 'in'), eRaw = toMin(day.out, 'out');
  // 시각을 해석하지 못하면 null 을 계산에 흘려보내지 않고 '계산 안 함(0)'으로 명시 종료한다.
  // 예전엔 workH:null·regularH:null 이 경고 없이 주간 합산·급여 입력까지 전파됐다.
  if (s === null || eRaw === null) {
    return {
      presentH: 0, breakMin: 0, workH: 0, regularH: 0, overtimeH: 0,
      holiday8H: 0, holidayOverH: 0, nightH: 0, holiday, pay: null,
      calculated: false, warnings: _drainCoerce(),
    };
  }
  // 출근·퇴근이 같은 시각이면 '자정 넘김' 으로 보아 24시간이 된다(기존 동작). 0시간을 뜻한
  // 입력이었다면 재실 24h·연장 15h 가 경고 없이 주52시간 판정에 실린다 → 반드시 고지한다.
  if (eRaw === s)
    _coerceLog.push(`⚠️ 출근·퇴근 시각(${_show(day.in)} → ${_show(day.out)})이 같습니다 — 자정을 넘겨 24시간 근무한 것으로 계산했습니다(재실 24시간). 그 날 근무가 없었다는 뜻이라면 해당 일자를 입력에서 빼거나 실제 퇴근 시각을 넣으세요.`);
  const e = eRaw <= s ? eRaw + 1440 : eRaw;   // 자정 넘김 보정
  const presentMin = e - s;                    // 재실시간
  // 미입력 판정은 존재 여부로 한다(== null 은 '' 를 놓쳐, 빈칸이 '휴게 0분' 으로 읽혔다).
  const breakMin = _blank(day.breakMin) ? W.breakMinutes(presentMin) : numNN(day.breakMin, 'breakMin');
  // 명시적 0분은 존중한다(그대로 계산). 다만 법정 최소 휴게가 있는 길이면 반드시 고지한다 —
  // 조용히 두면 휴게 없는 근무가 실근로·연장근로로 그대로 급여·주52시간 판정에 실린다.
  if (_explicitZero(day.breakMin) && W.breakMinutes(presentMin) > 0)
    _coerceLog.push(`⚠️ 휴게시간(breakMin)을 0분으로 입력해 그대로 계산했습니다 — 재실 ${(presentMin / 60).toFixed(1)}시간이면 근로기준법 §54 상 최소 ${W.breakMinutes(presentMin)}분의 휴게를 근로시간 도중에 주어야 합니다. 실제로 휴게를 부여했다면 그 시간을 입력하세요(실근로시간·연장근로가 과다 산정됩니다).`);
  const workMin = Math.max(0, presentMin - breakMin);  // 실근로
  const workH = workMin / 60;

  // 야간 겹침: 근무구간과 야간대(22~06)의 교집합.
  // 휴게는 보통 주간(점심)에 부여되므로 야간시간에서 차감하지 않는다.
  // 휴게가 야간대에 걸치면 breakInNightMin으로 명시 차감(미지정 시 0).
  const nightMin = Math.min(workMin, Math.max(0, nightOverlapMin(s, e) - numNN(day.breakInNightMin, 'breakInNightMin')));
  const nightH = nightMin / 60;

  const std = W.dailyLegalHours; // 8
  let regularH = 0, overtimeH = 0, holiday8H = 0, holidayOverH = 0;
  if (!holiday) {
    regularH = Math.min(workH, std);
    overtimeH = Math.max(0, workH - std);
  } else {
    holiday8H = Math.min(workH, std);
    holidayOverH = Math.max(0, workH - std);
  }

  // (선택) 참고 가산수당
  const wage = numNN(day.ordinaryHourly, 'ordinaryHourly');
  const fiveUnder = bool(day.fiveUnder, 'fiveUnder');
  let pay = null;
  if (wage > 0) {
    if (fiveUnder) {
      pay = { base: Math.round(wage * workH), overtimeAdd: 0, nightAdd: 0, holidayAdd: 0,
              total: Math.round(wage * workH), note: '5인 미만 §56 미적용(가산 0). 2026 하반기 확대 예정 — 시행 확인' };
    } else {
      const otAdd = wage * overtimeH * W.rateOvertime;
      const niAdd = wage * nightH * W.rateNight;
      const h8Add = wage * holiday8H * W.rateHolidayWithin8;
      const hoAdd = wage * holidayOverH * (W.rateHolidayOver8); // 8h초과 가산 100%(=1.0), 휴일근로 8h초과는 총 2.0배
      pay = {
        base: Math.round(wage * workH),
        overtimeAdd: Math.round(otAdd), nightAdd: Math.round(niAdd),
        holidayAdd: Math.round(h8Add + hoAdd),
        total: Math.round(wage * workH + otAdd + niAdd + h8Add + hoAdd),
      };
    }
  }

  // 문자열 숫자 변환·해석 불가 입력 경고(조용한 소실 금지).
  // 숫자 입력만이면 키 자체를 만들지 않아 기존 출력과 바이트 단위로 동일하다.
  const coerced = _drainCoerce();
  return {
    presentH: +(presentMin / 60).toFixed(2), breakMin,
    workH: +workH.toFixed(2),
    regularH: +regularH.toFixed(2), overtimeH: +overtimeH.toFixed(2),
    holiday8H: +holiday8H.toFixed(2), holidayOverH: +holidayOverH.toFixed(2),
    nightH: +nightH.toFixed(2),
    holiday, pay,
    ...(coerced.length ? { warnings: coerced } : {}),
  };
}

// 주간 합산 + 주52시간 점검
export function calcWeek(week = {}) {
  // 미지정 판정은 존재 여부로 한다(v3.4.5). `=== undefined || === null` 은 빈칸('')을 놓쳐,
  // CSV·양식에서 비워 둔 fiveUnder 가 '명시적 아니오(5인 이상)' 로 뒤집혔다 — 5인 미만 사업장인데
  // 주52시간 초과 경고가 뜨고 §56 가산수당이 붙었다(일자별 fiveUnder 를 무시).
  const yr = getRates(_blank(week.year) ? week.date : week.year);   // 계산 연도 자동 인식(미지정 시 오늘)
  _resetCoerce();
  const weekFiveUnder = _blank(week.fiveUnder)
    ? null : bool(week.fiveUnder, 'fiveUnder');
  const weekCoerce = _drainCoerce();   // 주 단위 불리언 변환 경고(일자별 계산이 로그를 비우기 전에 확보)
  // 주 단위 값이 '비어 있으면' 일자별 값으로 내린다. `??` 는 '' 를 값으로 보아 일자별 시급·5인미만
  // 지정을 덮어썼다. 명시적 0(시급 0원)은 여전히 값이므로 그대로 내려간다(0 존중).
  const days = (week.days || []).map(d => calcWorktime({ ...d,
    fiveUnder: _blank(week.fiveUnder) ? d.fiveUnder : week.fiveUnder,
    ordinaryHourly: _blank(week.ordinaryHourly) ? d.ordinaryHourly : week.ordinaryHourly }));
  const sum = k => +days.reduce((a, d) => a + (d[k] || 0), 0).toFixed(2);
  const legalWork = sum('regularH') + sum('holiday8H'); // 소정+휴일8h이내(법정근로 성격)
  const overtime = sum('overtimeH') + sum('holidayOverH');
  const weeklyTotal = sum('workH');
  const weekdayWork = sum('regularH') + sum('overtimeH'); // 평일 실근로(소정+1일초과연장)
  // 주52시간 한도는 '1주'(휴일 포함, §2①7) 총근로 기준 — 휴일근로도 산입(§53·대법 2020다).
  const over52 = weeklyTotal > W.weeklyMaxHours;
  // 주 40시간 초과분은 1일 8h 초과가 아니어도 추가 연장근로 → 별도 가산 필요
  const weeklyOvertimeExtra = Math.max(0, sum('regularH') - W.weeklyLegalHours);
  const warn = [];
  // fiveUnder 는 "false" 같은 문자열도 정확히 해석한다(기존 truthy 판정은 5인 미만 오판을 냈다).
  const fiveUnder = weekFiveUnder === null
    ? (week.days || []).length > 0 && (week.days || []).every(d => bool(d.fiveUnder, 'fiveUnder'))
    : weekFiveUnder;
  if (over52 && !fiveUnder)
    warn.push(`주 52시간(법정40+연장12) 초과 가능성. 휴일근로 포함 1주 총근로 ${weeklyTotal.toFixed(1)}h — 연장근로 한도 위반 점검 필요(§53).`);
  if (weeklyOvertimeExtra > 0 && !fiveUnder)
    warn.push(`주 소정근로 합계가 40h를 ${weeklyOvertimeExtra.toFixed(1)}h 초과 — 1일 8h 이내라도 주40h 초과분은 추가 연장근로로 가산 필요(§53·§56). 엔진의 overtimeH(${sum('overtimeH')}h)에 이 ${weeklyOvertimeExtra.toFixed(1)}h를 더해 가산수당을 산정하세요.`);
  if (fiveUnder) warn.push('5인 미만: 주52시간제·연장한도·가산수당 원칙 미적용(2026 하반기 단계 확대 예정 — 시행 확인).');
  if (yr.stale) warn.push(yr.staleWarning);
  // 시각 해석 실패로 계산되지 않은 날이 있으면 주간 합계가 과소 집계된다 — 반드시 알린다.
  const uncalced = days.filter(d => d.calculated === false).length;
  if (uncalced > 0)
    warn.push(`⚠️ ${uncalced}일치 출퇴근 시각을 해석하지 못해 주간 합계에서 빠졌습니다 — 주52시간 판정이 실제보다 낮게 나올 수 있습니다. 해당 일자의 in/out 을 'HH:MM' 형식으로 고치세요.`);
  // 주 단위 + 일자별 입력 강제변환·무시 경고를 주간 경고로 승격(중복 제거).
  // 숫자·불리언 입력만이면 아무것도 추가되지 않는다.
  warn.push(...new Set([...weekCoerce, ..._drainCoerce(), ...days.flatMap(d => d.warnings || [])]));
  return {
    days,
    weekly: { workH: weeklyTotal, regularH: sum('regularH'), overtimeH: sum('overtimeH'),
              nightH: sum('nightH'), holiday8H: sum('holiday8H'), holidayOverH: sum('holidayOverH') },
    weeklyOvertimeExtra,
    // ▼ nomu-payroll/payroll.mjs 입력 키로 그대로 복붙(필드명 매핑 마찰 제거)
    payrollInput: {
      overtimeHours: +(sum('overtimeH') + weeklyOvertimeExtra).toFixed(2),
      nightHours: sum('nightH'),
      holidayHoursWithin8: sum('holiday8H'),
      holidayHoursOver8: sum('holidayOverH'),
    },
    over52, warnings: warn, year: yr.year, asOf: yr.META.asOf,
  };
}

// ── CLI ──────────────────────────────────────────────────────
const isMain = await (async () => { try { const { fileURLToPath } = await import("node:url"); const { realpathSync } = await import("node:fs"); return !!process.argv[1] && realpathSync(fileURLToPath(import.meta.url)) === realpathSync(process.argv[1]); } catch { return false; } })(); // 한글·공백 경로 견고(realpath 비교)
if (isMain) {
  const fs = await import('node:fs');
  const path = process.argv[2];
  if (!path) { console.error('사용법: node worktime.mjs <input.json>  (day 또는 {days:[...]})'); process.exit(1); }
  const input = JSON.parse(fs.readFileSync(path, 'utf8'));
  const r = input.days ? calcWeek(input) : calcWorktime(input);
  console.log(JSON.stringify(r, null, 2));
}

export default { calcWorktime, calcWeek };
