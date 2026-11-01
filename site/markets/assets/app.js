/* 行情快讯栏目（原财经雷达）— 前端逻辑（无框架、无构建步骤） */
(function () {
  "use strict";

  const PAGE = 60;
  const REFRESH_MS = 10 * 60 * 1000;           // 页面开着时每 10 分钟重新拉取数据
  const MARKETS = ["cn", "hk", "us", "global", "crypto"];
  const TYPES = ["all", "flash", "news", "filing", "policy"];
  const DEFAULTS = { m: "all", type: "all", q: "", imp: "0" };

  const $ = (s, el = document) => el.querySelector(s);
  const root = document.documentElement;
  const store = {
    get(k, d) { try { const v = localStorage.getItem(k); return v === null ? d : JSON.parse(v); } catch { return d; } },
    set(k, v) { try { localStorage.setItem(k, JSON.stringify(v)); } catch { /* 隐私模式下忽略 */ } },
  };

  const lang = "zh"; // 合并后全站只用中文；i18n.js 里的英文文案保留但不再使用
  let T = window.I18N[lang];
  let meta = null, items = [], quotes = null, macro = [];
  let marketName = {};
  let state = readHash();
  let shown = PAGE;
  let filtered = [];
  let region = store.get("fr.region", "cn");
  let boardTab = store.get("fr.boardTab", null);

  /* ---------------- 状态 <-> 网址 ---------------- */
  function readHash() {
    const p = new URLSearchParams(location.hash.slice(1));
    const s = { ...DEFAULTS };
    for (const k of Object.keys(DEFAULTS)) if (p.has(k)) s[k] = p.get(k);
    return s;
  }
  function writeHash() {
    const p = new URLSearchParams();
    for (const [k, v] of Object.entries(state)) if (v !== DEFAULTS[k]) p.set(k, v);
    const h = p.toString();
    history.replaceState(null, "", h ? "#" + h : location.pathname + location.search);
  }
  function setState(patch) {
    Object.assign(state, patch);
    shown = PAGE;
    writeHash();
    renderFeed();
  }

  /* ---------------- 工具 ---------------- */
  const pad = (n) => String(n).padStart(2, "0");
  const ageH = (iso) => (Date.now() - Date.parse(iso)) / 36e5;
  const srcName = (id) => (meta && meta.source_names[id] ? meta.source_names[id][lang] : id);
  const mName = (id) => (marketName[id] ? marketName[id][lang] : id);
  const nm = (o) => (o ? o[lang] || o.zh || "" : "");
  const dirClass = (x) => (x == null || Math.abs(x) < 1e-9 ? "flat" : x > 0 ? "up" : "down");
  function fmtNum(v, dec) {
    if (v == null) return "–";
    v = Number(Number(v).toFixed(dec)) || 0; // 避免出现 -0.0
    return v.toLocaleString(lang === "zh" ? "zh-CN" : "en-US", { minimumFractionDigits: dec, maximumFractionDigits: dec });
  }
  function signed(v, dec, suffix = "") {
    if (v == null) return "";
    const s = fmtNum(Math.abs(v), dec);
    return (v > 0 ? "+" : v < 0 ? "−" : "") + s + suffix;
  }
  function dayKey(d) { return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}`; }
  function dayLabel(d) {
    const today = new Date();
    const y = new Date(today); y.setDate(today.getDate() - 1);
    const base = T.date_fmt(d.getMonth() + 1, d.getDate(), T.weekdays[d.getDay()]);
    if (dayKey(d) === dayKey(today)) return `${T.today} ${base}`;
    if (dayKey(d) === dayKey(y)) return `${T.yesterday} ${base}`;
    return base;
  }
  function haystack(it) {
    if (!it._hay) it._hay = [it.title, it.title_en, it.summary, (it.tags || []).join(" "), (it.sources || []).join(" ")].join(" ").toLowerCase();
    return it._hay;
  }

  /* ---------------- 迷你图 ---------------- */
  const NS = "http://www.w3.org/2000/svg";
  function sparkline(values, cls) {
    const svg = document.createElementNS(NS, "svg");
    svg.setAttribute("viewBox", "0 0 64 24");
    svg.setAttribute("aria-hidden", "true");
    const v = (values || []).filter((x) => x != null);
    if (v.length < 2) return svg;
    const lo = Math.min(...v), hi = Math.max(...v), span = hi - lo || 1;
    const pts = v.map((x, i) => `${(i / (v.length - 1) * 64).toFixed(1)},${(22 - (x - lo) / span * 20).toFixed(1)}`);
    const pl = document.createElementNS(NS, "polyline");
    pl.setAttribute("points", pts.join(" "));
    pl.setAttribute("stroke", `var(--${cls === "up" ? "up" : cls === "down" ? "down" : "flat"})`);
    svg.appendChild(pl);
    return svg;
  }
  function bars(history) {
    const svg = document.createElementNS(NS, "svg");
    svg.setAttribute("viewBox", "0 0 96 40");
    svg.setAttribute("aria-hidden", "true");
    const v = (history || []).map((h) => h.v).slice(-16);
    if (!v.length) return svg;
    let lo = Math.min(...v), hi = Math.max(...v);
    // 水平类指标（PMI、利率）离 0 很远：以区间最小值为底，突出变化；否则以 0 为基线
    const levelLike = lo > 0 && lo > hi * 0.5;
    if (levelLike) lo -= (hi - lo || 1) * 0.5; else { lo = Math.min(0, lo); hi = Math.max(0, hi); }
    const span = hi - lo || 1;
    const y0 = levelLike ? 38 : 38 - (0 - lo) / span * 36;
    const w = 96 / v.length;
    v.forEach((x, i) => {
      const r = document.createElementNS(NS, "rect");
      const y = 38 - (x - lo) / span * 36;
      r.setAttribute("x", (i * w + 1).toFixed(1));
      r.setAttribute("width", Math.max(1, w - 2).toFixed(1));
      r.setAttribute("y", Math.min(y, y0).toFixed(1));
      r.setAttribute("height", Math.max(1, Math.abs(y0 - y)).toFixed(1));
      if (i === v.length - 1) r.setAttribute("class", "last");
      svg.appendChild(r);
    });
    if (!levelLike && lo < 0) {
      const l = document.createElementNS(NS, "line");
      l.setAttribute("x1", 0); l.setAttribute("x2", 96); l.setAttribute("y1", y0); l.setAttribute("y2", y0);
      svg.appendChild(l);
    }
    return svg;
  }

  /* ---------------- 静态文案与开关 ---------------- */
  function applyLang() {
    T = window.I18N[lang];
    root.lang = "zh-CN";
    document.querySelectorAll("[data-i18n]").forEach((el) => { el.textContent = T[el.dataset.i18n]; });
    $("#q").placeholder = T.search;
    $("#board-note").textContent = T.board_note;
    $("#macro-note").textContent = T.macro_note;
    $("#foot-text").textContent = T.foot;
    syncColorBtn();
    if (meta) {
      $("#tagline").textContent = nm(meta.tagline);
      document.title = "行情快讯 · " + ((window.Site && window.Site.name) || "星图智策");
      $("#updated").textContent = T.updated(new Date(meta.updated).toLocaleString(lang === "zh" ? "zh-CN" : "en-US",
        { month: "short", day: "numeric", hour: "2-digit", minute: "2-digit" }));
    } else {
      $("#updated").textContent = T.not_yet;
    }
  }
  function updownMode() {
    return store.get("fr.updown", "red");
  }
  function syncColorBtn() {
    const mode = updownMode();
    root.dataset.updown = mode;
    const b = $("#color-btn");
    b.lastChild && b.lastChild.nodeType === 3 ? (b.lastChild.textContent = mode === "red" ? T.color_red : T.color_green)
      : b.append(mode === "red" ? T.color_red : T.color_green);
    b.title = T.color_hint;
  }

  /* ---------------- 行情板 ---------------- */
  function renderBoard() {
    const board = $("#board"), tabs = $("#board-tabs");
    board.innerHTML = ""; tabs.innerHTML = "";
    const groups = (quotes && quotes.groups || []).filter((g) => g.rows.length);
    if (!groups.length) { $(".board-wrap").hidden = true; return; }
    $(".board-wrap").hidden = false;
    if (!groups.some((g) => g.id === boardTab)) boardTab = groups[0].id;
    for (const g of groups) {
      const tab = document.createElement("button");
      tab.type = "button"; tab.setAttribute("role", "tab");
      tab.textContent = nm(g.name);
      tab.setAttribute("aria-selected", String(g.id === boardTab));
      tab.onclick = () => { boardTab = g.id; store.set("fr.boardTab", g.id); renderBoard(); };
      tabs.appendChild(tab);

      const sec = document.createElement("section");
      sec.className = "group" + (g.id === boardTab ? " on" : "");
      const h = document.createElement("h3");
      h.textContent = nm(g.name);
      sec.appendChild(h);
      for (const r of g.rows) {
        const isBp = r.change_unit === "bp";
        const move = isBp ? r.chg : r.pct;
        const cls = dirClass(move);
        const row = document.createElement("div");
        row.className = "q" + (r.stale ? " stale" : "");
        row.title = (r.stale ? T.stale + "\n" : "") + `${T.as_of} ${r.as_of || "–"}`;
        const n = document.createElement("span");
        n.className = "n"; n.textContent = nm(r.name);
        const b = document.createElement("b");
        b.textContent = (r.unit === "$" ? "$" : "") + fmtNum(r.last, r.decimals ?? 2) + (r.unit === "%" ? "%" : "");
        const c = document.createElement("span");
        c.className = "c " + cls;
        c.textContent = isBp ? signed(r.chg, 1, T.bp) : signed(r.pct, 2, "%");
        row.append(n, b, c, sparkline(r.spark, cls));
        sec.appendChild(row);
      }
      board.appendChild(sec);
    }
  }

  /* ---------------- 宏观面板 ---------------- */
  function renderMacro() {
    const seg = $("#region-seg");
    seg.innerHTML = "";
    seg.setAttribute("aria-label", T.macro);
    for (const r of ["cn", "us"]) {
      const b = document.createElement("button");
      b.type = "button"; b.setAttribute("role", "radio");
      b.textContent = T["region_" + r];
      b.setAttribute("aria-checked", String(region === r));
      b.onclick = () => { region = r; store.set("fr.region", r); renderMacro(); };
      seg.appendChild(b);
    }
    const list = $("#macro-list");
    list.innerHTML = "";
    const rows = macro.filter((e) => e.region === region);
    $(".macro").hidden = !macro.length;
    for (const e of rows) {
      const li = document.createElement("li");
      if (e.stale) li.className = "stale";
      const unit = e.unit === "%" ? "%" : "";
      const n = document.createElement("span");
      n.className = "mn";
      const a = document.createElement("a");
      a.href = e.url || "#"; a.target = "_blank"; a.rel = "noopener";
      a.textContent = nm(e.name);
      n.appendChild(a);
      const v = document.createElement("span");
      v.className = "mv";
      const dec = e.unit === "k" ? 0 : (e.id || "").includes("lpr") || (e.id || "").includes("ffr") ? 2 : 1;
      v.textContent = fmtNum(e.value, dec);
      if (unit) { const s = document.createElement("small"); s.textContent = unit; v.appendChild(s); }
      const p = document.createElement("span");
      p.className = "mp";
      const d = e.prev == null ? null : e.value - e.prev;
      p.textContent = `${e.period}｜${T.prev} ${e.prev == null ? "–" : fmtNum(e.prev, dec) + unit}`;
      if (e.stale) p.title = T.stale;
      li.append(n, v, p, bars(e.history));
      if (d != null) li.querySelector(".mv").title = signed(d, dec);
      list.appendChild(li);
    }
  }

  /* ---------------- 筛选控件 ---------------- */
  function renderControls() {
    const chips = $("#market-chips");
    chips.innerHTML = "";
    chips.setAttribute("aria-label", T.all_markets);
    const counts = {};
    for (const it of items) if (ageH(it.date) <= 24) for (const m of it.markets) counts[m] = (counts[m] || 0) + 1;
    const mk = (id, label, n) => {
      const b = document.createElement("button");
      b.type = "button"; b.setAttribute("role", "radio");
      b.className = "chip" + (id === "all" ? " all" : "");
      if (id !== "all") b.style.setProperty("--c", `var(--m-${id})`);
      b.setAttribute("aria-checked", String(state.m === id));
      b.append(label);
      if (n != null) { const s = document.createElement("small"); s.textContent = n; s.title = T.h24; b.appendChild(s); }
      b.onclick = () => setState({ m: id });
      chips.appendChild(b);
    };
    mk("all", T.all_markets, null);
    for (const m of MARKETS) if (marketName[m]) mk(m, mName(m), counts[m] || 0);

    const seg = $("#type-seg");
    seg.innerHTML = "";
    for (const t of TYPES) {
      const b = document.createElement("button");
      b.type = "button"; b.setAttribute("role", "radio");
      b.textContent = T["type_" + t];
      b.setAttribute("aria-checked", String(state.type === t));
      b.onclick = () => setState({ type: t });
      seg.appendChild(b);
    }
    $("#imp-only").checked = state.imp === "1";
  }

  /* ---------------- 时间线 ---------------- */
  function applyFilters() {
    const terms = state.q.toLowerCase().split(/\s+/).filter(Boolean);
    return items.filter((it) =>
      (state.m === "all" || it.markets.includes(state.m)) &&
      (state.type === "all" || (state.type === "policy" ? (it.type === "policy" || it.macro) : it.type === state.type)) &&
      (state.imp !== "1" || it.important) &&
      terms.every((w) => haystack(it).includes(w)));
  }

  function rowFor(it) {
    const el = $("#row-tpl").content.firstElementChild.cloneNode(true);
    el.classList.add(it.type);
    if (it.important) el.classList.add("imp");
    const d = new Date(it.date);
    const t = $(".t", el);
    t.dateTime = it.date;
    t.textContent = `${pad(d.getHours())}:${pad(d.getMinutes())}`;

    const a = $(".title a", el);
    a.href = it.url || "#";
    a.textContent = lang === "en" && it.title_en ? it.title_en : it.title;
    if (it.important) {
      const b = document.createElement("span");
      b.className = "badge"; b.textContent = T.important;
      $(".title", el).prepend(b);
    }
    const sum = $(".summary", el);
    sum.textContent = it.summary || "";
    sum.onclick = () => sum.classList.add("open");

    $(".kind", el).textContent = it.type === "flash" ? "" : T["type_" + it.type];
    const srcs = $(".srcs", el);
    it.sources.forEach((s, i) => {
      if (i) srcs.append(" / ");
      const alt = it.alt_urls && it.alt_urls[s];
      if (alt && i > 0) {
        const l = document.createElement("a");
        l.href = alt; l.target = "_blank"; l.rel = "noopener"; l.textContent = srcName(s);
        srcs.appendChild(l);
      } else srcs.append(srcName(s));
    });
    const mk = $(".mk", el);
    for (const m of it.markets) {
      if (!marketName[m]) continue;
      const b = document.createElement("button");
      b.type = "button";
      b.style.setProperty("--c", `var(--m-${m})`);
      b.textContent = mName(m);
      b.onclick = () => { setState({ m }); $("#feed").scrollIntoView({ behavior: "smooth" }); };
      mk.appendChild(b);
    }
    return el;
  }

  let lastDay = null;
  function appendRows(list, from, to) {
    const tl = $("#timeline");
    const frag = document.createDocumentFragment();
    for (const it of list.slice(from, to)) {
      const d = new Date(it.date);
      const k = dayKey(d);
      if (k !== lastDay) {
        const h = document.createElement("h2");
        h.className = "day";
        h.textContent = dayLabel(d);
        frag.appendChild(h);
        lastDay = k;
      }
      frag.appendChild(rowFor(it));
    }
    tl.appendChild(frag);
  }

  function renderFeed() {
    renderControls();
    filtered = applyFilters();
    $("#timeline").innerHTML = "";
    lastDay = null;
    appendRows(filtered, 0, shown);
    updateMore();
    $("#result-count").textContent = T.count(filtered.length);
    const dirty = ["m", "type", "q", "imp"].some((k) => state[k] !== DEFAULTS[k]);
    const reset = $("#reset-btn");
    reset.hidden = !dirty; reset.textContent = T.reset;
    const empty = $("#empty");
    empty.hidden = filtered.length > 0;
    if (!filtered.length) empty.textContent = items.length ? T.empty_filter : T.empty_data;
    const ch = $(".controls");
    if (ch) root.style.setProperty("--controls-h", getComputedStyle(ch).position === "sticky" ? ch.offsetHeight + "px" : "0px");
  }
  function updateMore() {
    const rest = filtered.length - shown;
    const more = $("#more-btn");
    more.hidden = rest <= 0;
    if (rest > 0) more.textContent = T.more(Math.min(rest, PAGE));
  }

  /* ---------------- 数据源状态 ---------------- */
  function renderStatus() {
    const st = (meta && meta.sources_status) || {};
    const ids = Object.keys(st);
    const ok = ids.filter((k) => st[k].ok).length;
    $("#status-summary").textContent = T.status_summary(ok, ids.length);
    $(".status").hidden = !ids.length;
    const ul = $("#status-list");
    ul.innerHTML = "";
    for (const id of ids.sort((a, b) => (st[a].ok - st[b].ok) || a.localeCompare(b))) {
      const s = st[id];
      const li = document.createElement("li");
      li.className = s.ok ? "ok" : "bad";
      const sp = document.createElement("span");
      sp.textContent = s.ok ? T.status_ok(s.count) : T.status_fail;
      const box = document.createElement("div");
      box.append(srcName(id) + " ", sp);
      if (!s.ok && s.error) {
        li.title = s.error; // 鼠标悬停显示原始报错
        const why = document.createElement("small");
        why.className = "err";
        why.textContent = window.Site ? window.Site.explainError(s.error) : s.error;
        box.appendChild(why);
      }
      li.replaceChildren(box);
      ul.appendChild(li);
    }
  }

  function renderAll() {
    applyLang();
    renderBoard();
    renderMacro();
    renderFeed();
    renderStatus();
  }

  /* ---------------- 事件 ---------------- */
  function bind() {
    let timer;
    const q = $("#q");
    q.value = state.q;
    q.addEventListener("input", () => { clearTimeout(timer); timer = setTimeout(() => setState({ q: q.value.trim() }), 180); });
    $("#imp-only").onchange = (e) => setState({ imp: e.target.checked ? "1" : "0" });
    $("#reset-btn").onclick = () => { q.value = ""; setState({ ...DEFAULTS }); };
    $("#more-btn").onclick = () => { const from = shown; shown += PAGE; appendRows(filtered, from, shown); updateMore(); };
    $("#color-btn").onclick = () => { store.set("fr.updown", updownMode() === "red" ? "green" : "red"); syncColorBtn(); };
    // 深浅色切换由全站顶栏（../assets/site.js）负责
    window.addEventListener("hashchange", () => { state = readHash(); q.value = state.q; shown = PAGE; renderFeed(); });
    document.addEventListener("keydown", (e) => {
      if (e.key === "/" && document.activeElement !== q) { e.preventDefault(); q.focus(); }
    });
  }

  /* ---------------- 数据加载 ---------------- */
  async function getJSON(name) {
    const r = await fetch(`data/${name}?v=${Math.floor(Date.now() / 3e5)}`); // 5 分钟内复用缓存
    return r.ok ? r.json() : null;
  }
  async function load(isRefresh) {
    try {
      const [m, d, q, mc] = await Promise.all([getJSON("meta.json"), getJSON("items.json"), getJSON("quotes.json"), getJSON("macro.json")]);
      if (isRefresh && m && meta && m.updated === meta.updated) return;
      meta = m;
      items = (d && d.items) || [];
      quotes = q;
      macro = (mc && mc.indicators) || [];
      marketName = {};
      if (meta) for (const x of meta.markets) marketName[x.id] = x.name;
    } catch (err) {
      console.error(err);
      if (!isRefresh) { $("#empty").hidden = false; $("#empty").textContent = T.load_error; }
      return;
    }
    const keep = isRefresh ? shown : PAGE;
    renderAll();
    if (isRefresh && keep > PAGE) { shown = keep; $("#timeline").innerHTML = ""; lastDay = null; appendRows(filtered, 0, shown); updateMore(); }
  }

  bind();
  applyLang();
  load(false);
  setInterval(() => { if (!document.hidden) load(true); }, REFRESH_MS);
})();
