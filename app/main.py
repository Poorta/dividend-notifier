"""
Dividend Notifier — FastAPI 应用入口 (WebApp 版)

提供:
- Web API (JSON 查询 + 文件下载 + 手动触发 + 配置管理)
- 简易前端 (仪表盘 + 设置页)
- APScheduler 定时调度 (无需 launchd)
- Swagger 文档 (/docs)
"""

import os
import sys
from contextlib import asynccontextmanager
from datetime import datetime, timedelta
from typing import Optional

from fastapi import FastAPI, Query, BackgroundTasks
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from jinja2 import Environment, FileSystemLoader
from pydantic import BaseModel
from starlette.requests import Request

# 确保项目根目录在 sys.path 中
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, PROJECT_ROOT)

from app.paths import static_dir, template_dir
from app.config import settings
from app.models.database import init_db, get_session_factory
from app.models.stock import StockDividendData, PushLog
from app.services.settings_service import (
    init_default_settings,
    load_settings_from_db,
    save_settings_to_db,
    get_settings_dict,
)
from app.utils.logger import logger

# ============================================================
# APScheduler
# ============================================================
_scheduler = None


def _get_scheduler():
    """懒加载 APScheduler BackgroundScheduler"""
    global _scheduler
    if _scheduler is None:
        from apscheduler.schedulers.background import BackgroundScheduler
        _scheduler = BackgroundScheduler(timezone="Asia/Shanghai")
    return _scheduler


def _start_schedule():
    """根据当前配置启动定时任务"""
    sched = _get_scheduler()
    job_id = "daily_dividend_job"

    # 移除已有任务
    if sched.get_job(job_id):
        sched.remove_job(job_id)

    # 从 DB 读取 schedule_enabled
    db = get_session_factory()()
    try:
        from app.models.stock import AppSettings
        row = db.query(AppSettings).filter(AppSettings.id == 1).first()
        enabled = bool(row.schedule_enabled) if row else False
        hour = row.send_hour if row else settings.send_hour
        minute = row.send_minute if row else settings.send_minute
    finally:
        db.close()

    if not enabled:
        logger.info("定时推送未启用 (schedule_enabled=0)")
        return

    from scripts.daily_job import run_daily_job

    sched.add_job(
        run_daily_job,
        "cron",
        hour=hour,
        minute=minute,
        id=job_id,
        replace_existing=True,
    )
    logger.info(f"定时推送已启用: 每日 {hour:02d}:{minute:02d}")


# ============================================================
# FastAPI 应用 (lifespan 管理调度器生命周期)
# ============================================================

@asynccontextmanager
async def lifespan(app: FastAPI):
    """应用生命周期: 启动时初始化 DB + 调度器，关闭时停止调度器"""
    init_db()
    init_default_settings()
    load_settings_from_db()
    sched = _get_scheduler()
    sched.start()
    _start_schedule()
    logger.info("FastAPI 服务已启动 (APScheduler 已激活)")
    yield
    if _scheduler:
        _scheduler.shutdown(wait=False)
        logger.info("APScheduler 已关闭")


app = FastAPI(
    title="Dividend Notifier",
    description="高股息股票每日分析报告工具 — WebApp",
    version="2.0.0",
    docs_url="/docs",
    redoc_url=None,
    lifespan=lifespan,
)

# 静态文件 (CSS)
app.mount("/static", StaticFiles(directory=static_dir()), name="static")

# Jinja2 环境
_jinja_env = Environment(
    loader=FileSystemLoader(template_dir()),
    autoescape=True,
)


def render_template(name: str, context: dict) -> HTMLResponse:
    template = _jinja_env.get_template(name)
    html = template.render(**context)
    return HTMLResponse(content=html)


# ============================================================
# Settings Pydantic model
# ============================================================

