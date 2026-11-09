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
//   ④ (v1.2) 연도 기준을 항목별로 나눈다.
//      · 소득세·지방소득세 = 지급일 기준(소득세법 §134①, 시행령 §194①, 지방세법 §103의13①). 원본 그대로.
//      · 4대보험 = 몇 월분 보험료인지(보험료 귀속월) 기준. 입력 insuranceMonth(YYYY-MM),
//        없으면 임금계산기간(periodTo → periodFrom)의 달, 그것도 없으면 지급일의 달.
//        (국민연금법 §88②, 국민건강보험법 §69④, 고용산재보험료징수법 §16의3①, 각 요율 개정 부칙의 「○월분 보험료」 적용례)
//      · 2027 국민연금 요율은 INSURANCE_EXTRA 에 원문 확인값만 넣었다. 원문으로 확인 안 된 요율은 등록하지 않고
//        결과에 [확인 필요]로 남긴다(2026 값으로 임시 계산).
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

// ── 원본 엔진에 없는 연도의 4대보험 요율 (법령 원문으로 확인한 값만) ──
// null 인 항목 = 원문으로 확인 못 해 등록하지 않음 → [확인 필요] + 2026 값으로 임시 계산.
export const INSURANCE_EXTRA = {
  2027: {
    nationalPension: {
      rateTotal: 0.10, rateWorker: 0.05,
      src: '국민연금법 부칙(법률 제20903호, 2025. 4. 2.) 제4조제1항제2호 「2027년은 1만분의 500」 — 기여금(근로자)·부담금(사용자) 각각',
      checked: '2026-11-09',
      checkedVia: '법제처 국가법령정보(korean-law 연결) 국민연금법 부칙 원문',
    },
    health: null,        // [확인 필요] 2027 건강보험료율 — 2027-01-01 시행예정 시행령 §44도 1만분의 719(2026과 같음), 별도 결정 여부 미확인
    longTermCare: null,  // [확인 필요] 2027 장기요양보험료율
    employment: null,    // [확인 필요] 2027 고용보험료율(현행 시행령 §12 실업급여 1천분의 18)
  },
};
const ENGINE_INS_YEARS = [2026]; // 원본 엔진(rates-2026.mjs)에 4대보험 요율이 다 들어 있는 연도
const INS_LABEL = { nationalPension: '국민연금', health: '건강보험', longTermCare: '장기요양보험', employment: '고용보험' };

// 국민연금 기준소득월액 상·하한 적용기(보험료 귀속월 기준). 보건복지부고시 제2026-31호(2026.7~2027.6) 등.
const NP_BASE_PERIODS = [
  { from: '2026-01', to: '2026-06', key: '2026H1', label: '2026.1~2026.6' },
  { from: '2026-07', to: '2027-06', key: '2026H2', label: '2026.7~2027.6' },
];

export const GUIDANCE = [
  '4대보험 최종 금액은 공단 고지액을 따릅니다.',
  '지급일은 실제 준 날짜를 넣어야 합니다.',
];

function ymOf(v) {
  if (v == null || v === '') return null;
  const m = String(v).trim().match(/^(\d{4})-(\d{1,2})(?:-\d{1,2})?$/);
  if (!m) return null;
  const mo = +m[2];
  if (mo < 1 || mo > 12) return null;
  return `${m[1]}-${String(mo).padStart(2, '0')}`;
}

// 보험료 귀속월 정하기: insuranceMonth → 임금계산기간(끝날 → 시작날)의 달 → 지급일의 달
export function insuranceMonthOf(input) {
  const notes = [];
  if (input.insuranceMonth != null && input.insuranceMonth !== '') {
    const ym = /^\d{4}-\d{2}$/.test(String(input.insuranceMonth).trim()) ? ymOf(input.insuranceMonth) : null;
    if (ym) return { month: ym, source: 'insuranceMonth', notes };
    notes.push(`⚠️ 입력 "insuranceMonth" 값(${JSON.stringify(input.insuranceMonth)})을 몇 월분 보험료(YYYY-MM)로 읽을 수 없어 임금계산기간의 달로 계산했습니다 — 예: 2026-12.`);
  }
  for (const [k, src] of [['periodTo', 'periodTo'], ['periodFrom', 'periodFrom'], ['payPeriodEnd', 'periodTo']]) {
    const ym = ymOf(input[k]);
    if (ym) return { month: ym, source: src, notes };
  }
  const ym = ymOf(input.payDate);
  if (ym) return { month: ym, source: 'payDate', notes };
  const d = new Date();
  return { month: `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}`, source: 'today', notes };
}

function npPeriodFor(ym) {
  const hit = NP_BASE_PERIODS.find((p) => ym >= p.from && ym <= p.to);
  if (hit) return { ...hit, registered: true };
  const fb = ym < NP_BASE_PERIODS[0].from ? NP_BASE_PERIODS[0] : NP_BASE_PERIODS[NP_BASE_PERIODS.length - 1];
  return { ...fb, registered: false };
}

