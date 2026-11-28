/* AI 前沿栏目（原 AI 前沿雷达）— 前端逻辑（无框架、无构建步骤） */
(function () {
  "use strict";

  const PAGE = 40;
  const TOPIC_ORDER = ["brain", "models", "apps", "medicine", "math", "physics", "finance"];
  const TYPES = ["all", "paper", "repo", "model", "dataset"];
  const RANGES = ["1", "3", "7", "30", "all"];
  const SOURCES = ["all", "arxiv", "huggingface", "github", "biorxiv", "medrxiv"];
  const DEFAULTS = { topic: "all", type: "all", source: "all", range: "all", sort: "new", q: "", saved: "0" };

  const $ = (s, el = document) => el.querySelector(s);
  const store = {
    get(k, d) { try { const v = localStorage.getItem(k); return v === null ? d : JSON.parse(v); } catch { return d; } },
    set(k, v) { try { localStorage.setItem(k, JSON.stringify(v)); } catch { /* 隐私模式等情况下忽略 */ } },
  };

  const lang = "zh"; // 合并后全站只用中文；i18n.js 里的英文文案保留但不再使用
  let T = window.I18N[lang];
  let meta = null;
  let items = [];
  let topicsById = {};
  let saved = store.get("radar.saved", {});      // id -> 条目快照（原数据过期后收藏仍在）
  let state = readHash();
  let shown = PAGE;
  let filtered = [];

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
    render();
  }

  /* ---------------- 工具 ---------------- */
  const tName = (id) => (topicsById[id] ? topicsById[id].name[lang] || topicsById[id].name.zh : id);
  const colorVar = (id) => `var(--t-${id}, var(--muted))`;
  const now = () => Date.now();
  const ageDays = (iso) => (now() - Date.parse(iso)) / 864e5;
  function fmtDate(iso) {
    const d = new Date(iso);
    return `${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`;
  }
  function relDay(iso) {
    const a = Math.floor(ageDays(iso));
    if (a <= 0) return T.today;
    if (a === 1) return T.yesterday;
    return T.days_ago(a);
  }
  function fmtNum(n) {
    if (n >= 1e6) return (n / 1e6).toFixed(n >= 1e7 ? 0 : 1) + "M";
    if (n >= 1e3) return (n / 1e3).toFixed(n >= 1e4 ? 0 : 1) + "k";
    return String(Math.round(n));
  }
  function popularity(it) {
    const m = it.metrics || {};
    const ln = (x) => Math.log1p(x || 0);
    const pop = ln(m.stars) + 1.6 * ln(m.upvotes) + ln(m.likes) + 0.15 * ln(m.downloads)
      + (it.sources.length - 1);
    return pop / Math.pow(1 + Math.max(0, ageDays(it.date)) / 10, 0.6);
  }
  function haystack(it) {
    if (!it._hay) {
      it._hay = [it.title, it.summary, it.tldr, (it.authors || []).join(" "), (it.tags || []).join(" "), it.id]
        .join(" ").toLowerCase();
    }
    return it._hay;
  }

  /* ---------------- 静态文案 ---------------- */
  function applyLang() {
    T = window.I18N[lang];
    document.documentElement.lang = "zh-CN";
    document.querySelectorAll("[data-i18n]").forEach((el) => { el.textContent = T[el.dataset.i18n]; });
    $("#q").placeholder = T.search;
    if (meta) {
      $("#tagline").textContent = meta.tagline[lang];
      document.title = "AI 前沿 · " + ((window.Site && window.Site.name) || "星图智策");
      const d = new Date(meta.updated);
      $("#updated").textContent = T.updated(d.toLocaleString(lang === "zh" ? "zh-CN" : "en-US",
        { month: "short", day: "numeric", hour: "2-digit", minute: "2-digit" }));
      $("#foot-text").textContent = T.foot(meta.retention_days || 60);
    } else {
      $("#updated").textContent = T.not_yet;
    }
    buildControls();
  }

  function buildControls() {
    const seg = (el, values, key, label) => {
      el.innerHTML = "";
      el.setAttribute("aria-label", label);
      for (const v of values) {
        const b = document.createElement("button");
        b.type = "button";
        b.setAttribute("role", "radio");
        b.textContent = key === "type" ? T["type_" + v] : T["sort_" + v];
        b.setAttribute("aria-checked", String(state[key] === v));
        b.onclick = () => setState({ [key]: v });
        el.appendChild(b);
      }
    };
    seg($("#type-seg"), TYPES, "type", T.type_all);
    seg($("#sort-seg"), ["new", "hot"], "sort", T.sort_new);

    const srcSel = $("#source-sel");
    srcSel.innerHTML = SOURCES.map((s) =>
      `<option value="${s}">${s === "all" ? T.source_all : T.src_names[s]}</option>`).join("");
    srcSel.value = state.source;
    const rSel = $("#range-sel");
    rSel.innerHTML = RANGES.map((r) => `<option value="${r}">${T["range_" + r]}</option>`).join("");
    rSel.value = state.range;

    const sb = $("#saved-btn");
    const n = Object.keys(saved).length;
    sb.textContent = state.saved === "1" ? T.saved_on : `${T.saved}${n ? " " + n : ""}`;
    sb.setAttribute("aria-pressed", String(state.saved === "1"));
  }

  /* ---------------- 光谱色带 ---------------- */
  function renderSpectrum() {
    const el = $("#spectrum");
    const week = items.filter((it) => ageDays(it.date) <= 7);
    const counts = Object.fromEntries(TOPIC_ORDER.map((t) => [t, 0]));
    for (const it of week) for (const t of it.topics) if (t in counts) counts[t]++;
    const totalTopics = Object.values(counts).reduce((a, b) => a + b, 0) || 1;
    el.innerHTML = "";
    el.classList.toggle("has-active", state.topic !== "all");

    const mk = (id, name, num, grow) => {
      const b = document.createElement("button");
      b.type = "button";
      b.className = "band" + (id === "all" ? " is-all" : "") + (state.topic === id ? " active" : "");
      b.setAttribute("role", "tab");
      b.setAttribute("aria-selected", String(state.topic === id));
      if (id !== "all") {
        b.style.setProperty("--c", colorVar(id));
        b.style.flexGrow = String(Math.max(0.6, (num / totalTopics) * 7));
        if (topicsById[id]) b.title = topicsById[id].description?.[lang] || "";
      }
      b.innerHTML = `<span class="b-name"></span><span class="b-num">${fmtNum(num)}<small>${id === "all" ? "" : "/7d"}</small></span>`;
      b.querySelector(".b-name").textContent = name;
      b.onclick = () => setState({ topic: state.topic === id ? "all" : id });
      el.appendChild(b);
    };
    mk("all", T.spectrum_all, items.length);
    for (const t of TOPIC_ORDER) if (topicsById[t]) mk(t, tName(t), counts[t]);

    const note = $("#spectrum-note");
    if (state.topic !== "all" && topicsById[state.topic]) {
      note.textContent = topicsById[state.topic].description?.[lang] || "";
      note.className = "topic-desc";
    } else {
      note.textContent = T.spectrum_note(week.length);
      note.className = "spectrum-note";
    }
  }

  /* ---------------- 列表 ---------------- */
  function applyFilters() {
    const pool = state.saved === "1"
      ? Object.values(saved).map((s) => items.find((i) => i.id === s.id) || s)
      : items;
    const terms = state.q.toLowerCase().split(/\s+/).filter(Boolean);
    const maxAge = state.range === "all" ? Infinity : Number(state.range);
    let out = pool.filter((it) =>
      (state.topic === "all" || it.topics.includes(state.topic)) &&
      (state.type === "all" || it.type === state.type) &&
      (state.source === "all" || it.sources.includes(state.source)) &&
      (state.saved === "1" || ageDays(it.date) <= maxAge) &&
      terms.every((w) => haystack(it).includes(w)));
    if (state.sort === "hot") {
      out = out.map((it) => [popularity(it), it]).sort((a, b) => b[0] - a[0]).map((x) => x[1]);
    } else {
      out.sort((a, b) => (b.date || "").localeCompare(a.date || ""));
    }
    return out;
  }

  function rowFor(it) {
    const tpl = $("#row-tpl").content.firstElementChild.cloneNode(true);
    tpl.classList.add("t-" + it.type);

    const ticks = $(".ticks", tpl);
    for (const t of it.topics) {
      const i = document.createElement("i");
      i.style.setProperty("--c", colorVar(t));
      ticks.appendChild(i);
    }

    const time = $("time", tpl);
    time.dateTime = it.date;
    time.textContent = fmtDate(it.date);
    time.title = relDay(it.date);
    const isNew = meta && it.first_seen && (Date.parse(meta.updated) - Date.parse(it.first_seen)) < 30 * 3600e3
      && state.saved !== "1";
    $(".badge-new", tpl).textContent = isNew ? T.new : "";

    const a = $(".title a", tpl);
    a.href = it.url;
    a.textContent = it.title;

    $(".kind", tpl).textContent = T["type_" + it.type] || it.type;
    $(".srcs", tpl).textContent = it.sources.map((s) => T.src_names[s] || s).join(" + ");
    const au = it.authors || [];
    $(".authors", tpl).textContent = au.length > 3 ? `${au.slice(0, 3).join(", ")} ${T.and_more(au.length)}` : au.join(", ");

    $(".tldr", tpl).textContent = it.tldr || "";
    const sum = $(".summary", tpl);
    sum.textContent = it.summary || "";
    sum.onclick = () => sum.classList.add("open");

    const tags = $(".topic-tags", tpl);
    for (const t of it.topics) {
      const li = document.createElement("li");
      const b = document.createElement("button");
      b.type = "button";
      b.style.setProperty("--c", colorVar(t));
      b.textContent = tName(t);
      b.onclick = () => { setState({ topic: t }); window.scrollTo({ top: 0, behavior: "smooth" }); };
      li.appendChild(b);
      tags.appendChild(li);
    }

    const m = it.metrics || {};
    const met = $(".metrics", tpl);
    for (const [k, label] of [["stars", T.m_stars], ["upvotes", T.m_upvotes], ["likes", T.m_likes], ["downloads", T.m_downloads]]) {
      if (m[k]) {
        const s = document.createElement("span");
        s.innerHTML = `<b>${fmtNum(m[k])}</b>`;
        s.append(label);
        met.appendChild(s);
      }
    }

    const links = $(".links", tpl);
    const L = it.links || {};
    for (const k of ["pdf", "code", "hf", "paper", "home"]) {
      if (!L[k] || L[k] === it.url) continue;
      const l = document.createElement("a");
      l.href = L[k]; l.target = "_blank"; l.rel = "noopener";
      l.textContent = T.links[k];
      if (k === "code") l.className = "code";
      links.appendChild(l);
    }

    const star = $(".star", tpl);
    const sync = () => {
      const on = !!saved[it.id];
      star.setAttribute("aria-pressed", String(on));
      star.setAttribute("aria-label", on ? T.star_remove : T.star_add);
      star.title = on ? T.star_remove : T.star_add;
    };
    star.onclick = () => {
      if (saved[it.id]) delete saved[it.id];
      else { const { _hay, ...snap } = it; saved[it.id] = snap; }
      store.set("radar.saved", saved);
      sync();
      buildControls();
    };
    sync();
    return tpl;
  }

  function renderList() {
    const list = $("#list");
    list.innerHTML = "";
    const frag = document.createDocumentFragment();
    for (const it of filtered.slice(0, shown)) frag.appendChild(rowFor(it));
    list.appendChild(frag);

    const rest = filtered.length - shown;
    const more = $("#more-btn");
    more.hidden = rest <= 0;
    if (rest > 0) more.textContent = T.more(Math.min(rest, PAGE));

    const total = state.saved === "1" ? Object.keys(saved).length : items.length;
    $("#result-count").textContent = T.count(filtered.length, total);
    const dirty = ["topic", "type", "source", "range", "q", "saved"].some((k) => state[k] !== DEFAULTS[k]);
    const reset = $("#reset-btn");
    reset.hidden = !dirty;
    reset.textContent = T.reset;

    const empty = $("#empty");
    empty.hidden = filtered.length > 0;
    if (!filtered.length) {
      empty.textContent = !items.length && state.saved !== "1" ? T.empty_data
        : state.saved === "1" && !Object.keys(saved).length ? T.empty_saved : T.empty_filter;
    }
  }

  function render() {
    buildControls();
    renderSpectrum();
    filtered = applyFilters();
    renderList();
  }

  /* ---------------- 事件 ---------------- */
  function bind() {
    let timer;
    const q = $("#q");
    q.value = state.q;
    q.addEventListener("input", () => {
      clearTimeout(timer);
      timer = setTimeout(() => setState({ q: q.value.trim() }), 180);
    });
    $("#source-sel").onchange = (e) => setState({ source: e.target.value });
    $("#range-sel").onchange = (e) => setState({ range: e.target.value });
    $("#saved-btn").onclick = () => setState({ saved: state.saved === "1" ? "0" : "1" });
    $("#reset-btn").onclick = () => { q.value = ""; setState({ ...DEFAULTS, sort: state.sort }); };
    $("#more-btn").onclick = () => {
      const from = shown;
      shown += PAGE;
      const frag = document.createDocumentFragment();
      for (const it of filtered.slice(from, shown)) frag.appendChild(rowFor(it));
      $("#list").appendChild(frag);
      const rest = filtered.length - shown;
      $("#more-btn").hidden = rest <= 0;
      if (rest > 0) $("#more-btn").textContent = T.more(Math.min(rest, PAGE));
    };
    // 深浅色切换由全站顶栏（../assets/site.js）负责
    window.addEventListener("hashchange", () => { state = readHash(); q.value = state.q; render(); });
    document.addEventListener("keydown", (e) => {
      if (e.key === "/" && document.activeElement !== q) { e.preventDefault(); q.focus(); }
    });
  }

  /* ---------------- 启动 ---------------- */
  async function load() {
    bind();
    applyLang();
    try {
      const bust = "?v=" + Math.floor(Date.now() / 6e5); // 10 分钟内复用缓存
      const [m, d] = await Promise.all([
        fetch("data/meta.json" + bust).then((r) => (r.ok ? r.json() : null)),
        fetch("data/items.json" + bust).then((r) => (r.ok ? r.json() : null)),
      ]);
      meta = m;
      items = (d && d.items) || [];
      if (meta) for (const t of meta.topics) topicsById[t.id] = t;
    } catch (err) {
      console.error(err);
      $("#empty").hidden = false;
      $("#empty").textContent = T.load_error;
    }
    applyLang();
    render();
  }

  load();
})();
