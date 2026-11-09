// 노무 서류 도우미 — 계산 다리(bridge)
// 원본 엔진(vendor/*.mjs, nomu-payroll·nomu-people v3.4.8)은 고치지 않고 그대로 부른다.
// 이 파일은 (1) 입력 JSON 을 stdin 으로 받고 (2) 원본 엔진을 부르고
// (3) 아래 두 가지만 덧씌운 뒤 (4) 결과 JSON 을 stdout 으로 낸다.
//   ① 건강보험·장기요양 근로자 몫을 10원 미만 절사(4대사회보험 정보연계센터 모의계산 방식).
//      원본은 1원 단위라 공단 고지액과 몇 원~수십 원 어긋난다. [확인 필요: 공단 고지액 대조]
//   ② 원본 경고문 중 "2026 하반기 5인 미만 가산수당 확대 예정"은 원본 v3.4.7 에서 스스로
//      반증한 문장이라 고친 문장으로 바꾼다.
//   ③ 원본 엔진에 아직 없는 연도의 최저임금(MINWAGE_EXTRA, 지금은 2027)을 기준일 연도에 맞춰
//      최저임금 판정에 쓴다. 4대보험·간이세액표 2027 값은 아직 없으므로 원본의 '미등록 연도' 경고는
//      최저임금 부분만 고쳐 그대로 남긴다.
// 사용:  echo '{"op":"payroll","input":{...}}' | node calc.mjs
import { calcPayroll, checkMinimumWage, hourlyToMonthly } from './vendor/payroll.mjs';
import { calcWeek, calcWorktime } from './vendor/people/worktime.mjs';
import { calcAnnualLeave } from './vendor/people/annual-leave.mjs';
import { lookupWithholding } from './vendor/income-tax-table-2026.mjs';
import { getRates } from './vendor/rates-2026.mjs';

// ── 원본 엔진에 없는 연도의 최저임금 (공식 고시에서 확인한 값만) ──
// 2027: 고용노동부고시 제2026-60호(2026. 8. 5. 고시), 적용 2027-01-01 ~ 2027-12-31.
//       시간급 10,700원 · 월 환산 2,236,300원(209시간). 업종 구분 없음. 확인일 2026-11-09.
//       https://www.moel.go.kr/info/lawinfo/instruction/view.do?bbs_seq=20260800150
export const MINWAGE_EXTRA = {
  2027: {
    hour: 10700, month209: 2236300,
    notice: '고용노동부고시 제2026-60호', noticeDate: '2026-08-05',
    from: '2027-01-01', to: '2027-12-31',
    src: '고용노동부 2027년 적용 최저임금 고시(고용노동부고시 제2026-60호, 시급 10,700원). 최저임금법 §5·§6·§28',
  },
};
const MW_ENGINE_SRC = { 2026: { notice: '고용노동부고시 제2025-47호' } };

function yearOf(v) {
  if (v == null) return null;
  if (typeof v === 'number' && isFinite(v)) return Math.trunc(v);
  const m = String(v).match(/(\d{4})/);
  return m ? +m[1] : null;
}

// 기준일 연도의 최저임금 정보. registered=false 면 등록된 가장 가까운 앞 연도 값으로 대신한 것.
export function minWageFor(yearOrDate) {
  const req = yearOf(yearOrDate) ?? new Date().getFullYear();
  const base = getRates(2026).MINWAGE;
  const table = {};
  for (const k of Object.keys(base)) if (/^\d{4}$/.test(k)) table[+k] = { ...base[k], notice: MW_ENGINE_SRC[k]?.notice ?? null, src: +k === base.current ? base.src : `${k}년 적용 최저임금(원본 엔진 표, 시급 ${base[k].hour.toLocaleString()}원)` };
  for (const [k, v] of Object.entries(MINWAGE_EXTRA)) table[+k] = { ...v };
  const years = Object.keys(table).map(Number).sort((a, b) => a - b);
  if (table[req]) return { year: req, usingYear: req, registered: true, ...table[req] };
  const prev = years.filter((y) => y < req).pop() ?? years[0];
  return { year: req, usingYear: prev, registered: false, ...table[prev] };
}

const STALE_RE = /^⚠️ (\d{4})년 요율이 이 엔진에 등록돼 있지 않습니다/;