// 귀속월 연도의 4대보험 요율 상태. confirmed=false 면 [확인 필요](2026 값으로 임시 계산).
function insuranceRatesFor(year) {
  const R = getRates(2026).INSURANCE;
  const engineOk = ENGINE_INS_YEARS.includes(year);
  const extra = INSURANCE_EXTRA[year] || {};
  const items = {};
  const base = {
    nationalPension: { rateWorker: R.nationalPension.rateWorker, rateTotal: R.nationalPension.rateTotal, src: '국민연금법 부칙(법률 제20903호) 제4조제1항제1호 「2026년은 1만분의 475」' },
    health: { rateWorker: R.health.rateWorker, rateTotal: R.health.rateTotal, src: R.health.src },
    longTermCare: { rateOfSalary: R.longTermCare.rateOfSalary, src: R.longTermCare.src },
    employment: { rateWorker: R.employment.rateWorker, src: R.employment.src },
  };
  for (const k of Object.keys(INS_LABEL)) {
    if (engineOk) items[k] = { ...base[k], year, confirmed: true };
    else if (extra[k]) items[k] = { ...base[k], ...extra[k], year, confirmed: true };
    else items[k] = { ...base[k], year, usingYear: 2026, confirmed: false, src: `[확인 필요] ${year}년 요율 원문 미확인 — 2026년 요율로 임시 계산` };
  }
  return items;
}

const pct = (x) => { const v = Number((x * 100).toFixed(3)); return `${v.toFixed(Math.max(2, (String(v).split('.')[1] || '').length))}%`; };


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

const NP_PERIOD_RE = /^⚠️ 국민연금 기준소득월액 상·하한 적용기\(pensionPeriod\)/;

function fixWarnings(list) {
  return (list || []).map((w) =>
    /2026 하반기 5인 미만 가산수당/.test(w) ? FIXED_FIVE_UNDER : fixStale(w));
}

