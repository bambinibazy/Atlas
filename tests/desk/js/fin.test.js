// 运行：node --test tests/desk/js/*.test.js
const test = require("node:test");
const assert = require("node:assert/strict");
const F = require("../../../site/assets/fin.js");

const close = (a, b, eps = 1e-6) => assert.ok(Math.abs(a - b) < eps, `${a} ≉ ${b}`);

test("NPV / IRR / 回收期（教科书例题）", () => {
  const flows = [-1000, 300, 400, 500];
  // NPV@10% = 300/1.1 + 400/1.21 + 500/1.331 - 1000
  close(F.npv(0.1, flows), 300 / 1.1 + 400 / 1.21 + 500 / 1.331 - 1000);
  const r = F.irr(flows);
  close(F.npv(r, flows), 0, 1e-6);
  close(r, 0.0889633947, 1e-6);
  close(F.payback(flows), 2 + 300 / 500); // 第 2 年末累计 -300，第 3 年回收
  const ev = F.evaluateProject(0.05, flows);
  assert.equal(ev.irrCount, 1);
  assert.ok(ev.discountedPayback > ev.payback);
  assert.equal(F.evaluateProject(0.1, flows).discountedPayback, null); // NPV<0 时折现后永远收不回
  close(ev.pi, (ev.npv + 1000) / 1000);
  assert.equal(F.payback([-100, 10, 10]), null);
});

test("IRR 多根与无解", () => {
  // 经典非常规现金流：-100, +230, -132 → IRR 为 10% 和 20%
  const roots = F.irrAll([-100, 230, -132]).sort();
  assert.equal(roots.length, 2);
  close(roots[0], 0.1, 1e-6);
  close(roots[1], 0.2, 1e-6);
  assert.equal(F.irr([100, 100]), null);
});

test("本量利", () => {
  const b = F.breakeven({ fixed: 120000, price: 50, varCost: 30, targetProfit: 40000, expectedUnits: 10000 });
  close(b.beUnits, 6000);
  close(b.beRevenue, 300000);
  close(b.targetUnits, 8000);
  close(b.expected.profit, 80000);
  close(b.expected.marginOfSafety, 0.4);
  close(b.expected.dol, 200000 / 80000);
  assert.ok(F.breakeven({ fixed: 1, price: 10, varCost: 12 }).error);
});

test("杜邦恒等式", () => {
  const d = F.dupont({ netIncome: 50, revenue: 1000, avgAssets: 800, avgEquity: 400 });
  close(d.margin * d.turnover * d.multiplier, d.roe);
  close(d.roe, 0.125);
});

test("营运资金与释放现金", () => {
  const base = F.cashCycle({ revenue: 3650, cogs: 2920, receivables: 600, inventory: 400, payables: 320 });
  close(base.dso, 60);
  close(base.dio, 50);
  close(base.dpo, 40);
  close(base.ccc, 70);
  const target = { dso: 50, dio: 50, dpo: 40 };
  close(F.cashReleased(base, target), 10 * 10); // 应收少 10 天 × 日收入 10
});

test("WACC 与 CAPM", () => {
  const ke = F.capm({ rf: 0.02, beta: 1.2, mrp: 0.06 });
  close(ke, 0.092);
  const w = F.wacc({ equity: 600, debt: 400, costEquity: ke, costDebt: 0.05, tax: 0.25 });
  close(w.wacc, 0.6 * 0.092 + 0.4 * 0.05 * 0.75);
});

test("贷款：等额本息 / 等额本金 / 实际成本", () => {
  const a = F.loanSchedule({ principal: 120000, annualRate: 0.06, months: 12, method: "annuity" });
  close(a.rows[0].payment, F.annuityPayment(120000, 0.005, 12), 1e-6);
  close(a.rows.at(-1).balance, 0, 1e-6);
  const l = F.loanSchedule({ principal: 120000, annualRate: 0.06, months: 12, method: "linear" });
  close(l.rows[0].principal, 10000);
  assert.ok(l.totalInterest < a.totalInterest);
  const noFee = F.effectiveCost({ principal: 120000, annualRate: 0.06, months: 12, method: "annuity" });
  close(noFee.apr, 0.06, 1e-8);
  const fee = F.effectiveCost({ principal: 120000, annualRate: 0.06, months: 12, method: "annuity", upfrontFee: 2400 });
  assert.ok(fee.ear > 0.09 && fee.ear < 0.11, String(fee.ear)); // 2% 手续费让一年期贷款实际成本明显上升
});

