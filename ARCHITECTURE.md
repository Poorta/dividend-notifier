# Dividend Notifier — 系统架构设计

> 版本: v1.0 | 架构师: Noah Chen | 日期: 2026-06-16 | 关联 PRD: v2.1

---

## 目录

1. [技术栈推荐](#1-技术栈推荐)
2. [数据库设计](#2-数据库设计)
3. [数据源方案评估](#3-数据源方案评估)
4. [开发步骤拆解](#4-开发步骤拆解)

---

## 1. 技术栈推荐

### 1.1 选型总览

| 层级 | 选型 | 版本要求 | 许可 | 选型理由 |
|------|------|---------|------|---------|
| **语言** | Python | ≥ 3.11 | - | 数据科学生态最成熟，AkShare 原生支持 |
| **Web 框架** | FastAPI | ≥ 0.110 | MIT | 异步高性能、自动 OpenAPI 文档、类型安全 |
| **数据库** | SQLite (内嵌) | - | Public Domain | 零部署依赖、单文件存储、个人场景完全够用 |
| **ORM** | SQLAlchemy 2.0 | ≥ 2.0 | MIT | SQLite 最佳拍档、迁移工具 Alembic 可选 |
| **数据源** | AkShare | ≥ 1.14 | MIT | 唯一真正免费全覆盖的 A 股开源库 |
| **Excel 生成** | openpyxl | ≥ 3.1 | MIT | 原生支持条件格式/合并单元格/冻结窗格 |
| **PDF 生成** | ReportLab | ≥ 4.0 | BSD | 纯 Python，无外部依赖，支持中文字体 |
| **邮件发送** | yagmail | ≥ 0.15 | MIT | 3行代码发邮件带附件，比 smtplib 省 90% 代码量 |
| **定时调度** | macOS launchd | 系统内置 | - | 零安装、开机自启、失败不阻塞 |
| **简易前端** | Jinja2 + 静态 HTML | - | BSD | FastAPI 内置、手机端友好、无需 npm |
| **配置管理** | python-dotenv | ≥ 1.0 | BSD | 加载 .env 到 os.environ |
| **日志** | Python logging (stdlib) | - | - | 零依赖，足够用 |

### 1.2 为什么不用其他方案

| 被排除方案 | 排除理由 |
|-----------|---------|
| Django + DRF | 太重，个人项目用 FastAPI 已足够 |
| MySQL / PostgreSQL | 需要独立安装服务进程，SQLite 零运维 |
| tushare (收费版) | 免费版积分限制严重，分红数据不全 |
| baostock | 2024 年后停更，数据滞后 |
| pandas + xlsxwriter | xlsxwriter 不支持条件格式，openpyxl 支持更完整 |
| WeasyPrint (PDF) | 依赖系统 Cairo/Pango，macOS 安装经常踩坑 |
| Celery + Redis | 过重，launchd 已完成调度需求 |
| React / Vue 前端 | 个人工具不需要 SPA，Jinja2 渲染直出更快 |
| Docker | 增加复杂度，launchd 本地原生化更简单 |

### 1.3 依赖清单

```txt
# requirements.txt
fastapi>=0.110.0
uvicorn[standard]>=0.29.0
akshare>=1.14.0
openpyxl>=3.1.0
reportlab>=4.0
yagmail>=0.15.0
python-dotenv>=1.0.0
pandas>=2.2.0
sqlalchemy>=2.0.0
jinja2>=3.1.0           # FastAPI 内置，显式声明版本
```

总计 **10 个依赖**，`pip install -r requirements.txt` 一键安装，无 C 扩展编译风险。

---

## 2. 数据库设计

### 2.1 ER 关系

```
┌─────────────────────────────┐
│    stock_dividend_data      │
│─────────────────────────────│
│ PK  id          INTEGER     │
│     code        TEXT (6)    │──┐
│     name        TEXT        │  │  联合唯一索引
│     industry    TEXT        │  │  (date, code)
│     market_cap  REAL        │  │
│     consecutive_years INT   │  │
│     latest_price REAL       │  │
│     annual_dividend REAL    │  │
│     dividend_yield REAL     │  │
│     ex_dividend_date TEXT   │  │
│     year_end_price REAL     │  │
│     ytd_return   REAL       │  │
│     dividend_price_impact TEXT│ │
│     dividend_detail TEXT    │  │
│     date         TEXT (10)  │──┘
│     created_at   TEXT       │
└─────────────────────────────┘

┌─────────────────────────────┐
│        push_logs            │
│─────────────────────────────│
│ PK  id          INTEGER     │
│     date        TEXT (10)   │
│     stock_count INTEGER     │
│     recipients  TEXT (JSON) │
│     xlsx_path   TEXT        │
│     pdf_path    TEXT        │
│     status      TEXT        │
│     error_msg   TEXT        │
│     duration_ms INTEGER     │
│     created_at  TEXT        │
└─────────────────────────────┘

┌─────────────────────────────┐
│     watch_list (可选P2)      │
│─────────────────────────────│
│ PK  id          INTEGER     │
│     code        TEXT (6)    │── 唯一
│     name        TEXT        │
│     added_at    TEXT        │
│     notes       TEXT        │
└─────────────────────────────┘
```

### 2.2 完整 SQL Schema

```sql
-- ============================================================
-- Dividend Notifier 数据库初始化脚本
-- 数据库: SQLite 3
-- 运行: sqlite3 data/dividend_notifier.db < schema.sql
-- ============================================================

-- 表1: 每日红利股数据快照
CREATE TABLE IF NOT EXISTS stock_dividend_data (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    code                TEXT    NOT NULL,              -- 股票代码, 如 "601398"
    name                TEXT    NOT NULL,              -- 股票名称, 如 "工商银行"
    industry            TEXT    DEFAULT '',            -- 所属行业分组
    market_cap          REAL    DEFAULT 0,             -- 总市值(亿元)
    consecutive_years   INTEGER DEFAULT 0,             -- 连续高息年限
    latest_price        REAL    DEFAULT 0,             -- 最新收盘价
    annual_dividend     REAL    DEFAULT 0,             -- 近12个月每股现金分红(元)
    dividend_yield      REAL    DEFAULT 0,             -- 近12个月股息率(%)
    ex_dividend_date    TEXT    DEFAULT '',            -- 最近除权除息日
    year_end_price      REAL    DEFAULT 0,             -- 2025-12-31 收盘价
    ytd_return          REAL    DEFAULT 0,             -- 年初至今涨跌幅(%)
    dividend_price_impact TEXT  DEFAULT '',            -- 股息率对股价影响分析
    dividend_detail     TEXT    DEFAULT '',            -- 分红明细(送股/转增/派息)
    date                TEXT    NOT NULL,              -- 数据日期 YYYY-MM-DD
    created_at          TEXT    NOT NULL DEFAULT (datetime('now', 'localtime')),

    UNIQUE(date, code)  -- 同一日期同一股票唯一
);

-- 索引: 按日期查全量
CREATE INDEX IF NOT EXISTS idx_sdd_date ON stock_dividend_data(date);
-- 索引: 按行业+股息率排序(报表核心查询)
CREATE INDEX IF NOT EXISTS idx_sdd_industry_yield ON stock_dividend_data(industry, dividend_yield DESC);
-- 索引: 按股票代码查历史
CREATE INDEX IF NOT EXISTS idx_sdd_code ON stock_dividend_data(code);


-- 表2: 推送执行日志
CREATE TABLE IF NOT EXISTS push_logs (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    date            TEXT    NOT NULL,                  -- 推送日期 YYYY-MM-DD
    stock_count     INTEGER DEFAULT 0,                 -- 本次覆盖标的数
    recipients      TEXT    DEFAULT '[]',              -- 收件人列表 JSON
    xlsx_path       TEXT    DEFAULT '',                -- 生成的 xlsx 文件路径
    pdf_path        TEXT    DEFAULT '',                -- 生成的 pdf 文件路径
    status          TEXT    NOT NULL DEFAULT 'pending',-- pending | running | success | failed
    error_msg       TEXT    DEFAULT '',                -- 失败时的错误信息
    duration_ms     INTEGER DEFAULT 0,                 -- 全流程耗时(毫秒)
    created_at      TEXT    NOT NULL DEFAULT (datetime('now', 'localtime'))
);

CREATE INDEX IF NOT EXISTS idx_pl_date ON push_logs(date);
CREATE INDEX IF NOT EXISTS idx_pl_status ON push_logs(status);


-- 表3: 用户自选关注列表 (P2, 本期可选)
CREATE TABLE IF NOT EXISTS watch_list (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    code        TEXT    NOT NULL UNIQUE,              -- 股票代码
    name        TEXT    NOT NULL,                     -- 股票名称
    added_at    TEXT    NOT NULL DEFAULT (datetime('now', 'localtime')),
    notes       TEXT    DEFAULT ''
);
```

### 2.3 核心字段设计说明

| 字段 | 设计决策 | 原因 |
|------|---------|------|
| `code` 用 TEXT 非 INTEGER | A股代码有前导零（"000001" 非 "1"），且深市/沪市格式不同 |
| `date` 用 TEXT "YYYY-MM-DD" | SQLite 无原生 DATE 类型，TEXT 可字符串比较，排序自然正确 |
| `industry` 冗余存储 | 避免多表 JOIN 影响报表生成性能；行业变更极少，冗余成本可忽略 |
| `dividend_yield` 预计算存储 | 股息率 = annual_dividend / latest_price，每次查询都算会拖慢排序；写入时算一次即可 |
| `recipients` 用 JSON TEXT | SQLite 无数组类型，JSON 序列化后存 TEXT 最灵活 |
| `status` 加状态机 | pending→running→success/failed，便于排查 launchd 静默失败 |
| UNIQUE(date, code) | 保证同一天不会重复写入同一只股票，INSERT OR REPLACE 做幂等写入 |
| 不设外键 | SQLite 默认不开启外键约束；3张表逻辑独立，无需强关联 |

---

## 3. 数据源方案评估

### 3.1 候选数据源对比

| 数据源 | 类型 | 费用 | A股分红数据 | 行情数据 | 稳定性 | 推荐度 |
|--------|------|------|:--:|:--:|:--:|:--:|
| **AkShare** | Python 库 | 免费 | ✅ 全 | ✅ 全 | ⭐⭐⭐⭐ | ★★★★★ 首选 |
| tushare (免费版) | HTTP API | 免费(需积分) | ⚠️ 不全 | ⚠️ 受限 | ⭐⭐⭐ | ★★☆ 备选 |
| baostock | Python 库 | 免费 | ❌ 停更 | ❌ 停更 | ⭐ | ☆☆☆ 不推荐 |
| 东方财富爬虫 | 网页解析 | 免费 | ❌ 易失效 | ⚠️ 反爬 | ⭐⭐ | ★★☆ 兜底 |
| yfinance | Python 库 | 免费 | ❌ 无A股分红 | ✅ A股行情 | ⭐⭐⭐ | ☆☆☆ 仅港股/美股 |
| JoinQuant 数据API | HTTP API | 免费(需注册) | ⚠️ 不全 | ✅ 日线 | ⭐⭐ | ★★☆ 备选 |

### 3.2 推荐方案：AkShare 为主，多源兜底

#### 3.2.1 主力数据源 — AkShare

围绕参考表 13 列，AkShare 能覆盖的接口如下：

| 需求字段 | AkShare 接口 | 覆盖率 | 备注 |
|---------|-------------|:--:|------|
| 代码、名称、最新价 | `stock_zh_a_spot_em()` | 100% | 东方财富实时行情，全量A股 |
| 行业 | `stock_individual_info_em()` | 100% | 东方财富个股信息 |
| 市值 | `stock_zh_a_spot_em()` | 100% | 总市值字段直接可用 |
| 每股分红（年报） | `stock_history_dividend_detail()` | ~95% | 含除权除息日、每股派息、送转股 |
| 连续高息年限 | 基于分红历史自行计算 | - | 遍历分红记录，统计连续满足股息率阈值的年数 |
| 股息率 | 自行计算 | - | = 近12个月每股现金分红 ÷ 最新价 × 100 |
| YTD 涨跌幅 | 自行计算 | - | = (最新价 − 年初前收盘) ÷ 年初前收盘 × 100 |

#### 3.2.2 兜底数据源 — 东方财富 HTTP API

当 AkShare 接口故障时的降级方案：

```
# 个股分红配股 (东方财富原始接口)
https://datacenter.eastmoney.com/securities/api/data/v1/get?
  reportName=RPT_FN_BONUSPLAN&columns=ALL&filter=(SECURITY_CODE="601398")

# 个股日K线 (用于计算 YTD)
https://push2his.eastmoney.com/api/qt/stock/kline/get?
  secid=1.601398&fields1=f1&fields2=f51&klt=101&beg=20260101&end=20260616
```

优势：与 AkShare 同源（都来自东方财富），数据一致；劣势：需自行处理 JSON 解析和反爬。

#### 3.2.3 数据获取架构

```
             ┌──────────────┐
             │  daily_job   │
             └──────┬───────┘
                    │
          ┌─────────▼─────────┐
          │  fetcher.py       │
          │  try AkShare 优先  │
          └─────────┬─────────┘
                    │
          ┌─────────▼─────────┐
          │  成功？            │
          └────┬─────────┬────┘
               │YES      │NO (异常/502)
          ┌────▼────┐ ┌──▼──────────┐
          │ 数据清洗 │ │ fallback:    │
          │ → 写入DB │ │ 东方财富 API  │
          └─────────┘ └──────┬───────┘
                             │
                      ┌──────▼───────┐
                      │ 重试一次      │
                      │ 仍失败→记录   │
                      │ 日志+通知用户 │
                      └──────────────┘
```

### 3.3 数据采集稳定性保障策略

| 策略 | 实现方式 |
|------|---------|
| **交易日历过滤** | AkShare `tool_trade_date_hist_sina()` 获取交易日历，非交易日跳过 |
| **请求间隔** | 每个股票请求间 sleep 0.5~1s，避免被东方财富反爬 |
| **代理支持** | `.env` 中 `HTTP_PROXY` 兜底，AkShare 原生支持 |
| **本地缓存** | SQLite 持久化，非交易日复用最近交易日数据 |
| **幂等写入** | `INSERT OR REPLACE` 保证同一天多次运行不会重复入库 |
| **告警机制** | fetch 失败时写日志 + push_logs 表记录，发邮件通知用户 |

---

## 4. 开发步骤拆解

> 每个子任务独立可运行、可验证。按顺序执行，后面任务依赖前面的基础模块。

---

### Task 1: 项目骨架 + 配置管理

**目标**: 搭建项目目录结构，实现 `.env` 配置加载，验证环境可用

**产出物**:
```
dividend-notifier/
├── app/__init__.py
├── app/config.py          # python-dotenv 加载 .env → Settings dataclass
├── app/utils/logger.py    # 标准 logging 配置
├── .env.example           # 完整配置模板
├── .env                   # 用户配置(加入.gitignore)
├── requirements.txt
└── README.md
```

**验证方式**: `python -c "from app.config import settings; print(settings)"` 输出完整配置

**涉及依赖**: python-dotenv

---

### Task 2: 数据库初始化

**目标**: SQLAlchemy 连接 SQLite + 自动建表

**产出物**:
```
app/models/
├── __init__.py
├── database.py        # engine + Session + get_db() 依赖注入 + init_db()
└── stock.py           # SQLAlchemy ORM 模型 (StockDividendData, PushLog)
```

**验证方式**: 运行 `init_db()` 后 `sqlite3 data/dividend_notifier.db ".schema"` 看到 3 张表

**涉及依赖**: sqlalchemy

---

### Task 3: 数据获取 + 衍生指标计算

**目标**: 调用 AkShare 获取全量 A 股数据，计算 13 列核心指标，写入 SQLite

**产出物**:
```
app/services/
├── fetcher.py         # fetch_all_stocks() → List[StockRaw]
├── calculator.py      # 计算股息率/YTD/连续高息年限等衍生指标
└── screener.py        # 按 .env 阈值筛选 + 行业分组 + 排序
```

**关键函数签名**:
```python
# fetcher.py
def fetch_all_stocks() -> pd.DataFrame:
    """调用 AkShare 获取全量 A 股行情 + 基本面，返回 DataFrame"""

def fetch_dividend_history(code: str) -> list[dict]:
    """获取单只股票历史分红记录，用于计算连续高息年限"""

# calculator.py
def calc_dividend_yield(annual_dividend: float, latest_price: float) -> float:
    """股息率 = 每股分红 / 最新价 × 100"""

def calc_consecutive_years(dividend_records: list[dict]) -> int:
    """从最近一年往回数，统计连续分红年数"""

def calc_ytd_return(code: str, latest_price: float) -> float:
    """(最新价 - 年初前收盘) / 年初前收盘 × 100"""

# screener.py
def apply_filters(df: pd.DataFrame, settings: Settings) -> pd.DataFrame:
    """根据 .env 阈值筛选，返回过滤后 DataFrame"""

def group_by_industry(df: pd.DataFrame) -> dict[str, pd.DataFrame]:
    """按行业分组，组内按股息率降序"""
```

**验证方式**: 运行 `python scripts/test_fetch.py`，打印前 10 只股票数据，确认 13 列都有值

**涉及依赖**: akshare, pandas

---

### Task 4: Excel 报表生成

**目标**: 读取当日 SQLite 数据，用 openpyxl 生成对标参考表的行业分组 Excel

**产出物**:
```
app/reports/
├── __init__.py
├── excel_report.py    # generate_excel(date, stocks) → filepath
└── utils/colors.py    # 颜色编码规则(从 .env 读取阈值)
```

**报表要求** (对照 PRD §8):
- 行业分隔行（深蓝底白字）
- 颜色编码：股息率 > 阈值红 / < 阈值绿，YTD 同理
- 冻结标题行 + 行业列
- 红利税脚注行
- 列宽自适应

**验证方式**: 手动运行生成 `output/dividend_report_20260616.xlsx`，用 WPS/Excel 打开检查格式

**涉及依赖**: openpyxl

---

### Task 5: PDF 报表生成 + 邮件推送

**目标**: ReportLab 生成 PDF + yagmail 发送附件邮件

**产出物**:
```
app/reports/pdf_report.py   # generate_pdf(date, stocks) → filepath
app/services/mailer.py       # send_report(xlsx_path, pdf_path, recipients)
```

**PDF 要求** (对照 PRD §9):
- A4 横向，表头每页重复
- macOS 系统黑体 (Heiti SC)，自动探测字体路径
- 颜色编码与 Excel 一致

**邮件要求**:
- 主题: `📊 养老收息红利股汇总 2026.06.16`
- 正文: 简短摘要（覆盖标的数、平均股息率、行业分布）
- 附件: xlsx + pdf

**验证方式**: 手动触发一次 → 检查邮箱收到邮件 + 手机打开附件可读

**涉及依赖**: reportlab, yagmail

---

### Task 6: launchd 定时调度

**目标**: 实现 `scripts/update_launchd.py` 根据 `.env` 时间自动生成 plist 并注册 launchd

**产出物**:
```
scripts/
├── daily_job.py          # launchd 调用的主任务脚本
└── update_launchd.py     # 读取 .env → 生成 plist → launchctl load
```

**daily_job.py 执行流程**:
```
1. init_db()                    # 确保数据库就绪
2. fetch_all_stocks()           # 获取数据
3. calc + filter + group        # 计算+筛选+分组
4. INSERT OR REPLACE INTO DB    # 写入数据库
5. generate_excel() + generate_pdf()  # 生成报表
6. send_report()                # 发送邮件
7. log + push_logs INSERT       # 记录日志
```

**验证方式**: 
1. 手动运行 `python scripts/daily_job.py` → 完整执行一次
2. 修改 `.env` 推送时间 → `python scripts/update_launchd.py` → `launchctl list | grep dividend` 确认注册成功
3. 等待到设定时间，观察是否自动执行

**涉及依赖**: launchd (macOS 内置)

---

### Task 7: FastAPI Web 服务 + 简易前端

**目标**: FastAPI 包装所有核心功能，提供 API + 简易 Web 页面

**产出物**:
```
app/main.py               # FastAPI 应用入口
app/templates/
├── base.html             # 基础布局
├── index.html            # 首页（今日概览 + 手动触发按钮）
├── report.html           # 报表在线预览页
└── history.html          # 历史推送记录页
```

**API 端点**:
| 方法 | 路径 | 功能 |
|------|------|------|
| GET | `/` | 首页仪表盘 |
| GET | `/api/stocks` | 查询当日数据 (JSON) |
| GET | `/api/report/xlsx` | 下载 Excel |
| GET | `/api/report/pdf` | 下载 PDF |
| POST | `/api/trigger` | 手动触发完整流程 |
| GET | `/api/history` | 历史推送记录 |

**前端方案**: Jinja2 模板 + 内嵌 CSS（无需 npm），移动端响应式。

**验证方式**: `uvicorn app.main:app --reload` 后浏览器打开 `http://localhost:8000/docs` 和首页

**涉及依赖**: fastapi, uvicorn, jinja2

---

### Task 8: GitHub 开源发布 + README

**目标**: 项目推送到 GitHub，编写高质量 README，打上 MIT License

**产出物**:
```
README.md        # 含项目介绍、架构图(Mermaid)、安装指南、效果截图、配置说明
LICENSE          # MIT License
.gitignore       # 排除 .env, *.db, output/, __pycache__, venv/
```

**README 结构**:
1. 项目 Logo + 一句话简介
2. 效果截图（Excel 报表 + PDF 报表 + 邮件截图）
3. Mermaid 架构图
4. 快速开始（3 步安装）
5. 配置说明（.env 各项解释）
6. 技术栈
7. 开发计划 / Roadmap
8. License

**验证方式**: `git clone` 到新目录 → 按 README 走一遍 → 能跑通

---

### 任务依赖关系

```
Task 1 (骨架+配置)
  └→ Task 2 (数据库)
       └→ Task 3 (数据获取)
            ├→ Task 4 (Excel 报表)
            ├→ Task 5 (PDF+邮件)
            └→ Task 6 (定时调度)
                 └→ Task 7 (Web 服务)
                      └→ Task 8 (开源发布)
```

Task 4/5/6 可以并行开发（都依赖 Task 3 产出的数据），Task 7 建议在 4/5/6 都稳定后再做。

---

## 附录 A: 关键设计决策记录

| 决策 | 选项 A | 选项 B | 选择 | 理由 |
|------|--------|--------|:--:|------|
| 数据库 | SQLite | PostgreSQL | A | 个人项目零运维，SQLite 单表百万级无压力 |
| ORM | SQLAlchemy | 原生 sqlite3 | A | 方便后续扩展；Alembic 做迁移 |
| Excel库 | openpyxl | xlsxwriter | A | xlsxwriter 不支持条件格式/读取 |
| PDF库 | ReportLab | WeasyPrint | A | WeasyPrint 依赖系统库，macOS 安装常踩坑 |
| 前端 | Jinja2 | React | A | 个人工具无需 SPA，直出更快更简单 |
| 调度 | launchd | cron/Celery | A | macOS 原生、开机自启、plist 声明式配置 |
| 日志 | logging | loguru | A | 零额外依赖，标准库够用 |
| 字体 | 系统黑体 | 嵌入字体 | A | 免下载、macOS 默认可用 |

---

## 附录 B: 预估工时

| Task | 预估工时 | 难度 |
|------|:--:|:--:|
| Task 1: 骨架+配置 | 0.5h | ⭐ |
| Task 2: 数据库 | 0.5h | ⭐ |
| Task 3: 数据获取 | 3-4h | ⭐⭐⭐ |
| Task 4: Excel 报表 | 2-3h | ⭐⭐ |
| Task 5: PDF+邮件 | 2-3h | ⭐⭐ |
| Task 6: 定时调度 | 1h | ⭐ |
| Task 7: Web 服务 | 2-3h | ⭐⭐ |
| Task 8: 开源发布 | 1h | ⭐ |
| **合计** | **12-16h** | |
