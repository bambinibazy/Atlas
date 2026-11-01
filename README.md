# 星图智策 · Atlas

> 兼听则明。

企业管理与财务决策的一站式网站。由原来的四个网站合并而成，共用一个仓库、一个网址、一套导航和配色：

| 栏目 | 内容 | 原来的网站 | 更新频率 |
|---|---|---|---|
| **首页** | 主要指数行情带、7×24 快讯、最新资讯、AI 前沿精选、常用工具和管理方法 | 新增 | 跟随各栏目 |
| **行情快讯** `markets/` | A 股、港股、美股、全球指数、外汇、商品、国债、加密货币行情；财联社等 7×24 快讯；公司公告；中美宏观数据 | 财经雷达 | 每 30 分钟 |
| **资讯** `#/news` | 四大会计师事务所洞察、哈佛商业评论、MIT 斯隆、麦肯锡、澎湃等财经媒体；财政部、税务总局、证监会、国资委等政策发布 | 经营决策台 + 财管日报 | 每 6 小时 |
| **工具** `#/tools` | 11 个在线计算器：项目投资、盈亏平衡、现金流预测、营运资金、杜邦、定价、WACC、贷款、决策矩阵、期望值、个人所得税；常用网站 | 经营决策台 + 财管日报 | 纯前端 |
| **知识库** `#/kb` | 40 篇管理方法与会计准则讲解 | 经营决策台 | 推送后自动编译 |
| **公司财报** `#/company` | 约 55 家上市公司近 5 年财务指标、同行中位数、杜邦分解；“分析我的公司” | 经营决策台 | 每周 |
| **AI 前沿** `ai/` | arXiv、Hugging Face、GitHub、bioRxiv 上的 AI 论文、代码和模型，按 7 个主题分类 | AI 前沿雷达 | 每天 |

全站只用中文界面，配色为深海军蓝 + 白底，支持深浅色切换（全站共用一个设置）。
不需要服务器和数据库：GitHub Actions 定时抓取，结果发布到 GitHub Pages，公开仓库完全免费。

> 本站内容仅供学习参考，不构成投资、财务、税务或法律建议。

---

## 部署（约 10 分钟）

1. 在 GitHub 新建一个**公开**仓库，把本项目推送到 `main` 分支：
   ```bash
   cd atlas
   git init && git add . && git commit -m "init"
   git branch -M main
   git remote add origin https://github.com/<你的用户名>/<仓库名>.git
   git push -u origin main
   ```
2. 仓库 **Settings → Actions → General → Workflow permissions** 选 **Read and write permissions**，保存。
3. 推送后 Actions 会自动运行第一次。第一次要抓全部栏目（AI 前沿受 arXiv 限速影响较慢），大约 15～25 分钟。
   没有自动运行的话：**Actions** → 「更新数据并发布」→ **Run workflow**，`parts` 填 `all`。
4. 运行完成后仓库里会出现 `public` 分支。**Settings → Pages → Build and deployment**：Source 选 **Deploy from a branch**，分支选 **public**、目录 **/ (root)**，保存。
5. 一两分钟后网站上线：`https://<你的用户名>.github.io/<仓库名>/`

### 建议的可选设置

**Settings → Secrets and variables → Actions**：

