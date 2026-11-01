/* 全站顶部导航与深浅色切换。
   用法：在 <body> 开头写 <script src="assets/site.js" data-base="./"></script>
        子目录页面（markets/、ai/）写 data-base="../"，并在 <html> 上写 data-section="markets" 之类。
   改网站名称或导航，只需改下面的 SITE_NAME 和 NAV。 */
(function () {
  "use strict";
  const SITE_NAME = "星图智策";
  const me = document.currentScript;
  const base = (me && me.dataset.base) || "./";
  const isRoot = base === "./";
  const root = document.documentElement;
  const desk = (h) => (isRoot ? "#/" + h : base + "#/" + h); // 首页、资讯、工具、知识库、公司财报是一个单页应用，用 # 路由

  // [栏目 id, 名称, 链接]
  const NAV = [
    ["home", "首页", isRoot ? "#/" : base],
    ["markets", "行情快讯", base + "markets/"],
    ["news", "资讯", desk("news")],
    ["tools", "工具", desk("tools")],
    ["kb", "知识库", desk("kb")],
    ["company", "公司财报", desk("company")],
    ["ai", "AI 前沿", base + "ai/"],
  ];

  /* ---------- 深浅色：全站共用一个设置 ---------- */
  const KEY = "site.theme";
  const store = {
    get() { try { return localStorage.getItem(KEY); } catch { return null; } },
    set(v) { try { localStorage.setItem(KEY, v); } catch { /* 隐私模式等情况下忽略 */ } },
  };
  const saved = store.get();
  if (saved === "dark" || saved === "light") root.dataset.theme = saved;
  const isDark = () => (root.dataset.theme ? root.dataset.theme === "dark" : matchMedia("(prefers-color-scheme: dark)").matches);

  /* ---------- 顶栏 ---------- */
  const esc = (s) => String(s).replace(/[&<>"]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]));
  const current = root.dataset.section || "";
  const links = NAV.map(([id, name, href]) =>
    `<a href="${esc(href)}" data-section="${id}"${id === current ? ' aria-current="page"' : ""}>${esc(name)}</a>`).join("");
  const html =
    `<header class="site-top"><div class="site-top-inner">` +
    `<a class="site-brand" href="${esc(isRoot ? "#/" : base)}">${esc(SITE_NAME)}</a>` +
    `<nav class="nav" aria-label="主导航">${links}</nav>` +
    `<button type="button" class="site-theme" id="site-theme" aria-label="切换深浅色">` +
    `<svg viewBox="0 0 20 20" width="16" height="16" aria-hidden="true"><path d="M10 2a8 8 0 1 0 0 16V2z" fill="currentColor"/>` +
    `<circle cx="10" cy="10" r="7.25" fill="none" stroke="currentColor" stroke-width="1.5"/></svg></button>` +
    `</div></header>`;
  if (me) me.insertAdjacentHTML("beforebegin", html);
  else document.body.insertAdjacentHTML("afterbegin", html);

  document.getElementById("site-theme").addEventListener("click", () => {
    root.dataset.theme = isDark() ? "light" : "dark";
    store.set(root.dataset.theme);
    window.dispatchEvent(new CustomEvent("site:theme", { detail: root.dataset.theme })); // 图表等需要重绘的页面监听这个事件
  });

  /* ---------- 数据源失败原因：把技术报错翻译成一句话 ---------- */
  function explainError(msg) {
    const m = String(msg || "");
    const code = (n) => new RegExp(`(HTTP ${n}\\b|\\b${n} (Client|Server) Error)`).test(m); // 只认状态码，不误认网址里的数字
    if (/^跳过/.test(m)) return "同一网站的其他栏目刚失败，本次跳过";
    if (/超时|timed out|Timeout/i.test(m)) return "请求超时：网站响应太慢或限制海外访问";
    if (/sec\.gov/i.test(m) && code(403)) return "SEC 拒绝访问：需要在仓库设置里添加 SEC_USER_AGENT（含联系邮箱）";
    if (code(403)) return "网站拒绝了服务器的访问（403），通常是反爬虫或限制海外访问";
    if (code(404)) return "地址不存在（404），可能网站改版";
    if (code(429)) return "请求太频繁被限流（429），下次会自动重试";
    if (/(HTTP 5\d\d\b|\b5\d\d Server Error)/.test(m)) return "对方服务器出错，下次会自动重试";
    if (/无法连接|Failed to establish|Connection refused|NameResolution/i.test(m)) return "无法连接到网站";
    if (/没有找到符合规则的链接/.test(m)) return "页面里找不到文章链接：网站改版或列表由脚本加载，需要调整配置";
    return m.length > 80 ? m.slice(0, 80) + "…" : m;
  }

  window.Site = { name: SITE_NAME, base, isDark, explainError };
})();
