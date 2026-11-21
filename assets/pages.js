/* 星图智策 — 页面 */
(function () {
  "use strict";
  const { h, F, isNum, pages } = App;
  const Fin = window.Fin;

  const KIND = { news: "文章", policy: "政策" };
  const REGION = { cn: "国内", intl: "国际" };
  const MARKET = { a: "A 股", hk: "港股", us: "美股" };

  function pageHead(title, lead, extra) {
    return h("header.page-head", h("h1", title), lead ? h("p.lead", lead) : null, extra || null);
  }
  function debounce(fn, ms) { let t; return (...a) => { clearTimeout(t); t = setTimeout(() => fn(...a), ms); }; }
  async function tryLoad(path) { try { return await App.load(path); } catch { return null; } }

  /* =====================================================================
     首页
     ===================================================================== */
  pages.home = async function (main) {
    const [kb, news, idx, home] = await Promise.all([tryLoad("kb.json"), tryLoad("news.json"), tryLoad("companies/index.json"), tryLoad("home.json")]);
    const mk = (home && home.markets) || {};
    const ai = (home && home.ai) || {};
    const WEEK = ["日", "一", "二", "三", "四", "五", "六"];

    /* ---- 搜索：工具、方法、公司 ---- */
    const results = h("ul.search-results", { role: "listbox", "aria-label": "搜索结果" });
    const input = h("input#home-q", { type: "search", placeholder: "搜索工具、方法和公司，例如：盈亏平衡、个税、杜邦、茅台", autocomplete: "off", "aria-label": "搜索工具、方法和公司" });
    const runSearch = debounce(async () => {
      const list = await App.searchAll(input.value);
      results.innerHTML = "";
      results.hidden = !input.value.trim();
      if (!list.length && input.value.trim()) results.append(h("li.empty-row", "没有找到。试试换个说法，或者直接浏览下面的栏目。"));
      for (const r of list) results.append(h("li", h("a", { href: r.href }, h("span.k", r.kind), h("b", r.title), h("span.d", r.desc))));
    }, 150);
    input.addEventListener("input", runSearch);
    results.hidden = true;

    /* ---- 首屏：日期、标题、搜索、主要行情 ---- */
    const now = new Date();
    const dateLine = `${now.getMonth() + 1}月${now.getDate()}日 星期${WEEK[now.getDay()]}` + (mk.updated ? `，行情更新于 ${F.ago(mk.updated)}` : "");
    let updown = "red";
    try { updown = JSON.parse(localStorage.getItem("fr.updown")) || "red"; } catch { /* 默认红涨绿跌 */ }
    const dirCls = (v) => (!isNum(v) || v === 0 ? "flat" : (v > 0) === (updown === "red") ? "red" : "green");
    const signed = (v, d, unit) => (isNum(v) ? (v > 0 ? "+" : v < 0 ? "−" : "") + F.num(Math.abs(v), d) + unit : "–");
    const ticker = (mk.quotes || []).length
      ? h("ul.ticker", { "aria-label": "主要行情" }, mk.quotes.map((q) => {
        const bp = q.change_unit === "bp";
        const move = bp ? q.chg : q.pct;
        return h("li", h("a", { href: "markets/", title: q.stale ? "数据未能及时更新，显示的是上一次的值" : "查看行情快讯" },
          h("span.q-name", q.name + (q.stale ? " *" : "")),
          h("b.q-last", (q.unit === "$" ? "$" : "") + F.num(q.last, q.decimals ?? 2) + (q.unit === "%" ? "%" : "")),
          h("span.q-chg." + dirCls(move), bp ? signed(q.chg, 1, " 基点") : signed(q.pct, 2, "%"))));
      }))
      : h("p.ticker-empty", "行情数据会在第一次自动更新后显示在这里。");

    const hero = h("section.hero",
      h("div.wrap",
        h("p.hero-date", dateLine),
        h("h1", "兼听则明"),
        h("p.lead", "行情与快讯、管理资讯与财税政策、11 个财务决策工具、40 篇管理方法讲解、上市公司财报对比，以及 AI 前沿研究，每天自动更新。"),
        h("div.hero-search", input, results)),
      h("div.wrap.ticker-wrap", ticker));

    /* ---- 第一排：快讯、资讯、AI ---- */
    const flash = (mk.flash || []).length
      ? h("ul.flash-mini", mk.flash.map((i) => h("li" + (i.important ? ".imp" : ""),
        h("time", i.date ? F.time(i.date) : ""),
        h("div", i.url ? h("a", { href: i.url, target: "_blank", rel: "noopener" }, i.title) : h("span.t", i.title),
          h("span.meta", (i.important ? "重要，" : "") + i.source)))))
      : h("p.muted", "快讯每 30 分钟自动更新。");

    const latest = (news && news.items || []).filter((i) => !i.backfill).slice(0, 7);
    const newsList = latest.length
      ? h("ul.news-mini", latest.map((i) => h("li", h("a", { href: i.url, target: "_blank", rel: "noopener" }, i.title),
        h("span.meta", (news.sources[i.source] || i.source) + "，" + F.ago(i.date)))))
      : h("p.muted", "资讯会在部署后由 GitHub Actions 自动抓取。");

    const TYPE = { paper: "论文", repo: "代码", model: "模型", dataset: "数据集" };
    const aiTopics = (ai.topics || []).filter((t) => t.count_7d > 0);
    const aiList = (ai.picks || []).length
      ? h("ul.news-mini.ai-mini", ai.picks.map((i) => h("li",
        h("a", { href: i.url, target: "_blank", rel: "noopener" }, i.title),
        h("span.meta", [TYPE[i.type] || "", ...(i.topics || [])].filter(Boolean).join("，") + (i.date ? "，" + F.ago(i.date) : "")))))
      : h("p.muted", "AI 前沿每天自动更新一次。");
    const aiChips = aiTopics.length
      ? h("p.topic-line", h("span", "近 7 天"), aiTopics.map((t) => h("a", { href: `ai/#topic=${t.id}` }, `${t.name} ${t.count_7d}`)))
      : null;

    /* ---- 第二排：工具、知识库、公司 ---- */
    const toolList = h("ul.tool-list", App.TOOL_ORDER.slice(0, 6).map((id) => {
      const t = App.tools[id];
      return h("li", h("a", { href: `#/tools/${id}` }, h("b", t.name), h("span", t.desc)));
    }));
    const picks = ["three-statements", "cvp", "npv", "working-capital", "decision-matrix", "cas-system"];
    const kbList = kb ? h("ul.kb-mini", picks.map((id) => kb.articles.find((a) => a.id === id)).filter(Boolean).map((a) =>
      h("li", h("a", { href: `#/kb/${a.id}` }, h("b", a.title), h("span", a.summary))))) : h("p.muted", "知识库正在生成。");
    const nCo = idx && idx.companies ? idx.companies.length : 0;
    const coBlock = h("div.co-block",
      h("p", nCo ? `${nCo} 家 A 股、港股、美股公司近 5 年的盈利、营运、偿债和现金流指标，按行业给出中位数，自动标出值得注意的变化。`
        : "A 股、港股、美股上市公司近 5 年的财务指标与同行对比，每周自动更新。"),
      h("p", h("a.btn", { href: "#/company" }, "查看公司列表")),
      h("p.co-mine", "也可以输入自家公司两年的主要报表数字，得到同样的比率、杜邦分解和提示，数据只保存在你的浏览器里。"),
      h("p", h("a.btn.ghost", { href: "#/mine" }, "分析我的公司")));

    const sec = (title, href, more, body, extra) =>
      h("section.home-sec", h("div.sec-head", h("h2", h("a", { href }, title)), h("a.more-link", { href }, more)), body, extra || null);

    main.append(hero,
      h("div.wrap.home-cols",
        sec("7×24 快讯", "markets/", "进入行情快讯", flash),
        sec("资讯与政策", "#/news", "全部资讯", newsList),
        sec("AI 前沿", "ai/", "进入 AI 前沿", aiList, aiChips)),
      h("div.wrap.home-cols.second",
        sec("财务决策工具", "#/tools", `全部 ${App.TOOL_ORDER.length} 个工具`, toolList),
        sec("管理方法", "#/kb", `全部 ${kb ? kb.articles.length : 40} 篇`, kbList),
        sec("上市公司财报", "#/company", "公司列表", coBlock)));
  };

  /* =====================================================================
     资讯
     ===================================================================== */
  pages.news = async function (main, r) {
    const data = await App.load("news.json");
    const st = { topic: r.query.get("topic") || "all", region: r.query.get("region") || "all", kind: r.query.get("kind") || "all", q: r.query.get("q") || "" };
    const list = h("div.news-list");
    const count = h("p.count", { "aria-live": "polite" });
    const chips = (key, opts) => h("div.chips", { role: "radiogroup" }, opts.map(([v, t]) => {
      const b = h("button.chip", { type: "button", role: "radio", "aria-checked": String(st[key] === v), onclick: () => {
        st[key] = v; App.setQuery({ [key]: v }); b.parentNode.querySelectorAll(".chip").forEach((x) => x.setAttribute("aria-checked", "false"));
        b.setAttribute("aria-checked", "true"); draw(); } }, t);
      return b;
    }));
    const q = h("input", { type: "search", value: st.q, placeholder: "搜索标题和摘要", "aria-label": "搜索资讯" });
    q.addEventListener("input", debounce(() => { st.q = q.value.trim(); App.setQuery({ q: st.q }); draw(); }, 200));
    let shown = 50;
    function draw() {
      const terms = st.q.toLowerCase().split(/\s+/).filter(Boolean);
      const items = data.items.filter((i) =>
        (st.topic === "all" || i.topics.includes(st.topic)) && (st.region === "all" || i.region === st.region) &&
        (st.kind === "all" || i.kind === st.kind) && terms.every((t) => (i.title + " " + (i.summary || "")).toLowerCase().includes(t)));
      list.innerHTML = "";
      count.textContent = `${items.length} 条`;
      let lastDay = "";
      for (const i of items.slice(0, shown)) {
        const day = F.date(i.date);
        if (day !== lastDay && !i.backfill) { list.append(h("h2.day", day)); lastDay = day; }
        if (i.backfill && lastDay !== "backfill") { list.append(h("h2.day", "首次收录（发布日期未知）")); lastDay = "backfill"; }
        list.append(h("article.news-item",
          h("h3", h("a", { href: i.url, target: "_blank", rel: "noopener" }, i.title)),
          i.summary ? h("p", i.summary) : null,
          h("p.meta", h("span.src", data.sources[i.source] || i.source), i.via ? h("span", "经 " + i.via) : null,
            h("span", KIND[i.kind] || ""), i.date_estimated && !i.backfill ? h("span", "收录于 " + F.date(i.first_seen)) : null,
            i.topics.map((t) => h("span.tag", (data.topics.find((x) => x.id === t) || {}).name || t)))));
      }
      if (items.length > shown) list.append(h("div.more", h("button.btn.ghost", { type: "button", onclick: () => { shown += 50; draw(); } }, `再显示 ${Math.min(50, items.length - shown)} 条`)));
      if (!items.length) list.append(h("p.empty", data.items.length ? "没有符合条件的资讯，换个分类试试。" : "还没有资讯数据。"));
    }
    main.append(h("div.wrap",
      pageHead("资讯与政策", `汇总四大会计师事务所洞察、哈佛商业评论等管理研究机构、澎湃等财经媒体，以及财政部、证监会、税务总局、国资委等部门的最新发布。更新于 ${F.ago(data.updated)}。`),
      h("div.filters",
        h("div.search-box", q),
        chips("topic", [["all", "全部主题"], ...data.topics.map((t) => [t.id, t.name])]),
        h("div.chip-row", chips("region", [["all", "全部地区"], ["cn", "国内"], ["intl", "国际"]]), chips("kind", [["all", "全部类型"], ["policy", "政策与监管"], ["news", "文章"]]))),
      count, list));
    draw();
  };

  /* =====================================================================
     工具
     ===================================================================== */
  pages.tools = async function (main, r) {
    if (!r.param) {
      const groups = {};
      for (const id of App.TOOL_ORDER) (groups[App.tools[id].group] ||= []).push(App.tools[id]);
      main.append(h("div.wrap",
        pageHead("财务决策工具", "所有计算都在你的浏览器里完成，输入的数字不会上传。每个工具都可以生成链接，分享给同事查看同样的输入。"),
        Object.entries(groups).map(([g, ts]) => h("section.tool-group", h("h2", g),
          h("ul.tool-list.wide", ts.map((t) => h("li", h("a", { href: `#/tools/${t.id}` }, h("b", t.name), h("span.en", t.en), h("span", t.desc))))))),
        (window.SITE_LINKS || []).length ? h("section.tool-group.links",
          h("h2", "常用网站"),
          h("div.link-groups", window.SITE_LINKS.map((g) => h("div", h("h3", g.name),
            h("ul", g.links.map((l) => h("li", h("a", { href: l.url, target: "_blank", rel: "noopener" }, l.title), h("span", l.note || "")))))))) : null));
      return;
    }
    const tool = App.tools[r.param];
    if (!tool) return pages.notfound(main);
    const shared = r.query.get("s") ? App.decodeState(r.query.get("s")) : null;
    const state = Object.assign(tool.defaults(), shared || {});
    const resultsBox = h("div.results", { "aria-live": "polite" });
    const ui = {
      update: debounce(() => {
        resultsBox.innerHTML = "";
        const out = view.results();
        (Array.isArray(out) ? out : [out]).forEach((x) => x && resultsBox.append(x));
        App.setQuery({ s: App.encodeState(state) });
      }, 120),
    };
    const view = tool.view(state, ui);
    const kb = await tryLoad("kb.json");
    const related = kb ? tool.kb.map((id) => kb.articles.find((a) => a.id === id)).filter(Boolean) : [];
    const copy = h("button.btn.ghost.small", { type: "button", onclick: async () => {
      try { await navigator.clipboard.writeText(location.href); copy.textContent = "链接已复制"; }
      catch { copy.textContent = "请从地址栏复制链接"; }
      setTimeout(() => (copy.textContent = "复制分享链接"), 2000);
    } }, "复制分享链接");
    const reset = h("button.btn.ghost.small", { type: "button", onclick: () => { App.setQuery({ s: null }); App.render(); } }, "恢复示例数据");
    main.append(h("div.wrap",
      h("nav.crumbs", h("a", { href: "#/tools" }, "工具"), h("span", tool.group)),
      pageHead(tool.name, tool.desc, h("div.head-actions", copy, reset)),
      h("div.tool-layout" + (tool.wide ? ".wide" : ""),
        h("form.tool-inputs", { onsubmit: (e) => e.preventDefault(), "aria-label": "输入" }, view.inputs),
        h("div.tool-out", resultsBox,
          related.length ? h("aside.related", h("h3", "相关方法"), h("ul", related.map((a) => h("li", h("a", { href: `#/kb/${a.id}` }, a.title))))) : null))));
    const out = view.results();
    (Array.isArray(out) ? out : [out]).forEach((x) => x && resultsBox.append(x));
  };

  /* =====================================================================
     知识库
     ===================================================================== */
  pages.kb = async function (main, r) {
    const kb = await App.load("kb.json");
    if (r.param) {
      const a = kb.articles.find((x) => x.id === r.param);
      if (!a) return pages.notfound(main);
      const cat = kb.categories.find((c) => c.id === a.category);
      const sameCat = kb.articles.filter((x) => x.category === a.category);
      const i = sameCat.indexOf(a);
      const body = h("div.prose", { html: a.html });
      // 正文里的站内链接保持在当前页打开，外部链接新窗口打开
      body.querySelectorAll("a[href^='http']").forEach((l) => { l.target = "_blank"; l.rel = "noopener"; });
      body.querySelectorAll("table").forEach((t) => t.replaceWith(h("div.table-wrap", t.cloneNode(true))));
      main.append(h("div.wrap.article-wrap",
        h("nav.crumbs", h("a", { href: "#/kb" }, "知识库"), h("a", { href: `#/kb?cat=${a.category}` }, cat ? cat.name : "")),
        h("article.article",
          h("header.page-head", h("h1", a.title), a.en ? h("p.en", a.en) : null, h("p.lead", a.summary)),
          a.toc.length > 2 ? h("nav.toc", { "aria-label": "本文目录" }, h("ol", a.toc.map((t) => h("li", h("button.linklike", { type: "button", onclick: () => document.getElementById(t.id)?.scrollIntoView({ behavior: "smooth" }) }, t.name))))) : null,
          body,
          a.tools.length ? h("aside.callout", h("h3", "动手算一算"), h("ul", a.tools.map((id) => App.tools[id] && h("li", h("a", { href: `#/tools/${id}` }, App.tools[id].name), "：", App.tools[id].desc)))) : null,
          a.sources.length ? h("aside.sources", h("h3", "延伸阅读"), h("ul", a.sources.map((s) => h("li", h("a", { href: s.url, target: "_blank", rel: "noopener" }, s.title))))) : null,
          a.related.length ? h("aside.related-arts", h("h3", "相关方法"), h("ul", a.related.map((id) => kb.articles.find((x) => x.id === id)).filter(Boolean).map((x) => h("li", h("a", { href: `#/kb/${x.id}` }, h("b", x.title), h("span", x.summary)))))) : null,
          h("nav.pager", i > 0 ? h("a.prev", { href: `#/kb/${sameCat[i - 1].id}` }, h("span", "上一篇"), sameCat[i - 1].title) : h("span"),
            i < sameCat.length - 1 ? h("a.next", { href: `#/kb/${sameCat[i + 1].id}` }, h("span", "下一篇"), sameCat[i + 1].title) : h("span")))));
      return;
    }
    const st = { cat: r.query.get("cat") || "all", q: r.query.get("q") || "" };
    const listBox = h("div");
    const q = h("input", { type: "search", value: st.q, placeholder: "搜索方法、术语，如“现金流”“IFRS 16”", "aria-label": "搜索知识库" });
    q.addEventListener("input", debounce(() => { st.q = q.value.trim(); App.setQuery({ q: st.q }); draw(); }, 150));
    const chips = h("div.chips", { role: "radiogroup" }, [["all", "全部"], ...kb.categories.map((c) => [c.id, c.name])].map(([v, t]) => {
      const b = h("button.chip", { type: "button", role: "radio", "aria-checked": String(st.cat === v), onclick: () => {
        st.cat = v; App.setQuery({ cat: v }); chips.querySelectorAll(".chip").forEach((x) => x.setAttribute("aria-checked", String(x === b))); draw(); } }, t);
      return b;
    }));
    function draw() {
      const terms = st.q.toLowerCase().split(/\s+/).filter(Boolean);
      listBox.innerHTML = "";
      let n = 0;
      for (const c of kb.categories) {
        if (st.cat !== "all" && st.cat !== c.id) continue;
        const arts = kb.articles.filter((a) => a.category === c.id &&
          terms.every((t) => (a.title + a.en + a.summary + a.text).toLowerCase().includes(t)));
        if (!arts.length) continue;
        n += arts.length;
        listBox.append(h("section.kb-cat", h("h2", c.name),
          h("ul.kb-list", arts.map((a) => h("li", h("a", { href: `#/kb/${a.id}` }, h("b", a.title), a.en ? h("span.en", a.en) : null, h("span", a.summary)))))));
      }
      if (!n) listBox.append(h("p.empty", "没有找到相关文章。"));
    }
    main.append(h("div.wrap", pageHead("管理方法知识库", `${kb.articles.length} 篇文章，覆盖战略、组织、决策、财务分析、投资融资、预算成本、风险治理和会计准则。每篇都说明用途、步骤、示例和常见误区。`),
      h("div.filters", h("div.search-box", q), chips), listBox));
    draw();
  };

  /* =====================================================================
     公司财报
     ===================================================================== */
  const RATIO_ROWS = [
    ["盈利能力", [["grossMargin", "毛利率", "pct"], ["operatingMargin", "营业利润率", "pct"], ["netMargin", "净利率", "pct"], ["roe", "ROE", "pct"], ["roa", "ROA", "pct"]]],
    ["营运能力", [["assetTurnover", "总资产周转率", "x"], ["dso", "应收账款周转天数", "days"], ["dio", "存货周转天数", "days"], ["dpo", "应付账款周转天数", "days"], ["ccc", "现金周转周期", "days"]]],
    ["偿债能力", [["debtRatio", "资产负债率", "pct"], ["currentRatio", "流动比率", "x"], ["quickRatio", "速动比率", "x"], ["equityMultiplier", "权益乘数", "x"]]],
    ["成长与现金", [["revenueGrowth", "收入增长率", "spct"], ["profitGrowth", "归母净利润增长率", "spct"], ["cfoToNetIncome", "经营现金流 / 净利润", "x"], ["rdRatio", "研发费用率", "pct"]]],
  ];
  const fmtBy = (kind, v) => kind === "pct" ? F.pct(v) : kind === "spct" ? F.signedPct(v) : kind === "days" ? F.days(v) : F.num(v);

  pages.company = async function (main, r) {
    const idx = await App.load("companies/index.json");
    if (r.param) return companyDetail(main, r.param, idx);
    const st = { market: r.query.get("market") || "all", ind: r.query.get("ind") || "all", sort: r.query.get("sort") || "roe", q: r.query.get("q") || "" };
    const tableBox = h("div.table-wrap");
    const cols = [["name", "公司"], ["industry_name", "行业"], ["latest", "最新年报"], ["revenue", "营业收入"], ["grossMargin", "毛利率"], ["netMargin", "净利率"], ["roe", "ROE"], ["debtRatio", "资产负债率"], ["revenueGrowth", "收入增长"], ["watch", "提示"]];
    const q = h("input", { type: "search", value: st.q, placeholder: "公司名称或代码", "aria-label": "搜索公司" });
    q.addEventListener("input", debounce(() => { st.q = q.value.trim(); App.setQuery({ q: st.q }); draw(); }, 150));
    const mk = (key, opts) => {
      const sel = h("select", { "aria-label": key === "market" ? "市场" : "行业" }, opts.map(([v, t]) => h("option", { value: v, selected: st[key] === v }, t)));
      sel.onchange = () => { st[key] = sel.value; App.setQuery({ [key]: sel.value }); draw(); };
      return h("label.select", sel);
    };
    function draw() {
      const val = (c, k) => (k in c.ratios ? c.ratios[k] : c[k]);
      let rows = idx.companies.filter((c) => (st.market === "all" || c.market === st.market) && (st.ind === "all" || c.industry === st.ind) &&
        (!st.q || (c.name + c.code).toLowerCase().includes(st.q.toLowerCase())));
      const dir = ["name", "industry_name", "latest"].includes(st.sort) ? 1 : -1;
      rows = rows.sort((a, b) => {
        const x = val(a, st.sort), y = val(b, st.sort);
        if (x == null) return 1; if (y == null) return -1;
        return typeof x === "string" ? x.localeCompare(y, "zh") * dir : (x - y) * dir;
      });
      const th = (k, t) => {
        const b = h("button.sort", { type: "button", "aria-sort": st.sort === k ? "descending" : "none", onclick: () => { st.sort = k; App.setQuery({ sort: k }); draw(); } }, t);
        return h(["name", "industry_name", "latest"].includes(k) ? "th" : "th.num", b);
      };
      tableBox.innerHTML = "";
      tableBox.append(h("table.data.companies",
        h("thead", h("tr", cols.map(([k, t]) => th(k, t)))),
        h("tbody", rows.map((c) => h("tr",
          h("td", h("a", { href: `#/company/${c.id}` }, h("b", c.name)), h("span.code", `${MARKET[c.market]} ${c.code}`), c.stale ? h("span.stale", { title: "本次更新失败，显示上次数据" }, "旧") : null),
          h("td", c.industry_name), h("td", c.latest),
          h("td.num", F.big(c.revenue, c.currency)),
          ["grossMargin", "netMargin", "roe", "debtRatio"].map((k) => h("td.num", F.pct(c.ratios[k]))),
          h("td.num", F.signedPct(c.ratios.revenueGrowth)),
          h("td.num", c.watch ? h("span.watch-n", { title: "值得关注的变化" }, String(c.watch)) : ""))))));
      if (!rows.length) tableBox.append(h("p.empty", "没有符合条件的公司。"));
    }
    main.append(h("div.wrap",
      pageHead("上市公司财报对比", `${idx.companies.length} 家公司的年度财报指标，同行业对比，自动标出值得注意的变化。点击表头排序，点击公司名查看详情。财报数据每周更新一次，最近更新 ${F.ago(idx.updated)}。`),
      h("div.filters.inline", h("div.search-box", q),
        mk("market", [["all", "全部市场"], ["a", "A 股"], ["hk", "港股"], ["us", "美股"]]),
        mk("ind", [["all", "全部行业"], ...idx.industries.map((i) => [i.id, i.name])])),
      tableBox,
      h("p.note", "营业收入按各公司报告币种列示；比率不受币种影响，可以跨市场比较，但要注意会计准则差异（参见",
        h("a", { href: "#/kb/cas-ifrs-differences" }, "准则差异"), "）。数据来自东方财富和 SEC，可能存在抽取误差，重要决策请以公司公告原文为准。")));
    draw();
  };

  async function companyDetail(main, id, idx) {
    const c = await App.load(`companies/${id}.json`);
    const ind = idx.industries.find((i) => i.id === c.industry) || { median: {} };
    const med = ind.median || {};
    const ps = c.periods;
    const last = ps[ps.length - 1];
    const labels = ps.map((p) => p.label);
    const R = (k) => ps.map((p) => p.ratios[k]);
    const cur = c.currency;
    const scale = (v) => (isNum(v) ? v / 1e8 : null);
    const unitName = "亿" + ({ CNY: "元", HKD: "港元", USD: "美元", 人民币: "元", 港币: "港元", 港元: "港元", 美元: "美元" }[cur] || " " + cur);

    const kpis = [
      ["营业收入", F.big(last.revenue, cur), last.ratios.revenueGrowth, "spct"],
      ["归母净利润", F.big(last.netIncome, cur), last.ratios.profitGrowth, "spct"],
      ["毛利率", F.pct(last.ratios.grossMargin), med.grossMargin, "med"],
      ["ROE", F.pct(last.ratios.roe), med.roe, "med"],
      ["资产负债率", F.pct(last.ratios.debtRatio), med.debtRatio, "med"],
      ["经营现金流 / 净利润", F.x(last.ratios.cfoToNetIncome), null, null],
    ];
    const obs = c.observations || [];
    const peers = idx.companies.filter((x) => c.peers.includes(x.id));

    main.append(h("div.wrap",
      h("nav.crumbs", h("a", { href: "#/company" }, "公司财报"), h("a", { href: `#/company?ind=${c.industry}` }, c.industry_name)),
      pageHead(c.name, null, h("p.lead.co-meta", `${MARKET[c.market]} ${c.code}，${c.industry_name}，${c.standard || ""}，报告币种 ${cur}。最新年报 ${last.label}（截至 ${last.end}）。`,
        c.stale ? h("span.stale-note", "本次更新失败，显示的是上次获取的数据。") : null)),
      h("div.kpis", kpis.map(([k, v, d, kind]) => h("div.kpi", h("span.k", k), h("b", v),
        kind === "spct" && isNum(d) ? h("span.d", "同比 " + F.signedPct(d)) : kind === "med" && isNum(d) ? h("span.d", "同行中位数 " + F.pct(d)) : h("span.d", " ")))),
      obs.length ? h("section.obs", h("h2", "值得注意"), h("ul", obs.map((o) => h("li." + o.level, o.text))),
        h("p.note", "以上为根据公开财报数据按固定规则生成的观察，只描述数据呈现的现象，不构成投资建议。")) : null,
      h("div.two-col",
        App.chart({ title: `营业收入与归母净利润（${unitName}）`, kind: "bar", labels, height: 220,
          series: [{ name: "营业收入", values: ps.map((p) => scale(p.revenue)) }, { name: "归母净利润", values: ps.map((p) => scale(p.netIncome)) }],
          fmt: (v) => F.num(v, Math.abs(v) < 10 ? 1 : 0) }),
        App.chart({ title: "利润率", labels, height: 220, fmt: (v) => F.pct(v, 0),
          series: [{ name: "毛利率", values: R("grossMargin") }, { name: "营业利润率", values: R("operatingMargin") }, { name: "净利率", values: R("netMargin") }] })),
      h("div.two-col",
        App.chart({ title: `净利润与经营现金流（${unitName}）`, kind: "bar", labels, height: 220,
          series: [{ name: "归母净利润", values: ps.map((p) => scale(p.netIncome)) }, { name: "经营现金流", values: ps.map((p) => scale(p.cfo)) }, { name: "自由现金流", values: R("fcf").map(scale) }],
          fmt: (v) => F.num(v, Math.abs(v) < 10 ? 1 : 0) }),
        App.chart({ title: "周转天数", labels, height: 220, fmt: (v) => F.num(v, 0) + " 天",
          series: [{ name: "应收", values: R("dso") }, { name: "存货", values: R("dio") }, { name: "应付", values: R("dpo") }] })),
      h("section.dupont-sec", h("h2", `杜邦分析（${last.label}）`),
        App.dupontTree({ roe: last.ratios.roe, roa: last.ratios.roa, margin: last.ratios.netMargin, turnover: last.ratios.assetTurnover, multiplier: last.ratios.equityMultiplier }, med),
        h("p.note", `同行中位数来自本站收录的 ${med._n || 0} 家“${c.industry_name}”公司的最新年报，`, h("a", { href: "#/kb/dupont" }, "杜邦分析怎么读"), "。")),
      h("section", h("h2", "财务比率"),
        h("div.table-wrap", h("table.data.ratios",
          h("thead", h("tr", h("th", ""), labels.map((l) => h("th.num", l)), h("th.num.med", "同行中位数"))),
          RATIO_ROWS.map(([g, rows]) => h("tbody", h("tr.group", h("th", { colSpan: labels.length + 2 }, g)),
            rows.map(([k, name, kind]) => h("tr", h("th", name), ps.map((p) => h("td.num", fmtBy(kind, p.ratios[k]))), h("td.num.med", fmtBy(kind, med[k]))))))))),
      h("section", h("h2", "主要报表项目"),
        h("div.table-wrap", h("table.data",
          h("thead", h("tr", h("th", unitName), labels.map((l) => h("th.num", l)))),
          h("tbody", [["revenue", "营业收入"], ["grossProfit", "毛利"], ["operatingProfit", "营业利润"], ["netIncome", "归母净利润"], ["rd", "研发费用"],
            ["totalAssets", "总资产"], ["totalLiabilities", "总负债"], ["equity", "归母净资产"], ["cash", "货币资金"], ["receivables", "应收账款"], ["inventory", "存货"],
            ["cfo", "经营活动现金流"], ["capex", "资本开支"]].map(([k, name]) => h("tr", h("th", name), ps.map((p) => {
            const v = k === "grossProfit" && !isNum(p[k]) && isNum(p.revenue) && isNum(p.cost) ? p.revenue - p.cost : p[k];
            return h("td.num", isNum(v) ? F.num(v / 1e8, 2) : "–");
          }))))))),
      peers.length ? h("section", h("h2", `同行业公司`), h("ul.peer-list", peers.map((p) => h("li", h("a", { href: `#/company/${p.id}` }, p.name),
        h("span", `毛利率 ${F.pct(p.ratios.grossMargin)}，ROE ${F.pct(p.ratios.roe)}`))))) : null,
      h("p.note", "数据来源：", h("a", { href: c.source_url, target: "_blank", rel: "noopener" }, c.market === "us" ? "SEC EDGAR" : "东方财富"),
        `，获取于 ${F.date(c.fetched)}。比率按期初期末平均余额计算，可能与公司公告口径略有差异。`)));
  }

  /* =====================================================================
     分析自己的公司
     ===================================================================== */
  const MINE_FIELDS = [
    ["利润表", [["revenue", "营业收入"], ["cost", "营业成本"], ["operatingProfit", "营业利润"], ["netIncome", "净利润"], ["rd", "研发费用"]]],
    ["资产负债表（期末）", [["totalAssets", "总资产"], ["totalLiabilities", "总负债"], ["equity", "所有者权益"], ["currentAssets", "流动资产"], ["currentLiabilities", "流动负债"],
      ["cash", "货币资金"], ["receivables", "应收账款"], ["inventory", "存货"], ["payables", "应付账款"]]],
    ["现金流量表", [["cfo", "经营活动现金流量净额"], ["capex", "购建长期资产支付的现金"]]],
  ];
  const MINE_SAMPLE = {
    name: "示例：某制造企业",
    cur: { revenue: 12000, cost: 8400, operatingProfit: 1100, netIncome: 860, rd: 420, totalAssets: 15000, totalLiabilities: 8200, equity: 6800, currentAssets: 8600, currentLiabilities: 6100, cash: 1800, receivables: 3300, inventory: 2600, payables: 1900, cfo: 620, capex: 900 },
    prev: { revenue: 10500, cost: 7150, operatingProfit: 1150, netIncome: 900, rd: 360, totalAssets: 13200, totalLiabilities: 6900, equity: 6300, currentAssets: 7400, currentLiabilities: 5000, cash: 2100, receivables: 2500, inventory: 2100, payables: 1800, cfo: 980, capex: 700 },
  };
  pages.mine = async function (main) {
    const KEY = "dd.mine";
    const data = App.store.get(KEY, null) || JSON.parse(JSON.stringify(MINE_SAMPLE));
    const out = h("div.mine-out", { "aria-live": "polite" });
    const save = debounce(() => App.store.set(KEY, data), 300);
    const table = h("table.grid.mine-grid",
      h("thead", h("tr", h("th", "项目"), h("th.num", "本年"), h("th.num", "上年"))),
      MINE_FIELDS.map(([g, rows]) => h("tbody", h("tr.group", h("th", { colSpan: 3 }, g)),
        rows.map(([k, name]) => h("tr", h("th", name),
          ["cur", "prev"].map((y) => {
            const i = h("input.cell", { type: "text", inputMode: "decimal", value: data[y][k] ?? "", "aria-label": `${name} ${y === "cur" ? "本年" : "上年"}` });
            i.addEventListener("input", () => { data[y][k] = F.parse(i.value); save(); draw(); });
            return h("td", i);
          }))))));
    function draw() {
      out.innerHTML = "";
      const cur = data.cur, prev = data.prev;
      if (!isNum(cur.revenue) || !isNum(cur.netIncome) || !isNum(cur.totalAssets)) {
        out.append(h("p.muted.pad", "至少填写本年的营业收入、净利润和总资产。"));
        return;
      }
      const rc = Fin.ratios(cur, prev), rp = Fin.ratios(prev, {});
      // 复用上市公司的观察规则：在前端做一个简化版本
      const notes = [];
      if (isNum(rc.revenueGrowth) && isNum(rc.profitGrowth) && rc.revenueGrowth > 0.05 && rc.profitGrowth < -0.05) notes.push(`收入增长 ${F.pct(rc.revenueGrowth)}，净利润下降 ${F.pct(-rc.profitGrowth)}：增收不增利，检查毛利率和费用率的变化。`);
      if (isNum(rc.grossMargin) && isNum(rp.grossMargin) && rc.grossMargin < rp.grossMargin - 0.02) notes.push(`毛利率从 ${F.pct(rp.grossMargin)} 降到 ${F.pct(rc.grossMargin)}。`);
      if (isNum(rc.cfoToNetIncome) && rc.cfoToNetIncome < 0.8) notes.push(`经营现金流只有净利润的 ${F.num(rc.cfoToNetIncome)} 倍，利润的现金含量偏低，关注应收和存货。`);
      if (isNum(cur.receivables) && isNum(prev.receivables) && isNum(rc.revenueGrowth) && prev.receivables > 0 && cur.receivables / prev.receivables - 1 > rc.revenueGrowth + 0.1)
        notes.push(`应收账款增长 ${F.pct(cur.receivables / prev.receivables - 1)}，明显快于收入增长。`);
      if (isNum(cur.inventory) && isNum(prev.inventory) && isNum(rc.revenueGrowth) && prev.inventory > 0 && cur.inventory / prev.inventory - 1 > rc.revenueGrowth + 0.1)
        notes.push(`存货增长 ${F.pct(cur.inventory / prev.inventory - 1)}，明显快于收入增长。`);
      if (isNum(rc.currentRatio) && rc.currentRatio < 1) notes.push(`流动比率 ${F.num(rc.currentRatio)}，短期偿债压力较大。`);
      if (isNum(rc.fcf) && rc.fcf < 0) notes.push(`自由现金流为负（${F.num(rc.fcf, 0)}），投资支出超过了经营现金流。`);
      out.append(
        notes.length ? h("section.obs", h("h2", "值得注意"), h("ul", notes.map((t) => h("li.watch", t)))) : h("section.obs", h("h2", "值得注意"), h("p", "按本站的规则没有发现明显异常。")),
        h("section.dupont-sec", h("h2", "杜邦分析"), App.dupontTree({ roe: rc.roe, roa: rc.roa, margin: rc.netMargin, turnover: rc.assetTurnover, multiplier: rc.equityMultiplier })),
        h("section", h("h2", "财务比率"), h("div.table-wrap", h("table.data.ratios",
          h("thead", h("tr", h("th", ""), h("th.num", "本年"), h("th.num.med", "上年（仅期末数）"))),
          RATIO_ROWS.map(([g, rows]) => h("tbody", h("tr.group", h("th", { colSpan: 3 }, g)),
            rows.map(([k, name, kind]) => h("tr", h("th", name), h("td.num", fmtBy(kind, rc[k])), h("td.num.med", fmtBy(kind, rp[k]))))))))),
        h("p.note", "本年比率用两年的平均余额计算；上年只有期末数，周转类和回报类指标仅供参考。想和上市公司比较，可以在",
          h("a", { href: "#/company" }, "公司列表"), "里按行业查看中位数。"));
    }
    main.append(h("div.wrap",
      pageHead("分析自己的公司", "填入两年的主要报表数字（单位自定，保持一致），得到盈利、营运、偿债、现金四类比率、杜邦分解和规则提示。数据只保存在这台设备的浏览器里，不会上传。",
        h("div.head-actions",
          h("button.btn.ghost.small", { type: "button", onclick: () => { Object.assign(data, JSON.parse(JSON.stringify(MINE_SAMPLE))); App.store.set(KEY, data); App.render(); } }, "填入示例数据"),
          h("button.btn.ghost.small", { type: "button", onclick: () => {
            for (const y of ["cur", "prev"]) for (const k of Object.keys(data[y])) data[y][k] = null;
            App.store.set(KEY, data); App.render(); } }, "清空"))),
      h("div.tool-layout.mine", h("div.tool-inputs", h("div.table-wrap", table)), out)));
    draw();
  };

  pages.notfound = async function (main) {
    main.append(h("div.wrap.notice", h("h1", "没有找到这个页面"), h("p", "链接可能已经失效。"), h("p", h("a", { href: "#/" }, "回到首页"))));
  };
})();