class SettingsUpdate(BaseModel):
    """前端提交的设置 JSON schema"""
    mail_username: Optional[str] = None
    mail_password: Optional[str] = None
    mail_host: Optional[str] = None
    mail_port: Optional[int] = None
    recipients: Optional[str] = None
    send_hour: Optional[int] = None
    send_minute: Optional[int] = None
    schedule_enabled: Optional[int] = None
    min_consecutive_years: Optional[int] = None
    max_consecutive_years: Optional[int] = None
    min_market_cap: Optional[float] = None
    max_market_cap: Optional[float] = None
    min_dividend_yield: Optional[float] = None
    max_dividend_yield: Optional[float] = None
    min_pe_ratio: Optional[float] = None
    max_pe_ratio: Optional[float] = None
    min_pb_ratio: Optional[float] = None
    max_pb_ratio: Optional[float] = None
    min_latest_price: Optional[float] = None
    max_latest_price: Optional[float] = None
    min_annual_dividend: Optional[float] = None
    max_annual_dividend: Optional[float] = None
    min_ytd_return: Optional[float] = None
    max_ytd_return: Optional[float] = None
    exclude_st: Optional[int] = None
    exclude_new_listing_days: Optional[int] = None
    color_div_yield_red: Optional[float] = None
    color_div_yield_green: Optional[float] = None
    color_ytd_red: Optional[float] = None
    color_ytd_green: Optional[float] = None
    color_consecutive_red: Optional[int] = None
    color_consecutive_green: Optional[int] = None
    output_format: Optional[str] = None
    ai_api_url: Optional[str] = None
    ai_api_key: Optional[str] = None
    ai_model: Optional[str] = None
    ai_prompt: Optional[str] = None
    ai_top_n: Optional[int] = None
    ai_candidate_limit: Optional[int] = None


# ============================================================
# API 端点 — 数据查询
# ============================================================

@app.get("/api/stocks")
async def get_stocks(
    date: Optional[str] = Query(None, description="日期 YYYY-MM-DD，默认今天"),
    top: Optional[int] = Query(None, description="返回 TOP N"),
):
    if date is None:
        date = datetime.now().strftime("%Y-%m-%d")
    session_factory = get_session_factory()
    with session_factory() as db:
        query = db.query(StockDividendData).filter(
            StockDividendData.date == date
        ).order_by(StockDividendData.dividend_yield.desc())
        if top:
            query = query.limit(top)
        stocks = query.all()
        return {
            "date": date,
            "count": len(stocks),
            "stocks": [
                {
                    "code": s.code, "name": s.name, "industry": s.industry,
                    "market_cap": s.market_cap, "consecutive_years": s.consecutive_years,
                    "latest_price": s.latest_price, "annual_dividend": s.annual_dividend,
                    "dividend_yield": s.dividend_yield, "ex_dividend_date": s.ex_dividend_date,
                    "year_end_price": s.year_end_price, "ytd_return": s.ytd_return,
                    "dividend_price_impact": s.dividend_price_impact,
                    "dividend_detail": s.dividend_detail,
                }
                for s in stocks
            ],
        }


@app.get("/api/history")
async def get_history(
    start: Optional[str] = Query(None),
    end: Optional[str] = Query(None),
):
    session_factory = get_session_factory()
    with session_factory() as db:
        query = db.query(PushLog).order_by(PushLog.created_at.desc())
        if start:
            query = query.filter(PushLog.date >= start)
        if end:
            query = query.filter(PushLog.date <= end)
        logs = query.limit(30).all()
        return {
            "count": len(logs),
            "logs": [
                {"id": log.id, "date": log.date, "stock_count": log.stock_count,
                 "status": log.status, "duration_ms": log.duration_ms,
                 "created_at": log.created_at, "error_msg": log.error_msg or ""}
                for log in logs
            ],
        }