// 원본의 미등록 연도 경고 — 최저임금은 이 다리에 등록돼 있으면 그 사실을 바로 적는다.
function fixStale(w) {
  const m = String(w).match(STALE_RE);
  if (!m) return w;
  const y = +m[1];
  if (!MINWAGE_EXTRA[y]) return w;
  return `⚠️ ${y}년 4대보험 요율·간이세액표가 이 엔진에 아직 등록돼 있지 않아 2026년 값으로 계산했습니다. 실제와 다를 수 있습니다. ` +
    `공단 고지액·국세청 간이세액표로 확인하거나 override 하십시오. 특히 국민연금 보험료율은 2027-01-01 9.5% → 10.0% 인상이 예정돼 있어 ` +
    `2027년 급여를 2026년 요율로 계산하면 공제액이 과소 산정됩니다. (최저임금은 ${y}년 값 ${MINWAGE_EXTRA[y].hour.toLocaleString()}원으로 판정 — ${MINWAGE_EXTRA[y].notice})`;
}

// 원본 checkMinimumWage 결과를 기준일 연도 최저임금으로 다시 판정한다(산입·제외 분해와 시간 환산은 원본 그대로).
function minwageYearAware(input) {
  const r = checkMinimumWage(input);
  const date = input.year ?? input.payDate ?? input.payPeriodEnd;
  const M = minWageFor(date);
  const engineYear = r.usingYear;
  const baseWarn = (r.warnings || []).filter((w) => !STALE_RE.test(w));
  if (M.usingYear === engineYear && M.registered) {
    return { ...r, minWageYear: M.usingYear, minWageNotice: M.notice, warnings: r.warnings };
  }
  const hour = M.hour;
  const probEligible = !!(r.probation && /^수습 감액 적용/.test(r.probation.note || ''));
  const applied = probEligible ? Math.ceil(hour * 0.9) : hour;
  const hours = r.hours;
  const comparable = r.comparableWage;
  const eff = hours > 0 ? comparable / hours : 0;
  const minMonthly = Math.round(applied * hours);
  const violated = comparable > 0 && eff < applied;
  const warn = baseWarn.filter((w) => !w.startsWith('🔴') && !/^수습/.test(w));
  if (!M.registered) {
    warn.unshift(`⚠️ ${M.year}년 최저임금이 아직 등록돼 있지 않습니다. ${M.usingYear}년 값(시급 ${hour.toLocaleString()}원)으로 판정했으므로 실제와 다를 수 있습니다. ${M.year}년 최저임금 고시를 확인하세요.`);
  }
  let probation = r.probation;
  if (r.probation) {
    const note = probEligible
      ? `수습 감액 적용(§5②·시행령 §3): 1년 이상 계약 + 수습 3개월 이내 + 단순노무 아님 → 최저 시급의 90%(${applied.toLocaleString()}원)`
      : String(r.probation.note || '').replace(/최저 시급 [\d,]+원/, `최저 시급 ${hour.toLocaleString()}원`);
    probation = { applied: applied < hour, note };
    warn.push(note);
  }
  const shortfallMonthly = violated ? Math.round(minMonthly - comparable) : 0;
  if (violated)
    warn.push(`🔴 최저임금 위반 소지: 산입임금 시간급 ${Math.floor(eff).toLocaleString()}원 < 최저 시급 ${applied.toLocaleString()}원. 월 ${shortfallMonthly.toLocaleString()}원 부족(최저임금법 §6① 위반 시 3년 이하 징역 또는 2천만원 이하 벌금 §28①).`);
  const basis = [...(r.basis || [])];
  basis[0] = `${M.usingYear}년 최저임금 시급 ${hour.toLocaleString()}원 · 월 환산(209h) ${M.month209.toLocaleString()}원 — ${M.src}`;
  return {
    ...r,
    year: M.year, usingYear: M.usingYear, minWageYear: M.usingYear, minWageNotice: M.notice, minWageRegistered: M.registered,
    minHourly: hour, appliedMinHourly: applied, minMonthly,
    violated,
    shortfallHourly: violated ? Math.ceil(applied - eff) : 0,
    shortfallMonthly,
    signal: comparable <= 0 ? '⚪ 판정 불가(입력 부족)' : violated ? '🔴 최저임금 위반 소지' : '🟢 최저임금 이상',
    probation,
    basis,
    warnings: warn,
  };
}