test("决策矩阵与期望值", () => {
  const m = F.decisionMatrix({
    criteria: [{ name: "成本", weight: 3 }, { name: "速度", weight: 1 }],
    options: [{ name: "A", scores: [8, 4] }, { name: "B", scores: [5, 9] }],
  });
  close(m.weights[0], 0.75);
  assert.equal(m.ranked[0].name, "A");
  close(m.gap, (0.75 * 8 + 0.25 * 4) - (0.75 * 5 + 0.25 * 9));
  const ev = F.expectedValue([{ name: "扩产", outcomes: [{ p: 0.6, v: 100 }, { p: 0.4, v: -50 }] }]);
  close(ev[0].ev, 40);
  close(ev[0].lossProb, 0.4);
  assert.ok(ev[0].probOk);
});

test("现金流预测", () => {
  const f = F.cashForecast({ opening: 100, inflow: 50, outflow: 80, months: 6, oneOffs: [{ month: 2, amount: -20 }] });
  assert.equal(f.firstNegative, 3); // 100 →70 →20 →-10
  close(f.rows[1].end, 20);
  close(f.ending, 100 + 6 * -30 - 20);
});

test("定价", () => {
  const p = F.pricing({ cost: 60, price: 100, discount: 0.1 });
  close(p.margin, 0.4);
  close(p.markup, 40 / 60);
  close(p.volumeNeeded, 40 / 30 - 1); // 打九折，销量需增长 33.3%
  close(F.marginToMarkup(0.4), 40 / 60);
  close(F.markupToMargin(0.5), 1 / 3);
});

test("财务比率", () => {
  const cur = { revenue: 1000, cost: 600, netIncome: 100, totalAssets: 1200, equity: 600, totalLiabilities: 600,
    currentAssets: 500, currentLiabilities: 250, inventory: 100, receivables: 150, payables: 90, cash: 120, cfo: 80, capex: -30 };
  const prev = { revenue: 800, netIncome: 80, totalAssets: 800, equity: 400, receivables: 50, inventory: 100, payables: 90 };
  const r = F.ratios(cur, prev);
  close(r.grossMargin, 0.4);
  close(r.roe, 100 / 500);
  close(r.roa, 100 / 1000);
  close(r.debtRatio, 0.5);
  close(r.quickRatio, 400 / 250);
  close(r.dso, 100 / 1000 * 365);
  close(r.fcf, 50);
  close(r.cfoToNetIncome, 0.8);
  close(r.revenueGrowth, 0.25);
  close(r.roe, r.netMargin * r.assetTurnover * r.equityMultiplier);
});

test("个人所得税：综合所得与年终奖", () => {
  // 收入 36 万，三险一金 4 万，专项附加 3.6 万 → 应纳税所得额 22.4 万，20% 档
  const r = F.iit({ income: 360000, social: 40000, special: 36000 });
  close(r.merged.taxable, 224000);
  close(r.tax, 224000 * 0.2 - 16920);
  close(r.afterTax, 360000 - 40000 - 27880);
  assert.equal(r.best, "merged");
  // 应纳税所得额为 0 时不交税
  close(F.iit({ income: 50000 }).tax, 0);
  // 档位边界：36000 元按 3%，多 1 元进入 10% 档（速算扣除数保证不跳涨）
  close(F.iitOnTaxable(36000).tax, 1080);
  close(F.iitOnTaxable(36001).tax, 36001 * 0.1 - 2520);
  // 年终奖单独计税：36000 元按月均 3000 → 3%；多 1 元跳到 10% 档（著名的“临界点”）
  close(F.bonusTax(36000).tax, 1080);
  close(F.bonusTax(36001).tax, 36001 * 0.1 - 210);
  // 单独计税更省时选单独
  const b = F.iit({ income: 300000, bonus: 36000, social: 30000, special: 24000 });
  assert.equal(b.best, "separate");
  close(b.tax, F.iitOnTaxable(300000 - 60000 - 30000 - 24000).tax + 1080);
  close(b.saving, Math.abs(b.merged.tax - b.separate.tax));
});