@app.get("/api/status")
async def api_status():
    """返回服务状态（调度器状态 + 最近推送记录）"""
    from app.models.stock import AppSettings

    session_factory = get_session_factory()
    with session_factory() as db:
        # 调度器状态
        row = db.query(AppSettings).filter(AppSettings.id == 1).first()
        sched_enabled = bool(row.schedule_enabled) if row else False
        sched_hour = row.send_hour if row else settings.send_hour
        sched_min = row.send_minute if row else settings.send_minute

        # 调度器下次运行时间
        next_run = None
        if _scheduler:
            job = _scheduler.get_job("daily_dividend_job")
            if job and job.next_run_time:
                next_run = job.next_run_time.strftime("%Y-%m-%d %H:%M")

        # 最近一次推送
        last = db.query(PushLog).order_by(PushLog.created_at.desc()).first()
        last_push = None
        if last:
            last_push = {
                "id": last.id,
                "date": last.date, "stock_count": last.stock_count,
                "status": last.status, "duration_ms": last.duration_ms,
                "created_at": last.created_at,
                "error_msg": last.error_msg or "",
            }

        # 是否已配置邮箱
        configured = bool(row and row.mail_username and row.mail_password
                          and row.recipients
                          and "your_email" not in row.mail_username
                          and "your_smtp" not in row.mail_password
                          and "user1@example" not in row.recipients)

        return {
            "schedule": {
                "enabled": sched_enabled,
                "time": f"{sched_hour:02d}:{sched_min:02d}",
                "next_run": next_run,
            },
            "last_push": last_push,
            "configured": configured,
        }


@app.get("/api/job-status/{job_id}")
async def api_job_status(job_id: int):
    """按任务 ID 查询后台刷新进度，供前端精准轮询。"""
    session_factory = get_session_factory()
    with session_factory() as db:
        log = db.get(PushLog, job_id)
        if not log:
            return JSONResponse(
                {"status": "error", "message": "任务不存在"},
                status_code=404,
            )
        return {
            "id": log.id,
            "date": log.date,
            "stock_count": log.stock_count,
            "status": log.status,
            "duration_ms": log.duration_ms,
            "created_at": log.created_at,
            "error_msg": log.error_msg or "",
        }


@app.post("/api/trigger")
async def trigger_job(background_tasks: BackgroundTasks):
    """手动触发每日任务。
    先写入 push_log(status=running)，让前端轮询立即感知。
    后台任务完成后会更新同一条记录。
    """
    today = datetime.now().strftime("%Y-%m-%d")
    session_factory = get_session_factory()
    push_log_id = None
    try:
        with session_factory() as db:
            running_logs = db.query(PushLog).filter(
                PushLog.date == today,
                PushLog.status == "running",
            ).order_by(PushLog.created_at.desc()).all()

            fresh_running = None
            for running in running_logs:
                try:
                    created_at = datetime.strptime(running.created_at, "%Y-%m-%d %H:%M:%S")
                except Exception:
                    created_at = datetime.min
                if datetime.now() - created_at < timedelta(minutes=10):
                    fresh_running = running
                    break
                running.status = "failed"
                running.error_msg = "上一次刷新异常中断，已自动释放运行锁"

            if fresh_running:
                return {
                    "status": "accepted",
                    "message": "刷新任务已经在后台运行，请稍后查看报表中心",
                    "date": today,
                    "job_id": fresh_running.id,
                }

            if running_logs:
                db.commit()

            push_log = PushLog(date=today, status="running")
            db.add(push_log)
            db.commit()
            push_log_id = push_log.id
    except Exception:
        pass  # 即使日志写入失败也继续触发

    from scripts.daily_job import run_daily_job
    background_tasks.add_task(run_daily_job, push_log_id)
    return {
        "status": "accepted",
        "message": "任务已在后台启动",
        "date": today,
        "job_id": push_log_id,
    }


@app.get("/api/report/xlsx")
async def download_xlsx(date: Optional[str] = Query(None)):
    if date is None:
        date = datetime.now().strftime("%Y%m%d")
    else:
        date = date.replace("-", "")
    filename = f"dividend_report_{date}.xlsx"
    filepath = os.path.join(settings.output.output_dir, filename)
    if not os.path.exists(filepath):
        return JSONResponse({"error": f"报表文件不存在: {filename}"}, status_code=404)
    return FileResponse(
        filepath,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        filename=filename,
    )


