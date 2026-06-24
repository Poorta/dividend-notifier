# Dividend Notifier

Dividend Notifier 是一个本地运行的 A 股红利股分析工具。它可以获取行情和分红数据，根据股息率、连续派现年数、市值、估值等条件筛选股票，并生成 Excel/PDF 报表。

项目面向希望长期跟踪高股息、稳定分红股票的个人投资者。所有配置和运行数据默认保存在本机，不依赖云端账号。

> 免责声明：本项目仅用于数据整理和学习研究，不构成任何投资建议。股票投资存在风险，请独立判断并自行承担投资风险。

## 功能特性

- 自动获取 A 股行情和分红数据
- 支持自动筛选、手动股票池、混合模式和 AI 选股
- 支持股息率、连续派现年数、市值、PE、PB、股价、涨跌幅等筛选条件
- 生成 Excel 和 PDF 红利股报表
- 支持本地网页界面和 macOS 桌面 App
- 支持邮箱推送和定时任务
- 数据默认保存在本机，适合个人长期使用

## 直接下载使用

如果你只是想直接使用，不需要懂代码：

1. 打开 GitHub Releases 页面。
2. macOS 用户下载 `DividendNotifier-mac-arm64.dmg`。
3. Windows 用户下载 `DividendNotifier-windows-x64.zip`，解压后双击 `Dividend Notifier.exe`。
4. 在页面中配置筛选条件、邮箱和推送时间。
5. 点击“刷新数据”生成报表。

首次打开时，macOS 可能会提示“无法验证开发者”。如果你信任此项目，可以在“系统设置 → 隐私与安全性”中允许打开。

## 从源码运行

适合开发者或想自己修改代码的人。

```bash
git clone https://github.com/your-name/dividend-notifier.git
cd dividend-notifier

python3 -m venv .venv
source .venv/bin/activate

pip install -r requirements.txt
uvicorn app.main:app --reload
```

然后访问：

```text
http://localhost:8000
```

macOS 也可以直接双击：

```text
start.command
```

这个脚本会自动创建 `.venv`、安装依赖并打开浏览器。

## 打包 macOS App

在 macOS 上运行：

```bash
bash packaging/build_mac.sh
```

构建完成后，App 位于：

```text
packaging/dist/Dividend Notifier.app
packaging/dist/DividendNotifier-mac-arm64.dmg
packaging/dist/DividendNotifier-mac-arm64.zip
```

发布到 GitHub 时，建议上传 `.dmg` 给普通用户下载；`.zip` 可以作为备用格式。不要把 `packaging/dist/` 直接提交到源码仓库。

更完整的 macOS 打包说明见 [packaging/README_MACOS.md](packaging/README_MACOS.md)。

## 打包 Windows App

Windows 版本通过 GitHub Actions 在 Windows runner 上构建。手动触发仓库中的 `Build Windows Release` 工作流，输入要上传的 Release tag，例如：

```text
v0.1.0
```

构建完成后会生成并上传：

```text
DividendNotifier-windows-x64.zip
```

## 数据保存位置

从源码运行时，数据默认保存在项目目录：

```text
data/
output/
logs/
```

打包成 macOS App 后，用户数据默认保存在：

```text
~/Library/Application Support/Dividend Notifier/
```

其中包括：

- `data/dividend_notifier.db`：本地数据库
- `data/cache/`：行情和分红缓存
- `output/`：生成的 Excel/PDF 报表
- `logs/`：运行日志

这些文件不应该上传到 GitHub。

## 项目结构

```text
.
├── app/
│   ├── main.py              # FastAPI 入口
│   ├── config.py            # 配置加载
│   ├── paths.py             # 源码/桌面 App 路径管理
│   ├── models/              # SQLite 数据模型
│   ├── services/            # 数据获取、筛选、邮件、AI 选股
│   ├── reports/             # Excel/PDF 报表生成
│   ├── templates/           # 页面模板
│   └── static/              # CSS 静态资源
├── scripts/
│   ├── daily_job.py         # 数据刷新主流程
│   └── update_launchd.py    # macOS launchd 定时任务脚本
├── packaging/
│   ├── mac_launcher.py      # 桌面 App 启动入口
│   ├── build_mac.sh         # macOS 打包脚本
│   └── DividendNotifier.spec
├── tests/
├── requirements.txt
├── start.command
├── .env.example
└── LICENSE
```

更完整的目录分区和数据隔离说明见 [PROJECT_STRUCTURE.md](PROJECT_STRUCTURE.md)。

## 配置说明

大部分配置都可以在网页中完成：

- 邮箱配置
- 推送时间
- 自动筛选条件
- 颜色规则
- AI 选股 API

`.env.example` 只保留默认值示例。请不要提交自己的 `.env` 文件。

## 上传 GitHub 前检查

确认以下文件没有被提交：

- `.env`
- `data/dividend_notifier.db`
- `data/cache/`
- `output/`
- `logs/`
- `.venv/`
- `.venv-build/`
- `packaging/dist/`
- `private_backup_before_release*/`

可以用下面命令检查：

```bash
git status --short
```

## 技术栈

| 层级 | 技术 |
|---|---|
| 后端 | FastAPI |
| 本地数据库 | SQLite + SQLAlchemy |
| 数据源 | AkShare + 东方财富兜底 |
| 报表 | openpyxl + ReportLab |
| 邮件 | yagmail |
| 定时任务 | APScheduler |
| 前端 | Jinja2 + 原生 CSS |
| 桌面 App | pywebview + PyInstaller |

## License

MIT License. See [LICENSE](LICENSE).