function payroll(input) {
  // ④ 연도 기준을 항목별로 — 소득세는 지급일, 4대보험은 보험료 귀속월
  const IM = insuranceMonthOf(input);
  const insYear = +IM.month.slice(0, 4);
  const NP = npPeriodFor(IM.month);
  const insItems = insuranceRatesFor(insYear);
  const userPensionPeriod = input.pensionPeriod || null;
  const pensionPeriod = userPensionPeriod || NP.key;
  const ov = input.rateOverride || {};
  const ovIns = { ...ov };
  // 귀속연도가 원본 엔진에 없고 원문 확인 요율이 있으면 그 요율을 쓴다(사장님 override 가 있으면 그게 우선).
  if (!ENGINE_INS_YEARS.includes(insYear) && insItems.nationalPension.confirmed && (ov.nationalPension === undefined || ov.nationalPension === null || ov.nationalPension === ''))
    ovIns.nationalPension = insItems.nationalPension.rateTotal;

  // (가) 소득세·지방소득세 계산용 — 지급일 기준(원본 그대로)
  const r = calcPayroll({ ...input, pensionPeriod });
  // (나) 4대보험 계산용 — 귀속월 기준. 연도는 귀속월, 국민연금 상·하한 적용기도 귀속월로.
  const insInput = { ...input, year: insYear, pensionPeriod, rateOverride: ovIns };
  const ri = calcPayroll(insInput);
  const d = r.deductions;
  const di = ri.deductions;
  for (const k of ['nationalPension', 'healthInsurance', 'longTermCare', 'employmentInsurance', 'industrialAccident', 'insuranceTotal'])
    d[k] = di[k];
  d.totalDeductions = d.insuranceTotal + d.incomeTax + d.localIncomeTax + d.otherDeductions;
  r.netPay = r.earnings.grossPay - d.totalDeductions;
  r.input.pensionPeriod = ri.input.pensionPeriod;

  // ① 10원 절사 보정 (건강보험 요율 0% 적용제외면 그대로 0) — 귀속월 연도의 요율로
  if (d.healthInsurance > 0 && !input.keepEngineRounding) {
    const R = getRates(insYear);
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
  //    기준일 = 임금계산기간 끝날 → 시작날 → 지급일 (generate.py 와 같은 순서)
  const mwDate = input.year ?? input.periodTo ?? input.periodFrom ?? input.payDate ?? input.payPeriodEnd;
  const mw = minwageYearAware({ ...input, payDate: mwDate });
  r.minimumWage = mw;

  // 경고 정리: 원본의 미등록 연도 경고·적용기 경고는 아래 항목별 문장으로 바꾼다.
  const payYear = yearOf(input.payDate ?? input.payPeriodEnd) ?? new Date().getFullYear();
  const taxStale = getRates(payYear).stale;
  const unconfirmed = Object.keys(INS_LABEL).filter((k) => !insItems[k].confirmed);
  const engineWarn = (r.meta.warnings || []).filter((w) => !w.startsWith('🔴 최저임금') && !STALE_RE.test(w) && !NP_PERIOD_RE.test(w));
  const extraWarn = [...IM.notes];
  const insLabel = `${insYear}년 ${+IM.month.slice(5)}월분`;
  const payDateStr = input.payDate || '(지급일 없음)';
  const mwNote = MINWAGE_EXTRA[mw.minWageYear] ? ` (최저임금은 ${mw.minWageYear}년 값 ${MINWAGE_EXTRA[mw.minWageYear].hour.toLocaleString()}원으로 판정 — ${MINWAGE_EXTRA[mw.minWageYear].notice})` : '';
  const insTail = unconfirmed.length
    ? `${insLabel} 보험료의 ${unconfirmed.map((k) => INS_LABEL[k]).join('·')} 요율은 원문으로 확인되지 않아 등록하지 않았고 2026년 요율로 임시 계산했습니다 [확인 필요].` +
      (insItems.nationalPension.confirmed && !ENGINE_INS_YEARS.includes(insYear) ? ` 국민연금은 ${insYear}년 요율(근로자 ${pct(insItems.nationalPension.rateWorker)})을 반영했습니다 — ${insItems.nationalPension.src}.` : '')
    : '';
  if (taxStale && unconfirmed.length && insYear === payYear) {
    extraWarn.push(`⚠️ ${payYear}년 4대보험 요율·간이세액표 중 원문으로 확인 안 된 값이 있습니다 [확인 필요]. 소득세는 지급일(${payDateStr}) 기준으로 현행 간이세액표(2026-03-01 시행)를 썼습니다(${payYear}년 개정 여부 확인 필요). ${insTail} 공단 고지액·국세청 간이세액표로 확인하세요.${mwNote}`);
  } else {
    if (taxStale)
      extraWarn.push(`소득세: 지급일(${payDateStr}) 기준으로 현행 간이세액표(2026-03-01 시행)를 썼습니다. ${payYear}년에 간이세액표가 바뀌었는지는 [확인 필요] — 국세청 간이세액표로 확인하세요.${mwNote}`);
    if (unconfirmed.length)
      extraWarn.push(`⚠️ 4대보험: ${insTail} 공단 고지액으로 확인하세요.`);
  }
  if (!userPensionPeriod && !NP.registered)
    extraWarn.push(`⚠️ 국민연금 기준소득월액 상·하한: ${insLabel}에 맞는 적용기가 아직 등록돼 있지 않아 ${NP.label} 표(${NP.key})로 임시 계산했습니다 [확인 필요]. 고소득자는 공제액이 달라질 수 있습니다.`);
  r.meta.warnings = fixWarnings(engineWarn).concat(extraWarn)
    .concat(mw.violated ? mw.warnings.filter((w) => w.startsWith('🔴')) : []);

  // 결과에 기준을 적는다(서류·점검결과.json 에 그대로 실림)
  const srcLabel = { insuranceMonth: '입력한 보험료 귀속월', periodTo: '임금계산기간', periodFrom: '임금계산기간', payDate: '임금계산기간이 없어 지급일의 달', today: '날짜 입력이 없어 오늘' }[IM.source];
  const rateLine = (k) => {
    const it = insItems[k];
    const ovv = ov[k === 'longTermCare' ? 'health' : k];
    if (ovv !== undefined && ovv !== null && ovv !== '') return { ...it, override: true, confirmed: true };
    return it;
  };
  r.yearBasis = {
    incomeTax: {
      basis: 'payDate', date: input.payDate || null, year: payYear, table: '근로소득 간이세액표(2026-03-01 시행)',
      tableYearConfirmed: !taxStale,
      label: `소득세·지방소득세: ${input.payDate ? `${input.payDate} 지급일` : '지급일'} 기준`,
      law: '소득세법 §134①, 시행령 §194①, 지방세법 §103의13①',
    },
    insurance: {
      basis: 'insuranceMonth', month: IM.month, year: insYear, source: IM.source, sourceLabel: srcLabel,
      label: `4대보험: ${insLabel} 기준`,
      pensionPeriod: r.input.pensionPeriod, pensionPeriodLabel: NP.label, pensionPeriodConfirmed: !!(userPensionPeriod || NP.registered),
      rates: Object.fromEntries(Object.keys(INS_LABEL).map((k) => [k, rateLine(k)])),
      unconfirmed: unconfirmed.map((k) => INS_LABEL[k]),
      law: '국민연금법 §88②·§90①, 국민건강보험법 §69④·§77③, 고용산재보험료징수법 §16의3①·§16의7①',
    },
    guidance: [...GUIDANCE],
  };
  r.yearBasis.label = `${r.yearBasis.incomeTax.label} / ${r.yearBasis.insurance.label}`;
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