@app.get("/api/report/pdf")
async def download_pdf(date: Optional[str] = Query(None)):
    if date is None:
        date = datetime.now().strftime("%Y%m%d")
    else:
        date = date.replace("-", "")
    filename = f"dividend_report_{date}.pdf"
    filepath = os.path.join(settings.output.output_dir, filename)
    if not os.path.exists(filepath):
        return JSONResponse({"error": f"报表文件不存在: {filename}"}, status_code=404)
    return FileResponse(filepath, media_type="application/pdf", filename=filename)


# ============================================================
# API 端点 — 用户配置
# ============================================================

@app.get("/api/settings")
async def api_get_settings():
    """获取当前用户配置"""
    return get_settings_dict()


@app.put("/api/settings")
async def api_save_settings(data: SettingsUpdate):
    """保存用户配置并立即生效"""
    payload = {k: v for k, v in data.model_dump().items() if v is not None}
    save_settings_to_db(payload)
    _start_schedule()  # 重新加载调度器
    return {"status": "ok", "message": "配置已保存并生效"}


@app.post("/api/settings/test-email")
async def api_test_email():
    """发送测试邮件"""
    if not settings.mail.username or not settings.mail.password:
        return JSONResponse(
            {"status": "error", "message": "请先填写邮箱和授权码"},
            status_code=400,
        )
    if not settings.mail.recipients:
        return JSONResponse(
            {"status": "error", "message": "请先填写收件人"},
            status_code=400,
        )
    try:
        import yagmail
        yag = yagmail.SMTP(
            user=settings.mail.username,
            password=settings.mail.password,
            host=settings.mail.host,
            port=settings.mail.port,
        )
        yag.send(
            to=settings.mail.recipients,
            subject="[Dividend Notifier] 测试邮件",
            contents="🎉 恭喜！邮件配置成功！\n\n这是一封来自 Dividend Notifier 的测试邮件。\n如果收到此邮件，说明你的 SMTP 配置正确，每日红利股报表将按时推送到此邮箱。",
        )
        return {"status": "ok", "message": f"测试邮件已发送至 {', '.join(settings.mail.recipients)}"}
    except Exception as e:
        logger.error(f"测试邮件发送失败: {e}")
        return JSONResponse(
            {"status": "error", "message": f"发送失败: {str(e)}"},
            status_code=500,
        )


# ============================================================
# API 端点 — 自选股 & 选股模式
# ============================================================
from app.services import watchlist_service as wl


@app.get("/api/watchlist")
async def api_get_watchlist():
    """获取自选股列表"""
    return wl.get_watchlist()


@app.post("/api/watchlist")
async def api_add_stock(data: dict):
    """添加自选股"""
    code = data.get("code", "").strip()
    name = data.get("name", "").strip()
    if not code or not name:
        return JSONResponse({"status": "error", "message": "代码和名称不能为空"}, status_code=400)
    return wl.add_stock(code, name)


@app.delete("/api/watchlist/{code}")
async def api_remove_stock(code: str):
    """删除自选股"""
    return wl.remove_stock(code)


@app.put("/api/watchlist/mode")
async def api_set_mode(data: dict):
    """切换选股模式"""
    mode = data.get("mode", "filter")
    return wl.set_selection_mode(mode)


@app.post("/api/watchlist/batch")
async def api_batch_watchlist(data: dict):
    """批量添加用户输入的自选股代码"""
    codes = data.get("codes")

    if codes and isinstance(codes, list):
        return wl.batch_add(codes)
    return JSONResponse({"status": "error", "message": "请提供 codes"}, status_code=400)


@app.get("/api/search-stocks")
async def api_search_stocks(q: str = Query(..., min_length=1)):
    """搜索股票"""
    results = wl.search_stocks(q)
    return results