| 名称 | 类型 | 作用 |
|---|---|---|
| `SEC_USER_AGENT` | Variables | SEC 要求请求带联系方式，例如 `Atlas 你的邮箱`。用于美股公告和美股财报。不填会用 GitHub 的 noreply 地址 |
| `FRED_API_KEY` | Secrets | [免费申请](https://fred.stlouisfed.org/docs/api/api_key.html)后美国宏观数据走官方 API，更稳定。不填则用 FRED 公开 CSV |
| `COINGECKO_DEMO_KEY` | Secrets | 提高加密货币行情的请求额度，不填也能用 |

### 从原来的四个仓库迁移

- 原来的四个网站可以保留，也可以停用：在旧仓库的 **Actions** 页把工作流 **Disable**，或者直接归档（Archive）仓库，避免重复占用 Actions 时间。
- 旧网站的历史数据**不会**自动带过来。新网站第一次运行后从零开始积累：快讯保留 3～14 天，资讯 45 天，AI 前沿 60 天，所以一两周后内容就和原来差不多了。
- 财管日报原来的 `digest/` 日报文件不再生成，改为资讯栏目的 RSS 订阅：`https://<网站地址>/feed.xml`。

### 国内访问

`github.io` 在中国大陆有时较慢。`public` 分支就是完整的静态网站，可以同时接到 **Cloudflare Pages** 或 **Vercel**：
新建项目 → 连接这个仓库 → 生产分支选 `public` → 构建命令留空、输出目录 `/`。每次更新都会自动重新部署。
页面只用系统字体，不加载任何境外字体或脚本。

---

## 定时任务怎么运行

只有一个工作流 `.github/workflows/update.yml`，每 30 分钟运行一次，步骤如下：

1. 从 `public` 分支取回上次发布的数据（用于去重、保留历史、某个来源失败时沿用旧值）
2. 运行离线测试（Python + 前端计算公式），测试不通过就不发布
3. `python -m pipelines.update --plan` 按 `site/data/runs.json` 里记录的上次成功时间，决定这次运行哪些部分
4. 如果要更新资讯，临时启动一个 RSSHub 容器（澎湃等来源需要），失败时改用公共实例 rsshub.app
5. 运行到期的部分，生成首页摘要，发布到 `public` 分支（每次都是一个全新的提交，仓库不会越来越大）

| 部分 | 间隔 | 说明 |
|---|---|---|
| `markets` | 每次 | 行情、快讯、公告、宏观 |
| `news` | 6 小时 | 资讯与政策，同时重新编译知识库 |
| `ai` | 每天 | 约 10～15 分钟（arXiv 要求请求间隔 3 秒） |
| `financials` | 每周 | 上市公司财报 |

- 某个部分失败不影响其他部分，失败的部分过一段时间（1～12 小时）自动重试，期间网站沿用上次的数据。
- 手动运行时可以在 `parts` 里填 `ai,news` 之类强制运行某几部分，`all` 为全部。
- 推送代码或配置到 `main` 后会自动运行一次：重新编译知识库，并按新的关键词离线重新分类行情和 AI 条目。
- 间隔在 `pipelines/update.py` 顶部的 `INTERVALS` 里修改。
- **注意**：公开仓库如果 60 天没有任何提交，GitHub 会自动停用定时任务。Actions 页面会出现提示，点 **Enable workflow** 即可恢复；也可以偶尔改一下配置提交一次。

---

## 自定义

所有配置都在 `config/` 里，改完推送即可生效，不需要改代码：

| 文件 | 内容 |
|---|---|
| `config/desk/sources.yaml` | 资讯来源与分类。RSS 写 `url`；经 RSSHub 生成的写 `route`（路由见 [RSSHub 文档](https://docs.rsshub.app/zh/)）；没有 RSS 的网页列表页（政府网站、四大洞察）写在 `gov_lists` / `page_lists`，用 `link_pattern` 挑出文章链接。综合类来源可以加 `keywords` 只保留相关内容 |
| `config/desk/companies.yaml` | 公司财报的公司列表（A 股 6 位代码、港股 5 位、美股代码） |
| `config/markets/sources.yaml` | 行情品种、自选股、快讯和新闻来源、公告关注的公司、宏观指标；`home_quotes` 决定首页行情带显示哪些品种 |
| `config/ai/topics.yaml` | AI 前沿的主题、关键词和抓取范围 |
| `content/kb/*.md` | 知识库文章（Markdown，开头写 YAML 头信息） |
| `site/assets/links.js` | 工具页底部的「常用网站」 |
| `site/assets/site.js` | 网站名称（`SITE_NAME`）和顶部导航 |
| `site/assets/site.css` | 全站配色和字体（`--c-*` 变量），三个栏目的样式都引用这里 |

每个来源都可以写 `enabled: false` 单独关闭。网页底部的「数据源状态」会显示每个来源本次是否成功、抓到多少条、失败原因。

### 已知限制

- **四大会计师事务所**没有 RSS，抓的是各自中国站的洞察列表页（实验性）。网站改版或拦截海外机房访问时会抓不到，状态里显示“页面里没有找到符合规则的链接”，调整 `link_pattern` 或先关闭即可。
- **政府网站列表页**同理，改版后需要更新 `url` 和 `link_pattern`。
- **中文快讯、东方财富行情和财报**用的是网站前端的非公开接口（参数参考开源项目 [AKShare](https://github.com/akfamily/akshare)），改版时可能失效。
- **RSSHub 路由**由社区维护，个别路由偶尔失效。
- 港股财报个别科目名称可能对不上，显示为“–”时可在 `pipelines/desk/financials/extract.py` 的 `HK_MAP` 补充。
- 个税计算器按 2019 年起施行的综合所得税率表计算；全年一次性奖金单独计税政策执行至 2027 年 12 月 31 日（财政部、税务总局公告 2023 年第 30 号）。政策调整时以税务机关规定为准。

---

## 本地运行

```bash
pip install -r requirements.txt pytest
python -m pipelines.update --parts all          # 抓取全部栏目
python -m pipelines.update --parts markets      # 只抓某几部分：markets, news, financials, ai
python -m pipelines.update --plan               # 只看这次会运行哪些部分
python -m pipelines.desk.run --only kb          # 只编译知识库（不联网）
python -m http.server -d site 8000              # 打开 http://localhost:8000
python -m pytest -q && node --test tests/desk/js/*.test.js   # 离线测试
```

本地没有 RSSHub 时，资讯里 `route` 类型的来源会改用公共实例 rsshub.app，可能被限流；
也可以用 Docker 起一个：`docker run -d -p 1200:1200 diygod/rsshub`。
本地抓 GitHub 时建议设置 `export GITHUB_TOKEN=ghp_xxx` 提高限额。

## 项目结构

```
config/
  desk/                 资讯来源、公司列表
  markets/              行情、快讯、公告、宏观
  ai/                   AI 主题与抓取范围
content/kb/             40 篇知识库文章
pipelines/
  update.py             统一调度：按间隔运行各部分，失败互不影响
  home.py               首页摘要（从行情、AI 数据里挑出首页要显示的内容）
  desk/                 资讯、财报、知识库（原经营决策台）
  markets/              行情快讯（原财经雷达）
  ai/                   AI 前沿（原 AI 前沿雷达）
site/                   静态网站，整个目录发布到 public 分支
  index.html            首页、资讯、工具、知识库、公司财报（单页应用，# 路由）
  assets/               site.css / site.js 全站共用；fin.js 计算公式；core/tools/pages.js 页面
  markets/              行情快讯栏目
  ai/                   AI 前沿栏目
  data/ …               各栏目的 data/ 由抓取生成，不提交到 main
tests/                  离线测试与各接口格式样本
.github/workflows/      定时任务
```
