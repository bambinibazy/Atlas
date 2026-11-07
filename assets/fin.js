/* 财务计算核心：纯函数，无 DOM 依赖。浏览器里挂在 window.Fin，Node 测试里 require 使用。
   所有比率都以小数返回（0.25 = 25%），天数以天返回。 */
(function (root, factory) {
  if (typeof module === "object" && module.exports) module.exports = factory();
  else root.Fin = factory();
})(typeof self !== "undefined" ? self : this, function () {
  "use strict";

  const isNum = (x) => typeof x === "number" && isFinite(x);
  const sum = (a) => a.reduce((s, x) => s + x, 0);
  const avg2 = (a, b) => (isNum(a) && isNum(b) ? (a + b) / 2 : isNum(a) ? a : isNum(b) ? b : null);
  const div = (a, b) => (isNum(a) && isNum(b) && b !== 0 ? a / b : null);

  /* ---------------- 投资评估 ---------------- */
  // flows[0] 发生在第 0 期（通常为负的初始投资）
  function npv(rate, flows) {
    return flows.reduce((s, cf, t) => s + cf / Math.pow(1 + rate, t), 0);
  }

  // 内部收益率：先在 [-0.99, 10] 里扫描符号变化，再二分求根；可能有多个根时返回所有根
  function irrAll(flows) {
    if (!flows.some((x) => x > 0) || !flows.some((x) => x < 0)) return [];
    const f = (r) => npv(r, flows);
    const roots = [];
    const grid = [];
    for (let r = -0.99; r < 10; r += r < 1 ? 0.005 : 0.05) grid.push(r);
    for (let i = 1; i < grid.length; i++) {
      let a = grid[i - 1], b = grid[i];
      let fa = f(a), fb = f(b);
      if (fa === 0) { if (!roots.some((x) => Math.abs(x - a) < 1e-4)) roots.push(a); continue; }
      if (fa * fb > 0) continue;
      for (let k = 0; k < 200; k++) {
        const m = (a + b) / 2, fm = f(m);
        if (Math.abs(fm) < 1e-10 || b - a < 1e-12) { a = b = m; break; }
        if (fa * fm < 0) { b = m; fb = fm; } else { a = m; fa = fm; }
      }
      const r = (a + b) / 2;
      if (!roots.some((x) => Math.abs(x - r) < 1e-4)) roots.push(r);
    }
    return roots;
  }
  function irr(flows) {
    const r = irrAll(flows);
    if (!r.length) return null;
    // 多个根时取最接近 10% 的那个，同时由界面提示“存在多个 IRR”
    return r.reduce((best, x) => (Math.abs(x - 0.1) < Math.abs(best - 0.1) ? x : best), r[0]);
  }

  // 回收期：累计现金流由负转正的时点，期内按线性插值
  function payback(flows, rate) {
    let cum = 0;
    for (let t = 0; t < flows.length; t++) {
      const cf = rate == null ? flows[t] : flows[t] / Math.pow(1 + rate, t);
      const prev = cum;
      cum += cf;
      if (t > 0 && prev < 0 && cum >= 0) return t - 1 + (-prev / cf);
      if (t === 0 && cum >= 0) return 0;
    }
    return null;
  }

  function evaluateProject(rate, flows) {
    const initial = flows[0];
    const pvFuture = npv(rate, [0, ...flows.slice(1)]);
    const roots = irrAll(flows);
    const cum = [];
    const cumDisc = [];
    flows.reduce((s, cf, t) => { cum.push(s + cf); return s + cf; }, 0);
    flows.reduce((s, cf, t) => { const v = s + cf / Math.pow(1 + rate, t); cumDisc.push(v); return v; }, 0);
    return {
      npv: npv(rate, flows),
      irr: irr(flows),
      irrCount: roots.length,
      payback: payback(flows),
      discountedPayback: payback(flows, rate),
      pi: initial < 0 ? pvFuture / -initial : null,
      cumulative: cum,
      cumulativeDiscounted: cumDisc,
      // 不同折现率下的 NPV，用于画 NPV 曲线
      profile: Array.from({ length: 31 }, (_, i) => {
        const r = i / 100;
        return { rate: r, npv: npv(r, flows) };
      }),
    };
  }

  /* ---------------- 本量利 ---------------- */
  function breakeven({ fixed, price, varCost, targetProfit = 0, expectedUnits = null }) {
    const cm = price - varCost;
    if (!(cm > 0)) return { error: "单价必须高于单位变动成本，否则卖得越多亏得越多" };
    const cmRatio = cm / price;
    const beUnits = fixed / cm;
    const out = {
      cm, cmRatio, beUnits, beRevenue: beUnits * price,
      targetUnits: (fixed + targetProfit) / cm,
      targetRevenue: ((fixed + targetProfit) / cm) * price,
    };
    if (isNum(expectedUnits) && expectedUnits > 0) {
      const profit = expectedUnits * cm - fixed;
      out.expected = {
        units: expectedUnits, revenue: expectedUnits * price, profit,
        marginOfSafety: (expectedUnits - beUnits) / expectedUnits,
        // 经营杠杆系数：销量变动 1% 带来利润变动的百分比
        dol: profit > 0 ? (expectedUnits * cm) / profit : null,
      };
    }
    return out;
  }

  /* ---------------- 杜邦分析 ---------------- */
  function dupont({ netIncome, revenue, avgAssets, avgEquity }) {
    const margin = div(netIncome, revenue);
    const turnover = div(revenue, avgAssets);
    const multiplier = div(avgAssets, avgEquity);
    const roa = div(netIncome, avgAssets);
    const roe = div(netIncome, avgEquity);
    return { margin, turnover, multiplier, roa, roe };
  }

  /* ---------------- 营运资金 ---------------- */
  function cashCycle({ revenue, cogs, receivables, inventory, payables, days = 365 }) {
    const dso = div(receivables, revenue) * days;
    const dio = div(inventory, cogs) * days;
    const dpo = div(payables, cogs) * days;
    return { dso, dio, dpo, ccc: dso + dio - dpo, dailyRevenue: revenue / days, dailyCogs: cogs / days };
  }
  // 周转天数改善后释放（正数）或占用（负数）的现金
  function cashReleased(base, target) {
    return (base.dso - target.dso) * base.dailyRevenue
      + (base.dio - target.dio) * base.dailyCogs
      + (target.dpo - base.dpo) * base.dailyCogs;
  }

  /* ---------------- 资本成本 ---------------- */
  function capm({ rf, beta, mrp }) { return rf + beta * mrp; }
  function wacc({ equity, debt, costEquity, costDebt, tax }) {
    const v = equity + debt;
    if (!(v > 0)) return null;
    const we = equity / v, wd = debt / v;
    return { we, wd, afterTaxDebt: costDebt * (1 - tax), wacc: we * costEquity + wd * costDebt * (1 - tax) };
  }

  /* ---------------- 贷款与融资成本 ---------------- */
  function annuityPayment(principal, rate, n) {
    if (rate === 0) return principal / n;
    return principal * rate / (1 - Math.pow(1 + rate, -n));
  }
  // method: annuity 等额本息 | linear 等额本金 | bullet 先息后本
  function loanSchedule({ principal, annualRate, months, method = "annuity" }) {
    const r = annualRate / 12;
    const rows = [];
    let bal = principal;
    const pmt = annuityPayment(principal, r, months);
    for (let m = 1; m <= months; m++) {
      const interest = bal * r;
      let princ;
      if (method === "annuity") princ = pmt - interest;
      else if (method === "linear") princ = principal / months;
      else princ = m === months ? bal : 0;
      if (m === months) princ = bal;
      bal -= princ;
      rows.push({ m, payment: princ + interest, principal: princ, interest, balance: Math.max(0, bal) });
    }
    return { rows, totalInterest: sum(rows.map((x) => x.interest)), totalPaid: sum(rows.map((x) => x.payment)) };
  }
  // 考虑手续费、保证金等之后的实际年化成本（按月现金流求 IRR）
  function effectiveCost({ principal, annualRate, months, method, upfrontFee = 0, monthlyFee = 0, deposit = 0 }) {
    const s = loanSchedule({ principal, annualRate, months, method });
    const flows = [principal - upfrontFee - deposit];
    s.rows.forEach((row, i) => flows.push(-(row.payment + monthlyFee) + (i === s.rows.length - 1 ? deposit : 0)));
    const r = irr(flows);
    return {
      ...s,
      monthlyIrr: r,
      apr: r == null ? null : r * 12,
      ear: r == null ? null : Math.pow(1 + r, 12) - 1,
      netProceeds: flows[0],
      totalCost: s.totalInterest + upfrontFee + monthlyFee * months,
    };
  }

  /* ---------------- 加权决策矩阵 ---------------- */
  function decisionMatrix({ criteria, options }) {
    const wsum = sum(criteria.map((c) => Math.max(0, c.weight || 0)));
    const weights = criteria.map((c) => (wsum > 0 ? Math.max(0, c.weight || 0) / wsum : 0));
    const results = options.map((o) => {
      const parts = criteria.map((c, i) => (o.scores[i] || 0) * weights[i]);
      return { name: o.name, total: sum(parts), parts };
    });
    const ranked = [...results].sort((a, b) => b.total - a.total);
    return { weights, results, ranked, gap: ranked.length > 1 ? ranked[0].total - ranked[1].total : null };
  }

  /* ---------------- 期望值 ---------------- */
  function expectedValue(options) {
    return options.map((o) => {
      const p = o.outcomes.map((x) => x.p || 0);
      const ps = sum(p);
      const ev = sum(o.outcomes.map((x) => (x.p || 0) * (x.v || 0)));
      const variance = sum(o.outcomes.map((x) => (x.p || 0) * Math.pow((x.v || 0) - ev, 2)));
      const vals = o.outcomes.map((x) => x.v || 0);
      return {
        name: o.name, ev, sd: Math.sqrt(variance), min: Math.min(...vals), max: Math.max(...vals),
        probSum: ps, probOk: Math.abs(ps - 1) < 1e-6,
        lossProb: sum(o.outcomes.filter((x) => (x.v || 0) < 0).map((x) => x.p || 0)),
      };
    });
  }

  /* ---------------- 现金流预测 ---------------- */
  function cashForecast({ opening, inflow, inflowGrowth = 0, outflow, outflowGrowth = 0, months = 12, oneOffs = [] }) {
    const rows = [];
    let cash = opening, inn = inflow, out = outflow, firstNegative = null, low = { m: 0, cash: opening };
    for (let m = 1; m <= months; m++) {
      const extra = sum(oneOffs.filter((o) => o.month === m).map((o) => o.amount));
      const start = cash;
      cash = start + inn - out + extra;
      rows.push({ m, start, inflow: inn, outflow: out, oneOff: extra, end: cash });
      if (cash < low.cash) low = { m, cash };
      if (cash < 0 && firstNegative == null) firstNegative = m;
      inn *= 1 + inflowGrowth;
      out *= 1 + outflowGrowth;
    }
    return { rows, firstNegative, low, ending: cash };
  }

  /* ---------------- 定价与毛利 ---------------- */
  function pricing({ cost, price, discount = 0 }) {
    const margin = div(price - cost, price);
    const markup = div(price - cost, cost);
    // 打折 d 后，要保持毛利额不变需要的销量增幅
    const newPrice = price * (1 - discount);
    const newUnitGp = newPrice - cost;
    const unitGp = price - cost;
    const volumeNeeded = newUnitGp > 0 ? unitGp / newUnitGp - 1 : null;
    return { margin, markup, newPrice, newMargin: div(newUnitGp, newPrice), volumeNeeded };
  }
  const marginToMarkup = (m) => (m < 1 ? m / (1 - m) : null);
  const markupToMargin = (k) => k / (1 + k);

  /* ---------------- 财务比率（公司分析与“分析我的公司”共用） ---------------- */
  // cur / prev: 本期、上期报表项目；字段缺失时对应指标为 null
  function ratios(cur, prev = {}) {
    const g = (o, k) => (o && isNum(o[k]) ? o[k] : null);
    const rev = g(cur, "revenue"), cost = g(cur, "cost"), ni = g(cur, "netIncome");
    const gp = g(cur, "grossProfit") ?? (isNum(rev) && isNum(cost) ? rev - cost : null);
    const cogs = isNum(cost) ? cost : isNum(rev) && isNum(gp) ? rev - gp : null;
    const aA = avg2(g(cur, "totalAssets"), g(prev, "totalAssets"));
    const aE = avg2(g(cur, "equity"), g(prev, "equity"));
    const aAR = avg2(g(cur, "receivables"), g(prev, "receivables"));
    const aInv = avg2(g(cur, "inventory"), g(prev, "inventory"));
    const aAP = avg2(g(cur, "payables"), g(prev, "payables"));
    const ca = g(cur, "currentAssets"), cl = g(cur, "currentLiabilities");
    const cfo = g(cur, "cfo"), capex = g(cur, "capex");
    const r = {
      grossMargin: div(gp, rev),
      operatingMargin: div(g(cur, "operatingProfit"), rev),
      netMargin: div(ni, rev),
      roe: aE > 0 ? div(ni, aE) : null,
      roa: div(ni, aA),
      assetTurnover: div(rev, aA),
      equityMultiplier: aE > 0 ? div(aA, aE) : null,
      debtRatio: div(g(cur, "totalLiabilities"), g(cur, "totalAssets")),
      currentRatio: div(ca, cl),
      quickRatio: isNum(ca) && isNum(cl) ? div(ca - (g(cur, "inventory") || 0), cl) : null,
      cashRatio: div(g(cur, "cash"), cl),
      dso: isNum(aAR) ? div(aAR, rev) * 365 : null,
      dio: isNum(aInv) && cogs > 0 ? div(aInv, cogs) * 365 : null,
      dpo: isNum(aAP) && cogs > 0 ? div(aAP, cogs) * 365 : null,
      cfoToNetIncome: ni > 0 ? div(cfo, ni) : null,
      fcf: isNum(cfo) && isNum(capex) ? cfo - Math.abs(capex) : null,
      rdRatio: div(g(cur, "rd"), rev),
      revenueGrowth: g(prev, "revenue") > 0 ? div(rev, g(prev, "revenue")) - 1 : null,
      profitGrowth: g(prev, "netIncome") > 0 ? div(ni, g(prev, "netIncome")) - 1 : null,
    };
    r.ccc = isNum(r.dso) && isNum(r.dio) && isNum(r.dpo) ? r.dso + r.dio - r.dpo : null;
    return r;
  }

  /* ---------------- 个人所得税（综合所得年度汇算） ---------------- */
  // 综合所得年度税率表（2019 年起施行）：[上限, 税率, 速算扣除数]
  const IIT_ANNUAL = [[36000, 0.03, 0], [144000, 0.1, 2520], [300000, 0.2, 16920], [420000, 0.25, 31920],
    [660000, 0.3, 52920], [960000, 0.35, 85920], [Infinity, 0.45, 181920]];
  // 按月换算后的综合所得税率表，用于全年一次性奖金单独计税
  const IIT_MONTHLY = [[3000, 0.03, 0], [12000, 0.1, 210], [25000, 0.2, 1410], [35000, 0.25, 2660],
    [55000, 0.3, 4410], [80000, 0.35, 7160], [Infinity, 0.45, 15160]];
  const IIT_BASIC = 60000; // 基本减除费用：每年 6 万元

  function bracket(table, x) {
    const i = table.findIndex(([cap]) => x <= cap);
    const [cap, rate, quick] = table[i];
    return { index: i, cap, rate, quick };
  }
  function iitOnTaxable(taxable) {
    const t = Math.max(0, taxable);
    const b = bracket(IIT_ANNUAL, t);
    return { taxable: t, tax: Math.max(0, t * b.rate - b.quick), rate: b.rate, quick: b.quick, bracket: b.index };
  }
  function bonusTax(bonus) {
    if (!(bonus > 0)) return { tax: 0, rate: 0, quick: 0, bracket: -1 };
    const b = bracket(IIT_MONTHLY, bonus / 12);
    return { tax: Math.max(0, bonus * b.rate - b.quick), rate: b.rate, quick: b.quick, bracket: b.index };
  }
  // income：全年工资薪金等综合所得收入（不含年终奖）；bonus：全年一次性奖金
  // social：专项扣除（个人缴纳的三险一金）；special：专项附加扣除；other：其他扣除
  function iit({ income = 0, bonus = 0, social = 0, special = 0, other = 0 }) {
    const deductions = IIT_BASIC + social + special + other;
    const merged = iitOnTaxable(income + bonus - deductions);
    const regular = iitOnTaxable(income - deductions);
    const bt = bonusTax(bonus);
    const separate = { tax: regular.tax + bt.tax, regular, bonus: bt };
    const gross = income + bonus;
    const best = bonus > 0 && separate.tax < merged.tax ? "separate" : "merged";
    const tax = best === "separate" ? separate.tax : merged.tax;
    return {
      deductions, merged, separate, best, tax, gross,
      effective: div(tax, gross), afterTax: gross - social - tax,
      saving: Math.abs(merged.tax - separate.tax),
    };
  }

  return {
    iit, iitOnTaxable, bonusTax, IIT_ANNUAL, IIT_MONTHLY,
    npv, irr, irrAll, payback, evaluateProject, breakeven, dupont, cashCycle, cashReleased,
    capm, wacc, annuityPayment, loanSchedule, effectiveCost, decisionMatrix, expectedValue,
    cashForecast, pricing, marginToMarkup, markupToMargin, ratios, isNum,
  };
});