# ============================================================
# 前端页面
# ============================================================

@app.get("/", response_class=HTMLResponse)
async def index(request: Request):
    """首页仪表盘"""
    today = datetime.now().strftime("%Y-%m-%d")
    session_factory = get_session_factory()
    with session_factory() as db:
        stocks = db.query(StockDividendData).filter(
            StockDividendData.date == today
        ).order_by(StockDividendData.dividend_yield.desc()).all()
        industries = {}
        total_yield = 0
        for s in stocks:
            ind = s.industry or "其他"
            industries[ind] = industries.get(ind, 0) + 1
            total_yield += (s.dividend_yield or 0)
        avg_yield = round(total_yield / len(stocks), 2) if stocks else 0
        top_industries = sorted(industries.items(), key=lambda x: x[1], reverse=True)[:5]
        recent_logs = db.query(PushLog).order_by(PushLog.created_at.desc()).limit(5).all()

        # 最近一次推送是否失败
        last_push_failed = False
        if recent_logs and recent_logs[0].status == 'failed':
            last_push_failed = True

        # 检查是否已配置
        from app.models.stock import AppSettings
        cfg = db.query(AppSettings).filter(AppSettings.id == 1).first()
        needs_config = not (cfg and cfg.mail_username and cfg.mail_password
                           and cfg.recipients
                           and "your_email" not in cfg.mail_username
                           and "your_smtp" not in cfg.mail_password
                           and "user1@example" not in cfg.recipients)
        sched_enabled = bool(cfg.schedule_enabled) if cfg else False

        # 调度器下次运行时间
        next_run = None
        if _scheduler:
            job = _scheduler.get_job("daily_dividend_job")
            if job and job.next_run_time:
                next_run = job.next_run_time.strftime("%Y-%m-%d %H:%M")

    return render_template("index.html", {
        "request": request,
        "today": today,
        "stock_count": len(stocks),
        "industry_count": len(industries),
        "avg_yield": avg_yield,
        "top_industries": top_industries,
        "top_stocks": [_stock_to_dict(s) for s in stocks[:10]],
        "recent_logs": [_log_to_dict(log) for log in recent_logs],
        "send_hour": settings.send_hour,
        "send_minute": settings.send_minute,
        "needs_config": needs_config,
        "schedule_enabled": sched_enabled,
        "next_run": next_run,
        "last_push_failed": last_push_failed,
    })


@app.get("/preview", response_class=HTMLResponse)
async def preview(request: Request):
    """旧预览页 — 重定向到报表中心"""
    return _reports_handler(request, None)


@app.get("/reports", response_class=HTMLResponse)
async def reports_page(request: Request, date: Optional[str] = Query(None, description="日期 YYYY-MM-DD")):
    """报表中心 — 行业分组全量表格 + 下载"""
    return _reports_handler(request, date)


