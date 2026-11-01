/* 星图智策 — 财务决策工具。计算全部在浏览器本地完成，输入不会上传。
   每个工具：{ id, name, en, desc, keywords, kb:[文章id], defaults(), view(state, ui) → {inputs, results} } */
(function () {
  "use strict";
  const { h, F, isNum } = App;
  const Fin = window.Fin;
  const T = App.tools;

  /* ---------------- 输入控件 ---------------- */
  // 数字输入框：state[key] 保存用户看到的数字（百分比字段保存“10”表示 10%）
  function num(state, key, label, opt = {}) {
    const id = "f-" + key + "-" + Math.random().toString(36).slice(2, 7);
    const input = h("input", {
      id, type: "text", inputMode: "decimal", autocomplete: "off", spellcheck: false,
      value: isNum(state[key]) ? String(state[key]) : "",
      placeholder: opt.placeholder || "",
      "aria-describedby": opt.hint ? id + "-h" : null,
    });
    input.addEventListener("input", () => { state[key] = F.parse(input.value); opt.onChange && opt.onChange(); });
    return h("div.field",
      h("label", { htmlFor: id }, label),
      h("div.input" + (opt.unit ? ".has-unit" : ""), input, opt.unit ? h("span.unit", opt.unit) : null),
      opt.hint ? h("p.hint", { id: id + "-h" }, opt.hint) : null);
  }
  function select(state, key, label, options, onChange) {
    const id = "f-" + key + "-" + Math.random().toString(36).slice(2, 7);
    const sel = h("select", { id }, options.map(([v, t]) => h("option", { value: v, selected: state[key] === v }, t)));
    sel.addEventListener("change", () => { state[key] = sel.value; onChange && onChange(); });
    return h("div.field", h("label", { htmlFor: id }, label), h("div.input", sel));
  }
  function cellInput(value, onInput, opt = {}) {
    const i = h("input", { type: "text", inputMode: opt.text ? "text" : "decimal", value: value ?? "", "aria-label": opt.label || "",
      class: opt.text ? "cell text" : "cell", spellcheck: false });
    i.addEventListener("input", () => onInput(opt.text ? i.value : F.parse(i.value)));
    return i;
  }
  const rmBtn = (label, fn) => h("button.icon-btn", { type: "button", "aria-label": label, title: label, onclick: fn }, "×");
  const addBtn = (label, fn) => h("button.add-btn", { type: "button", onclick: fn }, "+ " + label);
  const p = (x) => (isNum(x) ? x / 100 : null);
  const need = (...xs) => xs.every(isNum);
  const missing = () => h("p.muted.pad", "填写左侧的数字后，这里会显示计算结果。");
  const readout = (title, ...paras) => h("div.readout", h("h3", title), paras.map((t) => h("p", t)));

  /* =====================================================================
     1. 项目投资评估
     ===================================================================== */
  T.project = {
    id: "project", name: "项目投资评估", en: "NPV / IRR / Payback", group: "投资",
    desc: "输入各年现金流，计算净现值、内部收益率、回收期和折现回收期。",
    keywords: "npv irr 净现值 内部收益率 回收期 资本预算 投资回报",
    kb: ["npv", "irr", "wacc", "scenario-sensitivity"],
    defaults: () => ({ rate: 10, flows: [-1000, 300, 350, 400, 400, 300] }),
    view(st, ui) {
      const rows = h("div.rows");
      const drawRows = () => {
        rows.innerHTML = "";
        st.flows.forEach((v, i) => rows.append(h("div.row-line",
          h("span.row-k", i === 0 ? "第 0 年（投资）" : `第 ${i} 年`),
          cellInput(v, (x) => { st.flows[i] = x; ui.update(); }, { label: `第 ${i} 年现金流` }),
          i > 1 ? rmBtn("删除这一年", () => { st.flows.splice(i, 1); drawRows(); ui.update(); }) : h("span.icon-gap"))));
      };
      drawRows();
      const inputs = [
        num(st, "rate", "折现率（资本成本）", { unit: "%", hint: "通常用加权平均资本成本 WACC，风险高的项目适当提高。", onChange: ui.update }),
        h("div.field", h("span.label", "各年净现金流"), h("p.hint", "流入为正、流出为负。第 0 年一般为负的初始投资。单位自定（如万元）。"), rows,
          addBtn("增加一年", () => { st.flows.push(st.flows[st.flows.length - 1] ?? 0); drawRows(); ui.update(); })),
      ];
      const results = () => {
        const flows = st.flows.map((x) => (isNum(x) ? x : 0));
        if (!isNum(st.rate) || flows.length < 2) return missing();
        const r = Fin.evaluateProject(p(st.rate), flows);
        const good = r.npv > 0;
        return [
          App.ledger([
            { label: "净现值 NPV", value: F.num(r.npv), total: true },
            { label: "内部收益率 IRR", value: r.irr == null ? "无解" : F.pct(r.irr, 2), warn: r.irrCount > 1,
              note: r.irrCount > 1 ? `现金流多次变号，存在 ${r.irrCount} 个 IRR，请以净现值为准。` : null },
            { label: "盈利指数 PI", value: F.x(r.pi), sub: true },
            { label: "静态回收期", value: F.years(r.payback), sub: true },
            { label: "折现回收期", value: F.years(r.discountedPayback), sub: true },
          ], "结果"),
          readout("怎么读",
            good ? `按 ${F.pct(p(st.rate))} 的资本成本折现后，项目还多创造了 ${F.num(r.npv)} 的价值，从财务上看值得做。`
              : `按 ${F.pct(p(st.rate))} 的资本成本折现后，项目净现值为负，回报不足以弥补资本成本。`,
            r.irr != null ? `内部收益率 ${F.pct(r.irr, 1)}${r.irr > p(st.rate) ? " 高于" : " 低于"}折现率，与净现值的结论一致。比较互斥项目时以净现值为准。` : ""),
          App.chart({
            title: "不同折现率下的净现值", labels: r.profile.map((x) => F.pct(x.rate, 0)),
            series: [{ name: "净现值", values: r.profile.map((x) => x.npv) }], zeroLine: true, height: 200,
            markers: [{ value: p(st.rate), label: "当前折现率" }], markerDomain: [0, 0.3],
          }),
          App.chart({
            title: "累计现金流", kind: "bar", labels: flows.map((_, i) => `第${i}年`), height: 200,
            series: [{ name: "累计现金流", values: r.cumulative }, { name: "累计折现现金流", values: r.cumulativeDiscounted }],
          }),
        ];
      };
      return { inputs, results };
    },
  };

  /* =====================================================================
     2. 盈亏平衡
     ===================================================================== */
  T.breakeven = {
    id: "breakeven", name: "盈亏平衡 / 本量利", en: "Break-even (CVP)", group: "经营",
    desc: "要卖多少才能保本、达到目标利润，以及销量变化对利润的放大效应。",
    keywords: "盈亏平衡 保本点 本量利 边际贡献 经营杠杆 安全边际 cvp breakeven",
    kb: ["cvp", "capital-structure", "pricing-strategy"],
    defaults: () => ({ fixed: 120000, price: 50, varCost: 30, targetProfit: 40000, expectedUnits: 10000 }),
    view(st, ui) {
      const o = { onChange: ui.update };
      const inputs = [
        num(st, "fixed", "固定成本（每期）", { ...o, hint: "房租、管理人员工资、折旧等不随销量变化的成本。" }),
        num(st, "price", "单价", o),
        num(st, "varCost", "单位变动成本", { ...o, hint: "材料、计件工资、佣金、运费等随销量变化的成本。" }),
        num(st, "targetProfit", "目标利润（可选）", o),
        num(st, "expectedUnits", "预计销量（可选）", { ...o, unit: "件" }),
      ];
      const results = () => {
        if (!need(st.fixed, st.price, st.varCost)) return missing();
        const r = Fin.breakeven({ fixed: st.fixed, price: st.price, varCost: st.varCost, targetProfit: st.targetProfit || 0, expectedUnits: st.expectedUnits });
        if (r.error) return h("p.alert", r.error);
        const e = r.expected;
        const maxU = Math.max(r.beUnits * 2, (st.expectedUnits || 0) * 1.25, r.targetUnits * 1.2);
        const xs = Array.from({ length: 21 }, (_, i) => (maxU * i) / 20);
        return [
          App.ledger([
            { label: "单位边际贡献", value: F.num(r.cm), sub: true },
            { label: "边际贡献率", value: F.pct(r.cmRatio), sub: true },
            { label: "盈亏平衡销量", value: F.num(r.beUnits, 0) + " 件", total: true },
            { label: "盈亏平衡销售额", value: F.num(r.beRevenue, 0) },
            isNum(st.targetProfit) && st.targetProfit > 0 ? { label: "达到目标利润需要的销量", value: F.num(r.targetUnits, 0) + " 件" } : null,
            e ? { label: "预计利润", value: F.num(e.profit, 0) } : null,
            e ? { label: "安全边际率", value: F.pct(e.marginOfSafety), warn: e.marginOfSafety < 0.2 } : null,
            e && e.dol ? { label: "经营杠杆系数", value: F.x(e.dol, 2), note: `销量每变动 10%，利润约变动 ${F.pct(e.dol * 0.1, 0)}。` } : null,
          ], "结果"),
          readout("怎么读",
            `每卖出一件，扣除变动成本后剩 ${F.num(r.cm)} 用来覆盖固定成本；卖到 ${F.num(r.beUnits, 0)} 件时刚好不亏不赚。`,
            e ? (e.marginOfSafety >= 0
              ? `按预计销量，销量下滑 ${F.pct(e.marginOfSafety, 0)} 以内仍能保本。安全边际越小，经营风险越大。`
              : `预计销量低于盈亏平衡点，需要提价、降本或提高销量。`) : ""),
          App.chart({
            title: "收入与总成本", labels: xs.map((x) => F.num(x, 0)), height: 220,
            series: [{ name: "销售收入", values: xs.map((x) => x * st.price) },
              { name: "总成本", values: xs.map((x) => st.fixed + x * st.varCost) }],
            fmt: (v) => F.num(v, 0), markers: [{ value: r.beUnits, label: "保本点" }], markerDomain: [0, maxU],
          }),
        ];
      };
      return { inputs, results };
    },
  };

  /* =====================================================================
     3. 杜邦分析
     ===================================================================== */
  T.dupont = {
    id: "dupont", name: "杜邦分析", en: "DuPont ROE", group: "分析",
    desc: "把净资产收益率拆成净利率、资产周转率和权益乘数，看清回报从哪里来。",
    keywords: "杜邦 roe 净资产收益率 权益乘数 资产周转率 净利率 dupont",
    kb: ["dupont", "ratio-system", "capital-structure"],
    defaults: () => ({ netIncome: 50, revenue: 1000, assetsBegin: 760, assetsEnd: 840, equityBegin: 380, equityEnd: 420 }),
    view(st, ui) {
      const o = { onChange: ui.update };
      const inputs = [
        num(st, "netIncome", "净利润（归属于母公司）", o),
        num(st, "revenue", "营业收入", o),
        h("div.pair", num(st, "assetsBegin", "期初总资产", o), num(st, "assetsEnd", "期末总资产", o)),
        h("div.pair", num(st, "equityBegin", "期初净资产", o), num(st, "equityEnd", "期末净资产", o)),
        h("p.hint", "单位自定，保持一致即可。只有期末数时，期初也填同一个数。"),
      ];
      const results = () => {
        if (!need(st.netIncome, st.revenue, st.assetsEnd, st.equityEnd)) return missing();
        const avgA = ((st.assetsBegin ?? st.assetsEnd) + st.assetsEnd) / 2;
        const avgE = ((st.equityBegin ?? st.equityEnd) + st.equityEnd) / 2;
        const d = Fin.dupont({ netIncome: st.netIncome, revenue: st.revenue, avgAssets: avgA, avgEquity: avgE });
        return [
          dupontTree(d),
          readout("怎么读",
            `ROE ${F.pct(d.roe)} = 净利率 ${F.pct(d.margin)} × 资产周转率 ${F.num(d.turnover)} 次 × 权益乘数 ${F.num(d.multiplier)}。`,
            d.multiplier > 3 ? "权益乘数较高，回报中有相当一部分来自负债。行业下行时，高杠杆会放大亏损。" :
              d.margin > 0.15 ? "以高利润率驱动为主，通常意味着较强的定价权或成本优势。" :
                d.turnover > 1.5 ? "以高周转驱动为主，常见于零售、批发、快消等行业。" :
                  "三个因子都不突出。可以和同行比较，找出差距最大的一项。"),
        ];
      };
      return { inputs, results };
    },
  };
  function dupontTree(d, med) {
    const node = (label, v, f, m) => h("div.dnode", h("span.dl", label), h("b", f(v)), m != null ? h("span.dm", "同行中位数 " + f(m)) : null);
    return h("div.dtree", { role: "group", "aria-label": "杜邦分解" },
      h("div.dtop", node("ROE 净资产收益率", d.roe, F.pct, med && med.roe)),
      h("div.dops", h("span", "="), h("span"), h("span", "×"), h("span"), h("span", "×")),
      h("div.dbot",
        node("净利率", d.margin, F.pct, med && med.netMargin),
        h("span.dx", "×"),
        node("总资产周转率", d.turnover, (x) => F.num(x) + " 次", med && med.assetTurnover),
        h("span.dx", "×"),
        node("权益乘数", d.multiplier, (x) => F.num(x), med && med.equityMultiplier)),
      h("p.dfoot", `ROA 总资产收益率 = 净利率 × 资产周转率 = ${F.pct(d.roa)}`));
  }
  App.dupontTree = dupontTree;

  /* =====================================================================
     4. 营运资金
     ===================================================================== */
  T.workingcap = {
    id: "workingcap", name: "营运资金与现金周期", en: "Cash Conversion Cycle", group: "分析",
    desc: "计算应收、存货、应付周转天数和现金周转周期，以及缩短天数能释放多少现金。",
    keywords: "营运资金 现金周转周期 应收账款周转天数 存货周转天数 应付 dso dio dpo ccc",
    kb: ["working-capital", "ratio-system", "cashflow-forecast"],
    defaults: () => ({ revenue: 36500, cogs: 27375, receivables: 7500, inventory: 4500, payables: 3750, tDso: 60, tDio: 50, tDpo: 50 }),
    view(st, ui) {
      const o = { onChange: ui.update };
      const inputs = [
        num(st, "revenue", "年营业收入", o),
        num(st, "cogs", "年营业成本", o),
        num(st, "receivables", "应收账款（平均余额）", { ...o, hint: "最好用期初和期末的平均数。" }),
        num(st, "inventory", "存货（平均余额）", o),
        num(st, "payables", "应付账款（平均余额）", o),
        h("h3.sub-h", "改善目标"),
        h("div.trio", num(st, "tDso", "应收天数", { ...o, unit: "天" }), num(st, "tDio", "存货天数", { ...o, unit: "天" }), num(st, "tDpo", "应付天数", { ...o, unit: "天" })),
      ];
      const results = () => {
        if (!need(st.revenue, st.cogs, st.receivables, st.inventory, st.payables)) return missing();
        const b = Fin.cashCycle({ revenue: st.revenue, cogs: st.cogs, receivables: st.receivables, inventory: st.inventory, payables: st.payables });
        const tgt = { dso: st.tDso ?? b.dso, dio: st.tDio ?? b.dio, dpo: st.tDpo ?? b.dpo };
        const rel = Fin.cashReleased(b, tgt);
        return [
          App.ledger([
            { label: "应收账款周转天数", value: F.days(b.dso) },
            { label: "＋ 存货周转天数", value: F.days(b.dio) },
            { label: "－ 应付账款周转天数", value: F.days(b.dpo) },
            { label: "现金周转周期", value: F.days(b.ccc), total: true },
          ], "当前"),
          App.ledger([
            { label: "目标现金周转周期", value: F.days(tgt.dso + tgt.dio - tgt.dpo) },
            { label: "应收改善释放", value: F.num((b.dso - tgt.dso) * b.dailyRevenue, 0), sub: true },
            { label: "存货改善释放", value: F.num((b.dio - tgt.dio) * b.dailyCogs, 0), sub: true },
            { label: "应付延长释放", value: F.num((tgt.dpo - b.dpo) * b.dailyCogs, 0), sub: true },
            { label: rel >= 0 ? "合计释放现金" : "合计占用现金", value: F.num(Math.abs(rel), 0), total: true },
          ], "达到目标后"),
          readout("怎么读",
            `从付钱给供应商到收回客户货款，平均需要 ${F.num(b.ccc, 0)} 天。这段时间的资金需要企业自己垫付。`,
            `日均收入约 ${F.num(b.dailyRevenue, 0)}，应收天数每缩短 1 天，大约释放 ${F.num(b.dailyRevenue, 0)} 的现金。`),
        ];
      };
      return { inputs, results };
    },
  };

  /* =====================================================================
     5. WACC
     ===================================================================== */
  T.wacc = {
    id: "wacc", name: "资本成本 WACC", en: "WACC & CAPM", group: "投资",
    desc: "用资本资产定价模型估算股权成本，计算加权平均资本成本，作为投资项目的折现率。",
    keywords: "wacc capm 资本成本 股权成本 贝塔 折现率 无风险利率",
    kb: ["wacc", "capital-structure", "npv"],
    defaults: () => ({ equity: 600, debt: 400, rf: 2, beta: 1.2, mrp: 6, extra: 0, rd: 5, tax: 25 }),
    view(st, ui) {
      const o = { onChange: ui.update };
      const inputs = [
        h("div.pair", num(st, "equity", "股权价值", { ...o, hint: "上市公司用市值。" }), num(st, "debt", "有息负债", o)),
        h("h3.sub-h", "股权成本（CAPM）"),
        num(st, "rf", "无风险利率", { ...o, unit: "%", hint: "通常参考 10 年期国债收益率。" }),
        h("div.pair", num(st, "beta", "贝塔 β", o), num(st, "mrp", "市场风险溢价", { ...o, unit: "%" })),
        num(st, "extra", "额外风险溢价（可选）", { ...o, unit: "%", hint: "非上市、规模小或业务集中的企业可加 2%～5%。" }),
        h("h3.sub-h", "债务成本"),
        h("div.pair", num(st, "rd", "税前借款利率", { ...o, unit: "%" }), num(st, "tax", "所得税税率", { ...o, unit: "%" })),
      ];
      const results = () => {
        if (!need(st.equity, st.debt, st.rf, st.beta, st.mrp, st.rd, st.tax)) return missing();
        const ke = Fin.capm({ rf: p(st.rf), beta: st.beta, mrp: p(st.mrp) }) + (p(st.extra) || 0);
        const w = Fin.wacc({ equity: st.equity, debt: st.debt, costEquity: ke, costDebt: p(st.rd), tax: p(st.tax) });
        if (!w) return missing();
        return [
          App.ledger([
            { label: "股权成本", value: F.pct(ke, 2), note: `${F.pct(p(st.rf), 2)} + ${F.num(st.beta)} × ${F.pct(p(st.mrp), 2)}${st.extra ? " + " + F.pct(p(st.extra), 2) : ""}` },
            { label: "税后债务成本", value: F.pct(w.afterTaxDebt, 2) },
            { label: "股权权重", value: F.pct(w.we), sub: true },
            { label: "债务权重", value: F.pct(w.wd), sub: true },
            { label: "WACC", value: F.pct(w.wacc, 2), total: true },
          ], "结果"),
          readout("怎么读",
            `投资项目的回报率至少要达到 ${F.pct(w.wacc, 1)}，才能满足股东和债权人的要求。这个数字可以直接作为项目投资评估的折现率。`,
            "风险明显高于公司平均水平的项目（如进入新行业、新市场），应在此基础上提高折现率。"),
          h("p", h("a.btn-link", { href: `#/tools/project?s=${encodeState({ rate: Math.round(w.wacc * 1000) / 10, flows: [-1000, 300, 350, 400, 400, 300] })}` }, "用这个折现率评估项目")),
        ];
      };
      return { inputs, results };
    },
  };

  /* =====================================================================
     6. 贷款与融资成本
     ===================================================================== */
  const METHODS = [["annuity", "等额本息"], ["linear", "等额本金"], ["bullet", "先息后本"]];
  T.loan = {
    id: "loan", name: "贷款与融资成本", en: "Loan & True Cost of Funds", group: "投资",
    desc: "比较多个融资方案的月供、总利息和含手续费、保证金后的实际年化成本。",
    keywords: "贷款 融资成本 实际利率 年化 手续费 保证金 等额本息 等额本金 apr ear",
    kb: ["financing-options", "wacc", "irr"],
    defaults: () => ({ offers: [
      { name: "银行贷款", principal: 1000000, rate: 4.5, months: 12, method: "annuity", fee: 0, monthlyFee: 0, deposit: 0 },
      { name: "融资租赁", principal: 1000000, rate: 3.8, months: 12, method: "annuity", fee: 30000, monthlyFee: 0, deposit: 100000 },
    ] }),
    view(st, ui) {
      const box = h("div");
      const draw = () => {
        box.innerHTML = "";
        st.offers.forEach((o, i) => {
          const f = (k, label, opt = {}) => {
            const tmp = { [k]: o[k] };
            return num(tmp, k, label, { ...opt, onChange: () => { o[k] = tmp[k]; ui.update(); } });
          };
          const name = cellInput(o.name, (v) => { o.name = v; ui.update(); }, { text: true, label: "方案名称" });
          const sel = h("select", { "aria-label": "还款方式" }, METHODS.map(([v, t]) => h("option", { value: v, selected: o.method === v }, t)));
          sel.onchange = () => { o.method = sel.value; ui.update(); };
          box.append(h("fieldset.offer",
            h("legend", name, st.offers.length > 1 ? rmBtn("删除这个方案", () => { st.offers.splice(i, 1); draw(); ui.update(); }) : null),
            h("div.pair", f("principal", "借款金额"), f("rate", "名义年利率", { unit: "%" })),
            h("div.pair", f("months", "期限", { unit: "月" }), h("div.field", h("span.label", "还款方式"), h("div.input", sel))),
            h("div.trio", f("fee", "一次性费用"), f("monthlyFee", "每月费用"), f("deposit", "保证金", { hint: "到期退还" }))));
        });
        if (st.offers.length < 3) box.append(addBtn("增加方案", () => { st.offers.push({ ...st.offers[st.offers.length - 1], name: `方案 ${st.offers.length + 1}` }); draw(); ui.update(); }));
      };
      draw();
      const results = () => {
        const rs = st.offers.filter((o) => need(o.principal, o.rate, o.months) && o.months >= 1).map((o) => ({ o, r: Fin.effectiveCost({
          principal: o.principal, annualRate: p(o.rate), months: Math.round(o.months), method: o.method,
          upfrontFee: o.fee || 0, monthlyFee: o.monthlyFee || 0, deposit: o.deposit || 0 }) }));
        if (!rs.length) return missing();
        const best = rs.reduce((a, b) => ((b.r.ear ?? 9) < (a.r.ear ?? 9) ? b : a));
        const table = h("table.data",
          h("thead", h("tr", h("th", ""), rs.map(({ o }) => h("th.num", o.name || "方案")))),
          h("tbody",
            [["实际到手", (r) => F.num(r.netProceeds, 0)],
              ["首月还款", (r) => F.num(r.rows[0].payment, 0)],
              ["总利息", (r) => F.num(r.totalInterest, 0)],
              ["利息 + 费用", (r) => F.num(r.totalCost, 0)],
              ["名义年利率", (_, o) => F.pct(p(o.rate), 2)],
              ["实际年化（单利）", (r) => F.pct(r.apr, 2)],
              ["实际年利率（复利）", (r) => F.pct(r.ear, 2)]].map(([k, fn], ri) =>
              h("tr" + (ri >= 5 ? ".em" : ""), h("th", k), rs.map(({ o, r }) => h("td.num" + (ri === 6 && r === best.r ? ".best" : ""), fn(r, o)))))));
        const sch = best.r.rows;
        return [
          h("div.table-wrap", table),
          readout("怎么读",
            `把手续费、保证金和还款节奏都算进去后，“${best.o.name}”的实际成本最低，复利年化 ${F.pct(best.r.ear, 2)}。`,
            "实际年化成本是把到手金额作为现金流入、每期还款和费用作为流出，求内部收益率得到的，可以直接和其他融资方式比较。"),
          App.chart({ title: `“${best.o.name}”每月还款构成`, kind: "bar", labels: sch.map((x) => `${x.m}月`), height: 190,
            series: [{ name: "本金", values: sch.map((x) => x.principal) }, { name: "利息", values: sch.map((x) => x.interest) }],
            fmt: (v) => F.num(v, 0) }),
        ];
      };
      return { inputs: [box], results };
    },
  };

  /* =====================================================================
     7. 加权决策矩阵
     ===================================================================== */
  T.matrix = {
    id: "matrix", name: "加权决策矩阵", en: "Weighted Decision Matrix", group: "决策", wide: true,
    desc: "多个方案、多个标准时，先定权重再打分，得到透明、可讨论的排序。",
    keywords: "决策矩阵 加权评分 多方案比较 选择 供应商选择 评分卡",
    kb: ["decision-matrix", "expected-value", "pre-mortem"],
    defaults: () => ({
      criteria: [{ name: "五年总成本", weight: 30 }, { name: "功能匹配度", weight: 25 }, { name: "实施周期", weight: 15 }, { name: "服务能力", weight: 20 }, { name: "可扩展性", weight: 10 }],
      options: [{ name: "方案 A", scores: [6, 9, 5, 8, 9] }, { name: "方案 B", scores: [9, 6, 8, 5, 5] }, { name: "方案 C", scores: [7, 8, 7, 7, 7] }],
    }),
    view(st, ui) {
      const box = h("div.matrix-edit");
      const draw = () => {
        box.innerHTML = "";
        const table = h("table.grid",
          h("thead", h("tr", h("th", "标准"), h("th.num", "权重"),
            st.options.map((o, j) => h("th", cellInput(o.name, (v) => { o.name = v; ui.update(); }, { text: true, label: "方案名称" }),
              st.options.length > 2 ? rmBtn("删除方案", () => { st.options.splice(j, 1); draw(); ui.update(); }) : null)))),
          h("tbody", st.criteria.map((c, i) => h("tr",
            h("th", cellInput(c.name, (v) => { c.name = v; ui.update(); }, { text: true, label: "标准名称" }),
              st.criteria.length > 2 ? rmBtn("删除标准", () => { st.criteria.splice(i, 1); st.options.forEach((o) => o.scores.splice(i, 1)); draw(); ui.update(); }) : null),
            h("td", cellInput(c.weight, (v) => { c.weight = v; ui.update(); }, { label: c.name + " 权重" })),
            st.options.map((o) => h("td", cellInput(o.scores[i], (v) => { o.scores[i] = v; ui.update(); }, { label: `${o.name} ${c.name} 得分` })))))));
        box.append(h("div.table-wrap", table),
          h("div.btn-row",
            addBtn("增加标准", () => { st.criteria.push({ name: "新标准", weight: 10 }); st.options.forEach((o) => o.scores.push(5)); draw(); ui.update(); }),
            st.options.length < 6 ? addBtn("增加方案", () => { st.options.push({ name: `方案 ${String.fromCharCode(65 + st.options.length)}`, scores: st.criteria.map(() => 5) }); draw(); ui.update(); }) : null),
          h("p.hint", "权重填相对大小即可（会自动换算成百分比），得分建议用 1～10 分。先定权重、再打分。"));
      };
      draw();
      const results = () => {
        const m = Fin.decisionMatrix({ criteria: st.criteria.map((c) => ({ weight: c.weight || 0 })),
          options: st.options.map((o) => ({ name: o.name, scores: o.scores.map((x) => x || 0) })) });
        const top = m.ranked[0].total || 1;
        const maxScore = Math.max(10, ...st.options.flatMap((o) => o.scores.filter(isNum)));
        return [
          h("ol.rank", m.ranked.map((r, i) => h("li",
            h("span.rank-n", r.name), h("span.rank-bar", h("i", { style: { width: (r.total / maxScore) * 100 + "%" } })),
            h("b", F.num(r.total, 2))))),
          h("p.muted", "权重换算：", st.criteria.map((c, i) => `${c.name} ${F.pct(m.weights[i], 0)}`).join("，")),
          readout("怎么读",
            m.gap == null ? "" : m.gap < top * 0.05
              ? `前两名只差 ${F.num(m.gap, 2)} 分，结论并不稳固。建议对差距最大的标准做进一步验证，或者调整权重看看排名会不会变。`
              : `“${m.ranked[0].name}”领先第二名 ${F.num(m.gap, 2)} 分，在当前权重下优势比较明确。`,
            "合规、安全等底线要求不应参与加权，而应先作为门槛筛掉不合格的方案。"),
        ];
      };
      return { inputs: [box], results };
    },
  };

  /* =====================================================================
     8. 期望值
     ===================================================================== */
  T.ev = {
    id: "ev", name: "期望值比较", en: "Expected Value", group: "决策",
    desc: "为每个方案设定几种情景的概率和结果，比较期望值、最坏结果和亏损概率。",
    keywords: "期望值 决策树 概率 情景 风险 不确定性",
    kb: ["expected-value", "scenario-sensitivity", "pre-mortem"],
    defaults: () => ({ options: [
      { name: "扩建产线", outcomes: [{ s: "需求旺盛", p: 40, v: 800 }, { s: "需求一般", p: 40, v: 200 }, { s: "需求低迷", p: 20, v: -500 }] },
      { name: "外包代工", outcomes: [{ s: "需求旺盛", p: 40, v: 400 }, { s: "需求一般", p: 40, v: 150 }, { s: "需求低迷", p: 20, v: -50 }] },
    ] }),
    view(st, ui) {
      const box = h("div");
      const draw = () => {
        box.innerHTML = "";
        st.options.forEach((o, i) => {
          box.append(h("fieldset.offer",
            h("legend", cellInput(o.name, (v) => { o.name = v; ui.update(); }, { text: true, label: "方案名称" }),
              st.options.length > 1 ? rmBtn("删除方案", () => { st.options.splice(i, 1); draw(); ui.update(); }) : null),
            h("div.row-line.head", h("span", "情景"), h("span", "概率 %"), h("span", "结果"), h("span")),
            o.outcomes.map((x, k) => h("div.row-line.three",
              cellInput(x.s, (v) => { x.s = v; ui.update(); }, { text: true, label: "情景" }),
              cellInput(x.p, (v) => { x.p = v; ui.update(); }, { label: "概率" }),
              cellInput(x.v, (v) => { x.v = v; ui.update(); }, { label: "结果" }),
              o.outcomes.length > 1 ? rmBtn("删除情景", () => { o.outcomes.splice(k, 1); draw(); ui.update(); }) : h("span.icon-gap"))),
            addBtn("增加情景", () => { o.outcomes.push({ s: "新情景", p: 0, v: 0 }); draw(); ui.update(); })));
        });
        if (st.options.length < 3) box.append(addBtn("增加方案", () => { st.options.push(JSON.parse(JSON.stringify(st.options[0]))); st.options.at(-1).name = `方案 ${st.options.length}`; draw(); ui.update(); }));
      };
      draw();
      const results = () => {
        const rs = Fin.expectedValue(st.options.map((o) => ({ name: o.name, outcomes: o.outcomes.map((x) => ({ p: p(x.p) || 0, v: x.v || 0 })) })));
        const bad = rs.filter((r) => !r.probOk);
        const best = rs.reduce((a, b) => (b.ev > a.ev ? b : a));
        return [
          bad.length ? h("p.alert", `${bad.map((r) => `“${r.name}”的概率合计为 ${F.pct(r.probSum, 0)}`).join("；")}，应为 100%。`) : null,
          h("div.table-wrap", h("table.data",
            h("thead", h("tr", h("th", ""), rs.map((r) => h("th.num", r.name)))),
            h("tbody", [["期望值", (r) => F.num(r.ev)], ["最好结果", (r) => F.num(r.max)], ["最坏结果", (r) => F.num(r.min)],
              ["亏损概率", (r) => F.pct(r.lossProb, 0)], ["标准差（波动）", (r) => F.num(r.sd)]].map(([k, fn], i) =>
              h("tr" + (i === 0 ? ".em" : ""), h("th", k), rs.map((r) => h("td.num" + (i === 0 && r === best ? ".best" : ""), fn(r)))))))),
          readout("怎么读",
            `“${best.name}”的期望值最高（${F.num(best.ev)}）。`,
            best.min < 0 ? `但它在最坏情况下会亏损 ${F.num(-best.min)}，发生概率 ${F.pct(best.lossProb, 0)}。如果这个亏损超出了公司能承受的范围，期望值较低但更稳健的方案可能更合适。` : "这个方案在最坏情况下也不亏损。"),
        ];
      };
      return { inputs: [box], results };
    },
  };

  /* =====================================================================
     9. 现金流预测
     ===================================================================== */
  T.cashflow = {
    id: "cashflow", name: "现金流预测", en: "Cash Flow Forecast", group: "经营",
    desc: "按月模拟现金收支和余额，找出资金最紧张的月份和第一次出现缺口的时间。",
    keywords: "现金流预测 资金计划 现金跑道 烧钱率 资金缺口 runway",
    kb: ["cashflow-forecast", "working-capital", "comprehensive-budget"],
    defaults: () => ({ opening: 500, inflow: 300, inflowGrowth: 2, outflow: 340, outflowGrowth: 1, months: 12, minCash: 100,
      oneOffs: [{ month: 3, amount: -150, note: "设备尾款" }, { month: 7, amount: 200, note: "新增贷款" }] }),
    view(st, ui) {
      const o = { onChange: ui.update };
      const list = h("div.rows");
      const draw = () => {
        list.innerHTML = "";
        st.oneOffs.forEach((x, i) => list.append(h("div.row-line.three",
          cellInput(x.month, (v) => { x.month = v; ui.update(); }, { label: "月份" }),
          cellInput(x.amount, (v) => { x.amount = v; ui.update(); }, { label: "金额" }),
          cellInput(x.note, (v) => { x.note = v; ui.update(); }, { text: true, label: "说明" }),
          rmBtn("删除", () => { st.oneOffs.splice(i, 1); draw(); ui.update(); }))));
      };
      draw();
      const inputs = [
        num(st, "opening", "期初可用现金", { ...o, hint: "银行余额扣除保证金等受限资金。" }),
        h("div.pair", num(st, "inflow", "每月现金收入", o), num(st, "inflowGrowth", "月增长率", { ...o, unit: "%" })),
        h("div.pair", num(st, "outflow", "每月现金支出", o), num(st, "outflowGrowth", "月增长率", { ...o, unit: "%" })),
        h("div.pair", num(st, "months", "预测月数", { ...o, unit: "月" }), num(st, "minCash", "最低安全余额", o)),
        h("div.field", h("span.label", "一次性收支"), h("p.hint", "流入填正数，流出填负数。"), h("div.row-line.head", h("span", "第几月"), h("span", "金额"), h("span", "说明"), h("span")), list,
          addBtn("增加一笔", () => { st.oneOffs.push({ month: 1, amount: 0, note: "" }); draw(); ui.update(); })),
      ];
      const results = () => {
        if (!need(st.opening, st.inflow, st.outflow)) return missing();
        const months = Math.max(1, Math.min(36, Math.round(st.months || 12)));
        const r = Fin.cashForecast({ opening: st.opening, inflow: st.inflow, inflowGrowth: p(st.inflowGrowth) || 0, outflow: st.outflow,
          outflowGrowth: p(st.outflowGrowth) || 0, months, oneOffs: st.oneOffs.filter((x) => isNum(x.month) && isNum(x.amount)) });
        const minCash = st.minCash || 0;
        const below = r.rows.find((x) => x.end < minCash);
        return [
          App.ledger([
            { label: "期末现金", value: F.num(r.ending, 0), total: true },
            { label: "最低点", value: `第 ${r.low.m} 月，${F.num(r.low.cash, 0)}`, warn: r.low.cash < minCash },
            { label: "首次出现缺口", value: r.firstNegative ? `第 ${r.firstNegative} 月` : "预测期内没有", warn: !!r.firstNegative },
            below ? { label: "首次低于安全余额", value: `第 ${below.m} 月`, warn: true } : null,
          ], "结果"),
          App.chart({ title: "每月末现金余额", kind: "bar", labels: r.rows.map((x) => `${x.m}月`), height: 210,
            series: [{ name: "月末现金", values: r.rows.map((x) => x.end), color: (v) => (v < minCash ? "var(--series-2)" : "var(--series-1)") }],
            markersY: [{ value: minCash, label: "安全余额" }],
            fmt: (v) => F.num(v, 0) }),
          readout("怎么读",
            r.firstNegative ? `按当前假设，第 ${r.firstNegative} 个月现金会用完，需要在此之前安排融资、加快回款或削减支出。`
              : below ? `预测期内现金没有用完，但第 ${below.m} 个月会低于安全余额 ${F.num(minCash, 0)}。` : "预测期内现金余额始终高于安全线。",
            "建议再做一个“回款推迟一个月”的悲观情景：把每月收入调低、或在某个月加一笔负的一次性收支。"),
          h("details.more-table", h("summary", "查看逐月明细"), h("div.table-wrap", h("table.data.small",
            h("thead", h("tr", ["月", "月初", "收入", "支出", "一次性", "月末"].map((t, i) => h(i ? "th.num" : "th", t)))),
            h("tbody", r.rows.map((x) => h("tr" + (x.end < 0 ? ".neg" : ""), h("td", x.m), [x.start, x.inflow, x.outflow, x.oneOff, x.end].map((v) => h("td.num", F.num(v, 0))))))))),
        ];
      };
      return { inputs, results };
    },
  };

  /* =====================================================================
     10. 定价与折扣
     ===================================================================== */
  T.pricing = {
    id: "pricing", name: "定价与折扣", en: "Markup, Margin & Discounts", group: "经营",
    desc: "加成率与毛利率互相换算，并计算打折后销量要增长多少才能保住毛利。",
    keywords: "定价 毛利率 加成率 折扣 促销 降价 销量 markup margin",
    kb: ["pricing-strategy", "cvp"],
    defaults: () => ({ cost: 60, price: 100, discount: 10 }),
    view(st, ui) {
      const o = { onChange: ui.update };
      const inputs = [
        num(st, "cost", "单位成本", o),
        num(st, "price", "售价", o),
        num(st, "discount", "计划折扣", { ...o, unit: "%", hint: "例如打九折填 10。" }),
      ];
      const results = () => {
        if (!need(st.cost, st.price) || st.price <= 0) return missing();
        const r = Fin.pricing({ cost: st.cost, price: st.price, discount: p(st.discount) || 0 });
        const ds = [5, 10, 15, 20, 25, 30];
        return [
          App.ledger([
            { label: "毛利率", value: F.pct(r.margin) },
            { label: "加成率", value: F.pct(r.markup) },
            { label: "折后价格", value: F.num(r.newPrice), sub: true },
            { label: "折后毛利率", value: F.pct(r.newMargin), sub: true, warn: r.newMargin <= 0 },
            { label: "保持毛利额所需销量增幅", value: r.volumeNeeded == null ? "无法弥补" : F.pct(r.volumeNeeded), total: true, warn: r.volumeNeeded == null || r.volumeNeeded > 0.5 },
          ], "结果"),
          h("div.table-wrap", h("table.data.small",
            h("thead", h("tr", h("th", "折扣"), h("th.num", "折后毛利率"), h("th.num", "销量需增长"))),
            h("tbody", ds.map((d) => { const x = Fin.pricing({ cost: st.cost, price: st.price, discount: d / 100 });
              return h("tr", h("td", `${d}%`), h("td.num", F.pct(x.newMargin)), h("td.num", x.volumeNeeded == null ? "无法弥补" : F.pct(x.volumeNeeded))); })))),
          readout("怎么读",
            r.volumeNeeded == null ? "折扣已经吃掉了全部毛利，卖得越多亏得越多。"
              : `折扣 ${F.num(st.discount || 0, 0)}% 后，销量要增长 ${F.pct(r.volumeNeeded, 0)} 才能赚到和原来一样多的毛利。`,
            "毛利率越低，打折越危险。可以考虑捆绑、赠品、只对增量部分优惠等替代方式。"),
        ];
      };
      return { inputs, results };
    },
  };

  /* =====================================================================
     11. 个人所得税（综合所得年度汇算）
     ===================================================================== */
  const BRACKET_LABEL = (table, i, unit) => {
    const lo = i === 0 ? 0 : table[i - 1][0];
    const hi = table[i][0];
    return hi === Infinity ? `超过 ${F.num(lo, 0)}${unit}` : `${F.num(lo, 0)}–${F.num(hi, 0)}${unit}`;
  };
  T.iit = {
    id: "iit", name: "个人所得税", en: "Individual Income Tax", group: "税务",
    desc: "按综合所得年度税率表计算全年个税，并比较年终奖并入综合所得和单独计税哪种更省。",
    keywords: "个税 个人所得税 年度汇算 综合所得 年终奖 全年一次性奖金 专项附加扣除 速算扣除数 iit tax",
    kb: [],
    defaults: () => ({ income: 300000, bonus: 36000, social: 30000, special: 24000, other: 0 }),
    view(st, ui) {
      const o = { onChange: ui.update };
      const inputs = [
        num(st, "income", "全年工资薪金等收入", { ...o, unit: "元", hint: "不含年终奖；劳务报酬、稿酬、特许权使用费按规定折算后可一并填入。" }),
        num(st, "bonus", "全年一次性奖金（年终奖）", { ...o, unit: "元", hint: "没有可填 0。" }),
        num(st, "social", "专项扣除", { ...o, unit: "元", hint: "个人缴纳的养老、医疗、失业保险和住房公积金，全年合计。" }),
        num(st, "special", "专项附加扣除", { ...o, unit: "元", hint: "子女教育、继续教育、大病医疗、住房贷款利息或租金、赡养老人、婴幼儿照护，全年合计。" }),
        num(st, "other", "其他扣除", { ...o, unit: "元", hint: "如个人养老金、符合规定的商业健康保险等。" }),
      ];
      const results = () => {
        if (!need(st.income)) return missing();
        const v = (x) => (isNum(x) ? x : 0);
        const r = Fin.iit({ income: v(st.income), bonus: v(st.bonus), social: v(st.social), special: v(st.special), other: v(st.other) });
        const hasBonus = v(st.bonus) > 0;
        const chosen = r.best === "separate" ? r.separate.regular : r.merged;
        const rows = [
          { label: "收入合计", value: F.num(r.gross, 0) },
          { label: "减除费用与各项扣除", value: F.num(r.deductions, 0), sub: true },
          { label: hasBonus && r.best === "separate" ? "应纳税所得额（不含年终奖）" : "应纳税所得额", value: F.num(chosen.taxable, 0) },
          { label: "适用税率", value: F.pct(chosen.rate, 0), sub: true },
          { label: "速算扣除数", value: F.num(chosen.quick, 0), sub: true },
          hasBonus && r.best === "separate" ? { label: "年终奖单独计税", value: F.num(r.separate.bonus.tax, 0), sub: true } : null,
          { label: "全年应纳个税", value: F.num(r.tax, 0), total: true },
          { label: "实际税负率", value: F.pct(r.effective) },
          { label: "税后收入（扣除专项扣除和个税）", value: F.num(r.afterTax, 0) },
        ];
        const out = [App.ledger(rows, hasBonus ? (r.best === "separate" ? "按年终奖单独计税" : "按并入综合所得计税") : "结果")];
        if (hasBonus) {
          out.push(h("div.table-wrap", h("table.data.small",
            h("thead", h("tr", h("th", "计税方式"), h("th.num", "全年个税"), h("th.num", "税后收入"))),
            h("tbody", [["并入综合所得", r.merged.tax], ["年终奖单独计税", r.separate.tax]].map(([k, tax]) =>
              h("tr", h("td", k), h("td.num" + (tax === r.tax ? ".best" : ""), F.num(tax, 0)), h("td.num", F.num(r.gross - v(st.social) - tax, 0))))))));
        }
        const b = Fin.bonusTax(v(st.bonus));
        const cliff = hasBonus && b.bracket > 0 ? (Fin.IIT_MONTHLY[b.bracket - 1][0] * 12) : null;
        out.push(h("div.table-wrap", h("table.data.small",
          h("caption", "综合所得年度税率表"),
          h("thead", h("tr", h("th", "全年应纳税所得额"), h("th.num", "税率"), h("th.num", "速算扣除数"))),
          h("tbody", Fin.IIT_ANNUAL.map(([, rate, quick], i) =>
            h("tr" + (i === chosen.bracket ? ".em" : ""), h("td", BRACKET_LABEL(Fin.IIT_ANNUAL, i, " 元")), h("td.num", F.pct(rate, 0)), h("td.num", F.num(quick, 0))))))));
        out.push(readout("怎么读",
          `应纳税所得额 = 收入 − 6 万元基本减除费用 − 专项扣除 − 专项附加扣除 − 其他扣除。你的边际税率是 ${F.pct(chosen.rate, 0)}，也就是每多 1 元应纳税所得额，要多交 ${F.num(chosen.rate * 100, 0)} 分钱税。`,
          hasBonus
            ? (r.saving < 1 ? "两种计税方式税额相同。"
              : `年终奖${r.best === "separate" ? "单独计税" : "并入综合所得"}更省，少交 ${F.num(r.saving, 0)} 元。年度汇算时可以自己选择对你有利的方式。`)
              + (cliff && v(st.bonus) - cliff < cliff * 0.1 ? `注意：年终奖刚超过 ${F.num(cliff, 0)} 元的临界点，多发一点反而可能到手更少。` : "")
            : "如果有年终奖，填进去可以比较两种计税方式。",
          "全年一次性奖金单独计税政策执行至 2027 年 12 月 31 日。税率表和扣除标准以国家税务总局最新规定为准，本工具仅供估算。"));
        return out;
      };
      return { inputs, results };
    },
  };

  /* ---------------- 状态编码（分享链接） ---------------- */
  function encodeState(obj) {
    const json = JSON.stringify(obj);
    return btoa(unescape(encodeURIComponent(json))).replace(/\+/g, "-").replace(/\//g, "_").replace(/=+$/, "");
  }
  function decodeState(s) {
    try {
      const b = s.replace(/-/g, "+").replace(/_/g, "/");
      return JSON.parse(decodeURIComponent(escape(atob(b))));
    } catch { return null; }
  }
  App.encodeState = encodeState;
  App.decodeState = decodeState;
  App.TOOL_ORDER = ["project", "breakeven", "cashflow", "workingcap", "dupont", "pricing", "wacc", "loan", "matrix", "ev", "iit"];
})();
