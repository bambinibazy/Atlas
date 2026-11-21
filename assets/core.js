/* 星图智策 — 公共模块：路由、DOM 工具、格式化、图表、数据加载 */
(function () {
  "use strict";
  const App = (window.App = { pages: {}, tools: {}, data: {} });

  /* ---------------- DOM ---------------- */
  // h("div.cls#id", {attrs}, ...children)。文本一律走 textContent，不拼 HTML
  function h(tag, attrs, ...kids) {
    const m = tag.match(/^([a-z0-9]+)?((?:[.#][\w-]+)*)$/i);
    const el = document.createElement(m[1] || "div");
    (m[2].match(/[.#][\w-]+/g) || []).forEach((t) => (t[0] === "." ? el.classList.add(t.slice(1)) : (el.id = t.slice(1))));
    if (attrs && (typeof attrs !== "object" || attrs instanceof Node || Array.isArray(attrs))) { kids.unshift(attrs); attrs = null; }
    for (const [k, v] of Object.entries(attrs || {})) {
      if (v == null || v === false) continue;
      if (k.startsWith("on")) el.addEventListener(k.slice(2), v);
      else if (k === "style" && typeof v === "object") Object.assign(el.style, v);
      else if (k === "html") el.innerHTML = v; // 只用于本站自己编译的知识库正文
      else if (k in el && k !== "list") el[k] = v;
      else el.setAttribute(k, v === true ? "" : v);
    }
    append(el, kids);
    return el;
  }
  function append(el, kids) {
    for (const k of kids.flat(Infinity)) {
      if (k == null || k === false) continue;
      el.appendChild(k instanceof Node ? k : document.createTextNode(String(k)));
    }
    return el;
  }
  App.h = h;
  App.$ = (s, el = document) => el.querySelector(s);

  /* ---------------- 格式化 ---------------- */
  const isNum = (x) => typeof x === "number" && isFinite(x);
  const nf = (d) => new Intl.NumberFormat("zh-CN", { minimumFractionDigits: d, maximumFractionDigits: d });
  const F = {
    num(v, d = 2) { return isNum(v) ? nf(d).format(Math.abs(v) < 0.5 * 10 ** -d ? 0 : v) : "–"; },
    int(v) { return F.num(v, 0); },
    pct(v, d = 1) { return isNum(v) ? nf(d).format(v * 100) + "%" : "–"; },
    pp(v, d = 1) { return isNum(v) ? (v > 0 ? "+" : v < 0 ? "−" : "") + nf(d).format(Math.abs(v * 100)) + " 个百分点" : "–"; },
    days(v) { return isNum(v) ? nf(0).format(v) + " 天" : "–"; },
    x(v, d = 2) { return isNum(v) ? nf(d).format(v) + " 倍" : "–"; },
    years(v) { return isNum(v) ? nf(1).format(v) + " 年" : "无法收回"; },
    signedPct(v, d = 1) { return isNum(v) ? (v > 0 ? "+" : v < 0 ? "−" : "") + nf(d).format(Math.abs(v * 100)) + "%" : "–"; },
    // 金额按“亿/万”缩写，用于上市公司
    big(v, cur) {
      if (!isNum(v)) return "–";
      const unit = { CNY: "元", HKD: "港元", USD: "美元", 人民币: "元", 港币: "港元", 港元: "港元", 美元: "美元" }[cur] || (cur ? " " + cur : "");
      const a = Math.abs(v);
      if (a >= 1e8) return nf(a >= 1e10 ? 0 : 1).format(v / 1e8) + " 亿" + unit;
      if (a >= 1e4) return nf(0).format(v / 1e4) + " 万" + unit;
      return nf(0).format(v) + " " + unit;
    },
    date(iso) {
      if (!iso) return "";
      const d = new Date(iso);
      return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`;
    },
    // 当天显示“14:05”，更早显示“10/29”
    time(iso) {
      if (!iso) return "";
      const d = new Date(iso);
      const today = new Date().toDateString() === d.toDateString();
      return today ? `${String(d.getHours()).padStart(2, "0")}:${String(d.getMinutes()).padStart(2, "0")}` : `${d.getMonth() + 1}/${d.getDate()}`;
    },
    ago(iso) {
      const s = (Date.now() - Date.parse(iso)) / 1000;
      if (s < 3600) return `${Math.max(1, Math.round(s / 60))} 分钟前`;
      if (s < 86400) return `${Math.round(s / 3600)} 小时前`;
      if (s < 86400 * 7) return `${Math.round(s / 86400)} 天前`;
      return F.date(iso);
    },
  };
  // 解析用户输入的数字：允许千分位逗号、全角符号和百分号
  F.parse = (s) => {
    if (typeof s === "number") return s;
    const t = String(s || "").replace(/[,，\s]/g, "").replace(/[－—]/g, "-").replace(/．/g, ".");
    if (t === "" || t === "-") return null;
    const n = Number(t.replace(/%$/, ""));
    return isFinite(n) ? n : null;
  };
  App.F = F;
  App.isNum = isNum;

  /* ---------------- 本地存储（容错） ---------------- */
  App.store = {
    get(k, d) { try { const v = localStorage.getItem(k); return v === null ? d : JSON.parse(v); } catch { return d; } },
    set(k, v) { try { localStorage.setItem(k, JSON.stringify(v)); } catch { /* 隐私模式 */ } },
    del(k) { try { localStorage.removeItem(k); } catch { /* */ } },
  };

  /* ---------------- 数据加载 ---------------- */
  const cache = {};
  App.load = function (path) {
    if (!cache[path]) {
      const v = Math.floor(Date.now() / 6e5);
      cache[path] = fetch(`data/${path}?v=${v}`).then((r) => {
        if (!r.ok) throw new Error(`${path}: HTTP ${r.status}`);
        return r.json();
      });
      cache[path].catch(() => delete cache[path]);
    }
    return cache[path];
  };

  /* ---------------- 路由 ---------------- */
  // #/section/param?query
  App.route = function () {
    const raw = location.hash.replace(/^#/, "") || "/";
    const [path, qs] = raw.split("?");
    const parts = path.split("/").filter(Boolean);
    return { section: parts[0] || "home", param: parts[1] ? decodeURIComponent(parts[1]) : null, query: new URLSearchParams(qs || "") };
  };
  App.go = (hash, replace) => {
    if (replace) history.replaceState(null, "", hash);
    else location.hash = hash;
  };
  App.setQuery = function (obj) {
    const r = App.route();
    for (const [k, v] of Object.entries(obj)) {
      if (v == null || v === "" || v === "all") r.query.delete(k); else r.query.set(k, v);
    }
    const base = "#/" + [r.section === "home" ? "" : r.section, r.param].filter(Boolean).map(encodeURIComponent).join("/");
    const q = r.query.toString();
    history.replaceState(null, "", base + (q ? "?" + q : ""));
  };

  async function render() {
    const r = App.route();
    const main = App.$("#main");
    const navSection = r.section === "mine" ? "company" : r.section; // “分析我的公司”归在“公司财报”下
    document.querySelectorAll(".site-top .nav a").forEach((a) => {
      if (a.dataset.section === navSection) a.setAttribute("aria-current", "page"); else a.removeAttribute("aria-current");
    });
    const page = App.pages[r.section] || App.pages.notfound;
    main.innerHTML = "";
    main.setAttribute("aria-busy", "true");
    try {
      await page(main, r);
    } catch (err) {
      console.error(err);
      main.innerHTML = "";
      main.append(h("div.wrap.notice", h("h2", "内容加载失败"), h("p", "数据文件读取出错，请刷新重试。如果刚部署网站，可能是数据还没生成——等 GitHub Actions 运行完成后再试。"), h("p.muted", String(err.message || err))));
    }
    main.removeAttribute("aria-busy");
    if (!App._keepScroll) window.scrollTo(0, 0);
    App._keepScroll = false;
    const t = main.querySelector("h1");
    const siteName = (window.Site && window.Site.name) || "星图智策"; // 网站名称在 assets/site.js 里改
    document.title = (t && r.section !== "home" ? t.textContent + " · " : "") + siteName;
  }
  App.render = render;
  window.addEventListener("hashchange", render);

  /* ---------------- 主题 ---------------- */
  // 深浅色切换由全站顶栏（assets/site.js）负责；切换后重绘页面，让图表颜色跟着变
  window.addEventListener("site:theme", () => { App._keepScroll = true; App.render(); });

  /* ---------------- 提示框 ---------------- */
  let tipEl;
  function tip() {
    if (!tipEl) { tipEl = h("div.tip", { role: "status" }); document.body.appendChild(tipEl); }
    return tipEl;
  }
  App.showTip = function (x, y, title, rows) {
    const t = tip();
    t.innerHTML = "";
    t.append(h("div.tip-t", title));
    for (const r of rows) t.append(h("div.tip-r", h("i", { style: { background: r.color } }), h("b", r.value), h("span", r.label)));
    t.style.display = "block";
    const w = t.offsetWidth, hh = t.offsetHeight;
    t.style.left = Math.min(window.innerWidth - w - 8, Math.max(8, x + 14)) + "px";
    t.style.top = Math.max(8, y - hh - 12) + "px";
  };
  App.hideTip = () => { if (tipEl) tipEl.style.display = "none"; };
  window.addEventListener("scroll", App.hideTip, { passive: true });

  /* ---------------- 图表（SVG） ---------------- */
  const NS = "http://www.w3.org/2000/svg";
  const s = (tag, attrs = {}) => {
    const el = document.createElementNS(NS, tag);
    for (const [k, v] of Object.entries(attrs)) el.setAttribute(k, v);
    return el;
  };
  App.svg = s;
  App.color = (i) => `var(--series-${(i % 3) + 1})`;

  function niceTicks(lo, hi, n = 4) {
    if (lo === hi) { lo -= 1; hi += 1; }
    const span = hi - lo, step0 = span / n, mag = 10 ** Math.floor(Math.log10(step0));
    const step = [1, 2, 2.5, 5, 10].map((m) => m * mag).find((x) => x >= step0);
    const start = Math.floor(lo / step) * step, end = Math.ceil(hi / step) * step;
    const out = [];
    for (let v = start; v <= end + step / 2; v += step) out.push(Math.round(v / step) * step);
    return out;
  }

  function legend(series, kind) {
    if (series.length < 2) return null;
    return h("div.legend", series.map((sr, i) =>
      h("span", h("i." + kind, { style: { background: typeof sr.color === "string" ? sr.color : sr.legendColor || App.color(i) } }), sr.name)));
  }

  /* 折线图 / 柱状图：
     opts = { labels: [...], series: [{name, values, color}], kind: "line"|"bar", fmt: v=>string,
              height, zeroLine, markers: [{x, label}] , yMin } */
  App.chart = function (opts) {
    const { labels, series, kind = "line" } = opts;
    // 默认刻度格式：按数值大小自动决定小数位
    const fmt = opts.fmt || ((v) => F.num(v, Math.abs(v) >= 100 || v === 0 ? 0 : Math.abs(v) >= 1 ? 1 : 2));
    // 窄屏用较小的画布宽度，文字不会被缩得太小
    const narrow = window.innerWidth < 600;
    const height = Math.round((opts.height || 220) * (narrow ? 0.8 : 1));
    const wrap = h("figure.chart");
    if (opts.title) wrap.append(h("figcaption", opts.title));
    const lg = legend(series, kind === "bar" ? "box" : "line");
    if (lg) wrap.append(lg);
    const W = narrow ? 380 : 640, H = height, pad = { l: narrow ? 46 : 56, r: 12, t: 12, b: 26 };
    const all = series.flatMap((sr) => sr.values).filter(isNum);
    if (!all.length) { wrap.append(h("p.muted", "暂无数据")); return wrap; }
    let lo = Math.min(...all), hi = Math.max(...all);
    if (kind === "bar" || opts.zeroLine) { lo = Math.min(0, lo); hi = Math.max(0, hi); }
    if (isNum(opts.yMin)) lo = Math.min(lo, opts.yMin);
    const ticks = niceTicks(lo, hi);
    lo = ticks[0]; hi = ticks[ticks.length - 1];
    const svg = s("svg", { viewBox: `0 0 ${W} ${H}`, role: "img", "aria-label": opts.title || "图表" });
    const x0 = pad.l, x1 = W - pad.r, y0 = H - pad.b, y1 = pad.t;
    const Y = (v) => y0 - ((v - lo) / (hi - lo)) * (y0 - y1);
    const n = labels.length;
    const band = (x1 - x0) / n;
    const X = (i) => (kind === "bar" ? x0 + band * (i + 0.5) : x0 + (n === 1 ? (x1 - x0) / 2 : ((x1 - x0) * i) / (n - 1)));
    // 网格与 y 轴
    for (const t of ticks) {
      svg.append(s("line", { x1: x0, x2: x1, y1: Y(t), y2: Y(t), class: t === 0 ? "axis0" : "grid" }));
      const lab = s("text", { x: x0 - 8, y: Y(t) + 4, "text-anchor": "end", class: "tick" });
      lab.textContent = fmt(t);
      svg.append(lab);
    }
    // x 轴标签（太密时隔几个显示）
    const every = Math.ceil(n / (narrow ? 6 : 12));
    labels.forEach((l, i) => {
      if (i % every && i !== n - 1) return;
      const t = s("text", { x: X(i), y: H - 8, "text-anchor": "middle", class: "tick" });
      t.textContent = l;
      svg.append(t);
    });
    if (kind === "bar") {
      const k = series.length, bw = Math.min(24, (band * 0.7) / k);
      series.forEach((sr, si) => sr.values.forEach((v, i) => {
        if (!isNum(v)) return;
        const x = X(i) - (bw * k) / 2 + si * bw + 1, y = Math.min(Y(v), Y(0)), hgt = Math.max(1, Math.abs(Y(v) - Y(0)));
        const r = Math.min(4, hgt / 2, (bw - 2) / 2);
        const up = v >= 0;
        // 数据端 4px 圆角，基线端直角
        const d = up
          ? `M${x},${y + hgt}V${y + r}Q${x},${y} ${x + r},${y}H${x + bw - 2 - r}Q${x + bw - 2},${y} ${x + bw - 2},${y + r}V${y + hgt}Z`
          : `M${x},${y}V${y + hgt - r}Q${x},${y + hgt} ${x + r},${y + hgt}H${x + bw - 2 - r}Q${x + bw - 2},${y + hgt} ${x + bw - 2},${y + hgt - r}V${y}Z`;
        const color = typeof sr.color === "function" ? sr.color(v) : sr.color || App.color(si);
        svg.append(s("path", { d, fill: color, class: "bar" }));
      }));
    } else {
      series.forEach((sr, si) => {
        const pts = sr.values.map((v, i) => (isNum(v) ? [X(i), Y(v)] : null));
        let d = "", pen = false;
        pts.forEach((p) => { if (!p) { pen = false; return; } d += (pen ? "L" : "M") + p[0].toFixed(1) + "," + p[1].toFixed(1); pen = true; });
        svg.append(s("path", { d, class: "line", stroke: sr.color || App.color(si) }));
        const last = pts.map((p, i) => [p, i]).filter(([p]) => p).pop();
        if (last) svg.append(s("circle", { cx: last[0][0], cy: last[0][1], r: 4, fill: sr.color || App.color(si), class: "dot" }));
      });
    }
    for (const m of opts.markers || []) {
      const mx = isNum(m.value) ? x0 + ((m.value - opts.markerDomain[0]) / (opts.markerDomain[1] - opts.markerDomain[0])) * (x1 - x0) : X(m.x);
      if (!(mx >= x0 && mx <= x1)) continue;
      svg.append(s("line", { x1: mx, x2: mx, y1: y1, y2: y0, class: "marker" }));
      const t = s("text", { x: mx + 4, y: y1 + 10, class: "marker-t" });
      t.textContent = m.label;
      svg.append(t);
    }
    for (const m of opts.markersY || []) {  // 水平参考线，例如“安全余额”
      if (!isNum(m.value) || m.value < lo || m.value > hi) continue;
      svg.append(s("line", { x1: x0, x2: x1, y1: Y(m.value), y2: Y(m.value), class: "marker" }));
      const t = s("text", { x: x1 - 4, y: Y(m.value) - 5, "text-anchor": "end", class: "marker-t" });
      t.textContent = m.label;
      svg.append(t);
    }
    // 交互层：十字线（折线）/ 整列高亮（柱状）
    const cross = s("line", { y1: y1, y2: y0, class: "cross", visibility: "hidden" });
    svg.append(cross);
    const hit = s("rect", { x: x0, y: y1, width: x1 - x0, height: y0 - y1, fill: "transparent", tabindex: 0 });
    svg.append(hit);
    const showAt = (i, cx, cy) => {
      const xi = X(i);
      cross.setAttribute("x1", xi); cross.setAttribute("x2", xi); cross.setAttribute("visibility", "visible");
      App.showTip(cx, cy, labels[i], series.map((sr, si) => ({
        color: typeof sr.color === "function" ? sr.color(sr.values[i]) : sr.color || App.color(si),
        value: isNum(sr.values[i]) ? fmt(sr.values[i]) : "–", label: sr.name || "" })));
    };
    hit.addEventListener("pointermove", (e) => {
      const rect = svg.getBoundingClientRect();
      const px = ((e.clientX - rect.left) / rect.width) * W;
      const i = kind === "bar" ? Math.floor((px - x0) / band) : Math.round(((px - x0) / (x1 - x0)) * (n - 1));
      if (i >= 0 && i < n) showAt(i, e.clientX, e.clientY);
    });
    hit.addEventListener("pointerleave", () => { cross.setAttribute("visibility", "hidden"); App.hideTip(); });
    let fi = n - 1;
    hit.addEventListener("focus", () => { const r = svg.getBoundingClientRect(); showAt(fi, r.left + r.width / 2, r.top + 20); });
    hit.addEventListener("blur", () => { cross.setAttribute("visibility", "hidden"); App.hideTip(); });
    hit.addEventListener("keydown", (e) => {
      if (e.key === "ArrowLeft" || e.key === "ArrowRight") {
        fi = Math.max(0, Math.min(n - 1, fi + (e.key === "ArrowLeft" ? -1 : 1)));
        const r = svg.getBoundingClientRect();
        showAt(fi, r.left + (X(fi) / W) * r.width, r.top + 20);
        e.preventDefault();
      }
    });
    wrap.append(h("div.chart-box", svg));
    return wrap;
  };

  /* ---------------- 账簿式结果块（本站的标志元素） ---------------- */
  // rows: [{label, value, note, total, sub}]
  App.ledger = function (rows, title) {
    const box = h("div.ledger");
    if (title) box.append(h("h3", title));
    const dl = h("dl");
    for (const r of rows) {
      if (!r) continue;
      dl.append(h("div.lrow" + (r.total ? ".total" : "") + (r.sub ? ".sub" : "") + (r.warn ? ".warn" : ""),
        h("dt", r.label), h("dd", r.value)));
      if (r.note) dl.append(h("p.lnote", r.note));
    }
    box.append(dl);
    return box;
  };

  /* ---------------- 搜索索引（首页与全站搜索） ---------------- */
  App.searchAll = async function (q) {
    q = q.trim().toLowerCase();
    if (!q) return [];
    const out = [];
    for (const t of Object.values(App.tools)) {
      if ((t.name + t.en + t.desc + (t.keywords || "")).toLowerCase().includes(q)) out.push({ kind: "工具", title: t.name, desc: t.desc, href: `#/tools/${t.id}` });
    }
    try {
      const kb = await App.load("kb.json");
      for (const a of kb.articles) {
        const hay = (a.title + " " + a.en + " " + a.summary).toLowerCase();
        const body = a.text.toLowerCase();
        if (hay.includes(q)) out.push({ kind: "方法", title: a.title, desc: a.summary, href: `#/kb/${a.id}`, score: 2 });
        else if (body.includes(q)) out.push({ kind: "方法", title: a.title, desc: a.summary, href: `#/kb/${a.id}`, score: 1 });
      }
    } catch { /* 知识库未生成 */ }
    try {
      const idx = await App.load("companies/index.json");
      for (const c of idx.companies) {
        if ((c.name + c.code + c.industry_name).toLowerCase().includes(q)) out.push({ kind: "公司", title: `${c.name} ${c.code}`, desc: `${c.industry_name} · ${c.latest} 年报`, href: `#/company/${c.id}` });
      }
    } catch { /* 财报未生成 */ }
    // 工具和标题命中排在前面，正文命中排在后面
    out.sort((a, b) => (b.score ?? 3) - (a.score ?? 3));
    return out.slice(0, 12);
  };
})();