def _reports_handler(request: Request, query_date: Optional[str]):
    """报表页共用处理逻辑，支持日期参数"""
    today = query_date if query_date else datetime.now().strftime("%Y-%m-%d")

    # 先用今天数据，没有则查最新
    session_factory = get_session_factory()
    with session_factory() as db:
        stocks = db.query(StockDividendData).filter(
            StockDividendData.date == today
        ).order_by(StockDividendData.industry, StockDividendData.dividend_yield.desc()).all()

        if not stocks:
            # 查找最近有数据的日期
            last = db.query(StockDividendData).order_by(
                StockDividendData.date.desc()
            ).first()
            if last:
                today = last.date
                stocks = db.query(StockDividendData).filter(
                    StockDividendData.date == today
                ).order_by(StockDividendData.industry, StockDividendData.dividend_yield.desc()).all()

        # 查找前后日期 (用于导航)
        dates = [r[0] for r in db.query(StockDividendData.date).distinct().order_by(StockDividendData.date).all()]
        prev_date = None
        next_date = None
        if today in dates:
            idx = dates.index(today)
            if idx > 0:
                prev_date = dates[idx - 1]
            if idx < len(dates) - 1:
                next_date = dates[idx + 1]

        # 按行业分组
        grouped = {}
        for s in stocks:
            ind = s.industry or "其他"
            if ind not in grouped:
                grouped[ind] = []
            grouped[ind].append(_stock_full_dict(s))

        # 获取颜色阈值
        from app.models.stock import AppSettings
        cfg = db.query(AppSettings).filter(AppSettings.id == 1).first()
        colors = {
            "div_yield_red": cfg.color_div_yield_red if cfg else 5.0,
            "div_yield_green": cfg.color_div_yield_green if cfg else 3.0,
            "ytd_red": cfg.color_ytd_red if cfg else 0.0,
            "ytd_green": cfg.color_ytd_green if cfg else -5.0,
            "cons_red": cfg.color_consecutive_red if cfg else 10,
            "cons_green": cfg.color_consecutive_green if cfg else 5,
        }

    return render_template("reports.html", {
        "request": request,
        "today": today,
        "grouped": grouped,
        "total_stocks": len(stocks),
        "industry_count": len(grouped),
        "avg_yield": round(
            sum(s.dividend_yield or 0 for s in stocks) / len(stocks), 2
        ) if stocks else 0,
        "colors": colors,
        "prev_date": prev_date,
        "next_date": next_date,
    })


@app.get("/settings", response_class=HTMLResponse)
async def settings_page(request: Request):
    """旧设置页 — 重定向到通知设置"""
    return _notifications_handler(request)


@app.get("/notifications", response_class=HTMLResponse)
async def notifications_page(request: Request):
    """通知设置页"""
    return _notifications_handler(request)


@app.get("/stock-pick", response_class=HTMLResponse)
async def stock_pick_page(request: Request):
    """选股设置页"""
    cfg = get_settings_dict()
    # 读 selection_mode
    from app.services.watchlist_service import get_selection_mode
    mode = get_selection_mode()
    return render_template("stock_pick.html", {
        "request": request,
        "config": cfg,
        "mode": mode,
    })


def _notifications_handler(request: Request):
    cfg = get_settings_dict()
    return render_template("notifications.html", {
        "request": request,
        "config": cfg,
    })


def _stock_to_dict(s: StockDividendData) -> dict:
    return {
        "industry": s.industry, "name": s.name, "code": s.code,
        "market_cap": s.market_cap, "consecutive_years": s.consecutive_years,
        "latest_price": s.latest_price, "dividend_yield": s.dividend_yield,
        "ytd_return": s.ytd_return, "ex_dividend_date": s.ex_dividend_date,
        "dividend_detail": s.dividend_detail,
        "selection_source": s.selection_source,
    }


def _stock_full_dict(s: StockDividendData) -> dict:
    """预览页用的完整13列"""
    def yield_price(rate: float) -> float:
        annual_dividend = s.annual_dividend or 0
        return round(annual_dividend / (rate / 100), 2) if annual_dividend > 0 else 0

    return {
        "industry": s.industry, "name": s.name, "code": s.code,
        "market_cap": s.market_cap, "consecutive_years": s.consecutive_years,
        "latest_price": s.latest_price, "annual_dividend": s.annual_dividend,
        "dividend_yield": s.dividend_yield, "ex_dividend_date": s.ex_dividend_date,
        "year_end_price": s.year_end_price, "ytd_return": s.ytd_return,
        "dividend_price_impact": s.dividend_price_impact,
        "dividend_detail": s.dividend_detail,
        "selection_source": s.selection_source,
        "yield_price_4": yield_price(4),
        "yield_price_5": yield_price(5),
        "yield_price_6": yield_price(6),
        "yield_price_7": yield_price(7),
        "yield_price_8": yield_price(8),
    }


def _log_to_dict(log: PushLog) -> dict:
    return {
        "date": log.date, "stock_count": log.stock_count,
        "status": log.status, "duration_ms": log.duration_ms,
    }