const floor10 = (v) => Math.floor((v + 1e-6) / 10) * 10;
const FIXED_FIVE_UNDER =
  '5인 미만: 근로기준법 §56 가산수당 미적용으로 계산(근로한 시간만큼 1.0배만). 2026-11 기준 시행령 별표1 개정 시행 사실 없음 — 발급 전 국가법령정보센터에서 한 번 더 확인하세요.';

function fixWarnings(list) {
  return (list || []).map((w) =>
    /2026 하반기 5인 미만 가산수당/.test(w) ? FIXED_FIVE_UNDER : fixStale(w));
}

function payroll(input) {
  const r = calcPayroll(input);
  const ov = input.rateOverride || {};
  const d = r.deductions;
  // ① 10원 절사 보정 (건강보험 요율 0% 적용제외면 그대로 0)
  if (d.healthInsurance > 0 && !input.keepEngineRounding) {
    const R = getRates(input.year ?? input.payDate ?? input.payPeriodEnd);
    const hiRate = Number(ov.health) > 0 ? Number(ov.health) : R.INSURANCE.health.rateTotal;
    const taxable = r.earnings.taxableGross;
    const I = R.INSURANCE.health;
    let total = taxable * hiRate;
    total = Math.min(Math.max(total, I.premiumFloorTotal), I.premiumCapTotal);
    const hi = floor10(total / 2);
    const ltc = floor10(hi * (R.INSURANCE.longTermCare.rateOfSalary / hiRate));
    const delta = (d.healthInsurance - hi) + (d.longTermCare - ltc);
    d.engineRounding = { healthInsurance: d.healthInsurance, longTermCare: d.longTermCare };
    d.healthInsurance = hi;
    d.longTermCare = ltc;
    d.insuranceTotal -= delta;
    d.totalDeductions -= delta;
    r.netPay += delta;
    d.roundingNote = '건강보험·장기요양은 10원 미만 절사(4대사회보험 정보연계센터 모의계산 방식). 실제 금액은 공단 고지액이 기준입니다.';
  }
  // ③ 최저임금 판정을 기준일 연도 값으로(원본은 미등록 연도를 2026 값으로 판정)
  const mw = minwageYearAware(input);
  r.minimumWage = mw;
  r.meta.warnings = fixWarnings((r.meta.warnings || []).filter((w) => !w.startsWith('🔴 최저임금')))
    .concat(mw.violated ? mw.warnings.filter((w) => w.startsWith('🔴')) : []);
  return r;
}

const ops = {
  payroll: (i) => payroll(i),
  minwage: (i) => minwageYearAware(i),
  minwageFor: (i) => minWageFor(i.year ?? i.date),
  hourlyToMonthly: (i) => hourlyToMonthly(i.hourlyWage, i.weeklyHours),
  week: (i) => { const r = calcWeek(i); if (r.warnings) r.warnings = fixWarnings(r.warnings); return r; },
  day: (i) => calcWorktime(i),
  annualLeave: (i) => { const r = calcAnnualLeave(i); if (r.warnings) r.warnings = fixWarnings(r.warnings); return r; },
  withholding: (i) => ({ tax: lookupWithholding(i.taxable, i.family) }),
  rates: (i) => {
    const R = getRates(i.year ?? 2026);
    const M = minWageFor(i.year ?? 2026);
    // MINWAGE 는 원본 표에 이 다리의 추가 연도(MINWAGE_EXTRA)를 더해 돌려준다. 4대보험·세율은 원본 그대로.
    const MW = { ...R.MINWAGE };
    for (const [k, v] of Object.entries(MINWAGE_EXTRA)) MW[k] = { hour: v.hour, month209: v.month209, notice: v.notice };
    return { year: R.year, usingYear: R.usingYear, stale: R.stale, MINWAGE: MW, minWage: M, INSURANCE: R.INSURANCE, INCOME_TAX: R.INCOME_TAX };
  },
};

let buf = '';
process.stdin.setEncoding('utf8');
process.stdin.on('data', (c) => (buf += c));
process.stdin.on('end', () => {
  try {
    const { op, input } = JSON.parse(buf || '{}');
    if (!ops[op]) throw new Error(`알 수 없는 op: ${op}`);
    process.stdout.write(JSON.stringify({ ok: true, result: ops[op](input || {}) }));
  } catch (e) {
    process.stdout.write(JSON.stringify({ ok: false, error: String(e && e.message || e) }));
    process.exitCode = 1;
  }
});
