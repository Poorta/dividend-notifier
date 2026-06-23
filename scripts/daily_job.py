#!/usr/bin/env python3
"""
每日任务主脚本

由 launchd 定时调度，执行完整的数据 → 报表 → 推送流水线:
1. 初始化数据库
2. 获取全量 A 股行情 + 分红数据
3. 计算衍生指标
4. 筛选 + 行业分组 + 排序
5. 写入 SQLite
6. 生成 Excel + PDF 报表
7. 发送邮件附件
8. 记录推送日志
"""

import os
import sys
import time
import traceback
from datetime import datetime

import pandas as pd

# 确保项目根目录在 sys.path 中
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, PROJECT_ROOT)

from app.config import settings
from app.models.database import init_db, get_session_factory
from app.models.stock import StockDividendData, PushLog
from app.services.fetcher import (
    fetch_a_spot_with_fallback,
    fetch_dividend_summary,
    fetch_dividend_history_batch,
    fetch_year_end_prices_batch,
)
from app.services.calculator import (
    calc_dividend_yield,
    calc_consecutive_payout_years,
    calc_annual_dividend_from_records,
    calc_year_dividend_from_records,
    calc_ytd_return,
    get_last_ex_dividend_date,
    get_dividend_detail_text,
    get_dividend_price_impact,
)
from app.services.screener import apply_filters, group_by_industry, get_summary_stats
from app.services.ai_stock_picker import get_ai_config, pick_stocks_with_ai
from app.services.settings_service import load_settings_from_db
from app.reports.excel_report import generate_excel
from app.reports.pdf_report import generate_pdf
from app.services.mailer import send_report
from app.utils.logger import logger


AUTO_DETAIL_NETWORK_LIMIT = int(os.getenv("DIVIDEND_AUTO_DETAIL_NETWORK_LIMIT", "20"))
AI_DETAIL_NETWORK_LIMIT = int(os.getenv("DIVIDEND_AI_DETAIL_NETWORK_LIMIT", "20"))
YEAR_END_NETWORK_LIMIT = int(os.getenv("DIVIDEND_YEAR_END_NETWORK_LIMIT", "0"))
YTD_FILTER_YEAR_END_NETWORK_LIMIT = int(os.getenv("DIVIDEND_YTD_YEAR_END_NETWORK_LIMIT", "80"))


def _build_stock_records(
    spot_df: pd.DataFrame,
    dividend_map: dict,
    source: str,
    summary_map: dict | None = None,
    dividend_event_year: int | None = None,
) -> list[dict]:
    """Turn行情+分红数据 into normalized report records."""
    records = []
    total = len(spot_df)

    for i, (_, row) in enumerate(spot_df.iterrows(), 1):
        code = str(row.get("代码", "")).strip()
        name = str(row.get("名称", "")).strip()
        latest_price = float(row.get("最新价", 0) or 0)

        if not code or latest_price <= 0:
            continue

        div_records = dividend_map.get(code)
        has_div_records = div_records is not None and not div_records.empty
        summary = (summary_map or {}).get(code, {})
        annual_div = (
            calc_annual_dividend_from_records(div_records)
            if dividend_event_year is None and has_div_records
            else 0
        )
        if dividend_event_year is not None and has_div_records:
            annual_div = calc_year_dividend_from_records(div_records, dividend_event_year)
        payout_years = (
            calc_consecutive_payout_years(
                div_records,
                dividend_event_year,
            )
            if has_div_records else 0
        )
        ex_date = get_last_ex_dividend_date(div_records, dividend_event_year) if has_div_records else ""
        div_detail = get_dividend_detail_text(div_records, dividend_event_year) if has_div_records else ""

        if annual_div <= 0 and summary and not has_div_records:
            annual_div = float(summary.get("annual_dividend", 0) or 0)
        if payout_years <= 0 and summary and not has_div_records:
            payout_years = int(summary.get("dividend_count", 0) or 0)
        if not div_detail and annual_div > 0:
            div_detail = f"10派{annual_div * 10:g}元"

        div_yield = calc_dividend_yield(annual_div, latest_price)
        ytd_ret = calc_ytd_return(latest_price, float(row.get("60日涨跌幅", 0) or 0))
        div_impact = get_dividend_price_impact(ytd_ret, div_yield)

        market_cap = float(row.get("总市值", 0) or 0) / 1e8 if row.get("总市值") else 0
        pe_ratio = float(row.get("市盈率-动态", 0) or 0)
        pb_ratio = float(row.get("市净率", 0) or 0)

        records.append({
            "code": code,
            "name": name,
            "industry": str(row.get("行业", "")).strip() if "行业" in spot_df.columns else "",
            "market_cap": round(market_cap, 2),
            "consecutive_years": payout_years,
            "latest_price": latest_price,
            "annual_dividend": round(annual_div, 4),
            "dividend_yield": div_yield,
            "ex_dividend_date": ex_date,
            "year_end_price": float(row.get("year_end_price", 0) or 0),
            "ytd_return": ytd_ret,
            "dividend_price_impact": div_impact,
            "dividend_detail": div_detail,
            "yield_price_4": _yield_price(annual_div, 4),
            "yield_price_5": _yield_price(annual_div, 5),
            "yield_price_6": _yield_price(annual_div, 6),
            "yield_price_7": _yield_price(annual_div, 7),
            "yield_price_8": _yield_price(annual_div, 8),
            "pe_ratio": pe_ratio,
            "pb_ratio": pb_ratio,
            "selection_source": source,
        })

        if i % 500 == 0:
            logger.info(f"  数据处理进度: {i}/{total}")

    return records


def _yield_price(annual_dividend: float, target_yield: float) -> float:
    if annual_dividend is None or annual_dividend <= 0 or target_yield <= 0:
        return 0.0
    return round(annual_dividend / (target_yield / 100), 2)


def _enrich_year_end_metrics(df: pd.DataFrame, year: int, network_limit: int | None = None) -> pd.DataFrame:
    if df.empty:
        return df
    prices = fetch_year_end_prices_batch(df["code"].astype(str).tolist(), year, network_limit=network_limit)
    result = df.copy()
    result["year_end_price"] = result["code"].astype(str).str.zfill(6).map(prices).fillna(0)
    result["ytd_return"] = result.apply(
        lambda row: calc_ytd_return(row.get("latest_price", 0), row.get("year_end_price", 0)),
        axis=1,
    )
    return result


def _prepare_auto_candidates(spot_df: pd.DataFrame, summary_df: pd.DataFrame) -> tuple[pd.DataFrame, dict]:
    """Use cheap market data and dividend summary to reduce detail requests."""
    if spot_df.empty:
        return spot_df, {}

    df = spot_df.copy()
    df["代码"] = df["代码"].astype(str).str.zfill(6)

    summary_map = {}
    if not summary_df.empty:
        summary = summary_df.copy()
        summary["代码"] = summary["代码"].astype(str).str.zfill(6)
        summary["annual_dividend"] = pd.to_numeric(summary.get("年均股息", 0), errors="coerce").fillna(0) / 10
        summary["dividend_count"] = pd.to_numeric(summary.get("分红次数", 0), errors="coerce").fillna(0).astype(int)
        summary_map = {
            row["代码"]: {
                "annual_dividend": float(row["annual_dividend"]),
                "dividend_count": int(row["dividend_count"]),
            }
            for _, row in summary.iterrows()
        }
        df = df.merge(summary[["代码", "annual_dividend", "dividend_count"]], on="代码", how="left")
    else:
        df["annual_dividend"] = 0
        df["dividend_count"] = 0

    df["annual_dividend"] = pd.to_numeric(df["annual_dividend"], errors="coerce").fillna(0)
    df["dividend_count"] = pd.to_numeric(df["dividend_count"], errors="coerce").fillna(0)
    df["最新价"] = pd.to_numeric(df["最新价"], errors="coerce").fillna(0)
    df["总市值"] = pd.to_numeric(df["总市值"], errors="coerce").fillna(0)
    df["市盈率-动态"] = pd.to_numeric(df["市盈率-动态"], errors="coerce").fillna(0)
    df["市净率"] = pd.to_numeric(df["市净率"], errors="coerce").fillna(0)
    df["summary_dividend_yield"] = 0.0
    valid_price = df["最新价"] > 0
    df.loc[valid_price, "summary_dividend_yield"] = (
        df.loc[valid_price, "annual_dividend"] / df.loc[valid_price, "最新价"] * 100
    )

    fs = settings.filter
    before = len(df)
    if fs.exclude_st:
        df = df[~df["名称"].astype(str).str.contains("ST|退", na=False)]
    if fs.min_market_cap and fs.min_market_cap > 0:
        df = df[(df["总市值"] / 1e8) >= fs.min_market_cap]
    if fs.max_market_cap and fs.max_market_cap > 0:
        df = df[(df["总市值"] / 1e8) <= fs.max_market_cap]
    if fs.min_latest_price and fs.min_latest_price > 0:
        df = df[df["最新价"] >= fs.min_latest_price]
    if fs.max_latest_price and fs.max_latest_price > 0:
        df = df[df["最新价"] <= fs.max_latest_price]
    if fs.min_pe_ratio and fs.min_pe_ratio > 0:
        df = df[(df["市盈率-动态"] > 0) & (df["市盈率-动态"] >= fs.min_pe_ratio)]
    if fs.max_pe_ratio and fs.max_pe_ratio > 0:
        df = df[(df["市盈率-动态"] > 0) & (df["市盈率-动态"] <= fs.max_pe_ratio)]
    if fs.min_pb_ratio and fs.min_pb_ratio > 0:
        df = df[(df["市净率"] > 0) & (df["市净率"] >= fs.min_pb_ratio)]
    if fs.max_pb_ratio and fs.max_pb_ratio > 0:
        df = df[(df["市净率"] > 0) & (df["市净率"] <= fs.max_pb_ratio)]
    if fs.min_consecutive_years and fs.min_consecutive_years > 0:
        df = df[df["dividend_count"] >= fs.min_consecutive_years]
    if fs.max_consecutive_years and fs.max_consecutive_years > 0:
        df = df[df["dividend_count"] <= fs.max_consecutive_years]
    if fs.min_annual_dividend and fs.min_annual_dividend > 0:
        df = df[df["annual_dividend"] >= fs.min_annual_dividend]
    if fs.max_annual_dividend and fs.max_annual_dividend > 0:
        df = df[df["annual_dividend"] <= fs.max_annual_dividend]
    if fs.min_dividend_yield and fs.min_dividend_yield > 0:
        # Use the cheap summary yield as a prefilter, with a small cushion so
        # borderline stocks still get verified by detailed dividend records.
        df = df[df["summary_dividend_yield"] >= max(0, fs.min_dividend_yield - 0.25)]
    if fs.max_dividend_yield and fs.max_dividend_yield > 0:
        df = df[df["summary_dividend_yield"] <= fs.max_dividend_yield + 0.25]

    df = df.sort_values(["summary_dividend_yield", "dividend_count", "总市值"], ascending=[False, False, False])

    logger.info(f"自动池候选预筛: {before} → {len(df)} 只")
    return df.drop(columns=["annual_dividend", "dividend_count", "summary_dividend_yield"], errors="ignore"), summary_map


def _prepare_ai_candidates(
    spot_df: pd.DataFrame,
    summary_df: pd.DataFrame,
    candidate_limit: int,
) -> tuple[pd.DataFrame, dict]:
    """Build a broad candidate pool for AI selection."""
    if spot_df.empty:
        return spot_df, {}

    df = spot_df.copy()
    df["代码"] = df["代码"].astype(str).str.zfill(6)

    summary_map = {}
    if not summary_df.empty:
        summary = summary_df.copy()
        summary["代码"] = summary["代码"].astype(str).str.zfill(6)
        summary["annual_dividend"] = pd.to_numeric(summary.get("年均股息", 0), errors="coerce").fillna(0) / 10
        summary["dividend_count"] = pd.to_numeric(summary.get("分红次数", 0), errors="coerce").fillna(0).astype(int)
        summary_map = {
            row["代码"]: {
                "annual_dividend": float(row["annual_dividend"]),
                "dividend_count": int(row["dividend_count"]),
            }
            for _, row in summary.iterrows()
        }
        df = df.merge(summary[["代码", "annual_dividend", "dividend_count"]], on="代码", how="left")
    else:
        df["annual_dividend"] = 0
        df["dividend_count"] = 0

    df["annual_dividend"] = pd.to_numeric(df["annual_dividend"], errors="coerce").fillna(0)
    df["dividend_count"] = pd.to_numeric(df["dividend_count"], errors="coerce").fillna(0)
    df["最新价"] = pd.to_numeric(df["最新价"], errors="coerce").fillna(0)
    df["总市值"] = pd.to_numeric(df["总市值"], errors="coerce").fillna(0)

    before = len(df)
    df = df[df["最新价"] > 0]
    df = df[df["annual_dividend"] > 0]
    df = df[df["dividend_count"] > 0]
    if settings.filter.exclude_st:
        df = df[~df["名称"].astype(str).str.contains("ST|退", na=False)]

    df = df.sort_values(["dividend_count", "总市值"], ascending=[False, False])

    logger.info(f"AI候选池预筛: {before} → {len(df)} 只 (发送给AI前再按真实指标截取 {candidate_limit} 只)")
    return df.drop(columns=["annual_dividend", "dividend_count"], errors="ignore"), summary_map


def run_daily_job(push_log_id: int | None = None):
    """执行每日完整流水线"""
    start_time = time.time()
    today = datetime.now().strftime("%Y-%m-%d")
    report_date = datetime.now().strftime("%Y.%m.%d")
    dividend_event_year = datetime.now().year - 1
    year_end_price_year = dividend_event_year

    logger.info("=" * 60)
    logger.info(f"Dividend Notifier 每日任务启动: {today}")
    logger.info("=" * 60)

    # 找到触发器创建的 running 记录并更新，不新建第二条
    session_factory = get_session_factory()
    with session_factory() as db:
        push_log = db.get(PushLog, push_log_id) if push_log_id else None
        if push_log is None:
            push_log = db.query(PushLog).filter(
                PushLog.date == today,
                PushLog.status == "running"
            ).order_by(PushLog.created_at.desc()).first()
    if push_log is None:
        push_log = PushLog(date=today, status="running")

    try:
        # === Step 1: 初始化数据库 ===
        logger.info("[1/7] 初始化数据库...")
        init_db()
        load_settings_from_db()

        # === 选股模式判断 ===
        from app.services.watchlist_service import get_selection_mode, get_watchlist_codes
        mode = get_selection_mode()
        logger.info(f"选股模式: {mode}")

        manual_codes = get_watchlist_codes()
        auto_df = pd.DataFrame()
        manual_df = pd.DataFrame()
        ai_df = pd.DataFrame()
        ai_config = get_ai_config() if mode == "ai" else None
        if mode == "ai" and (not ai_config.api_url or not ai_config.model):
            raise RuntimeError("请先在 AI选股 中填写 API URL 和模型名称")

        # === Step 2-5: 根据模式构建独立股票池 ===
        if mode in ("filter", "both", "ai"):
            logger.info("[2/7] 自动池: 获取全量 A 股行情...")
            spot_df = fetch_a_spot_with_fallback()
            if spot_df.empty:
                raise RuntimeError("自动池未获取到任何行情数据")

            logger.info("[3/7] 自动池: 获取分红概要并预筛候选...")
            summary_df = fetch_dividend_summary()
            if mode == "ai":
                candidate_df, summary_map = _prepare_ai_candidates(
                    spot_df,
                    summary_df,
                    ai_config.candidate_limit,
                )
            else:
                candidate_df, summary_map = _prepare_auto_candidates(spot_df, summary_df)
            if candidate_df.empty:
                raise RuntimeError("候选池预筛后没有股票，请检查筛选条件或 AI 候选池配置")

            if mode == "ai":
                detail_limit = AI_DETAIL_NETWORK_LIMIT
            else:
                detail_limit = AUTO_DETAIL_NETWORK_LIMIT
            logger.info(f"[3/7] 自动池: 获取候选分红明细（未缓存网络上限 {detail_limit} 只）...")
            dividend_map = fetch_dividend_history_batch(candidate_df["代码"].tolist(), network_limit=detail_limit)

            logger.info("[4/7] 自动池: 计算衍生指标...")
            all_stocks_df = pd.DataFrame(_build_stock_records(
                candidate_df,
                dividend_map,
                "auto",
                summary_map,
                dividend_event_year,
            ))
            logger.info(f"自动池基础数据完成: {len(all_stocks_df)} 只")

            if mode == "ai":
                logger.info("[5/7] AI选股: 调用模型选择股票...")
                selected_codes, ai_reason = pick_stocks_with_ai(all_stocks_df, ai_config)
                order_map = {code: idx for idx, code in enumerate(selected_codes)}
                ai_df = all_stocks_df[all_stocks_df["code"].astype(str).isin(selected_codes)].copy()
                ai_df.loc[:, "selection_source"] = "ai"
                ai_df.loc[:, "_ai_order"] = ai_df["code"].map(order_map)
                ai_df = ai_df.sort_values("_ai_order").drop(columns=["_ai_order"])
                if ai_reason:
                    logger.info(f"AI选股理由: {ai_reason}")
                logger.info(f"AI选股结果: {len(ai_df)} 只")
            else:
                logger.info("[5/7] 自动池: 按条件筛选...")
                if settings.filter.min_ytd_return is not None or settings.filter.max_ytd_return is not None:
                    logger.info(f"筛选包含YTD范围，先补充 {year_end_price_year} 年末价（未缓存网络上限 {YTD_FILTER_YEAR_END_NETWORK_LIMIT} 只）...")
                    all_stocks_df = _enrich_year_end_metrics(
                        all_stocks_df,
                        year_end_price_year,
                        network_limit=YTD_FILTER_YEAR_END_NETWORK_LIMIT,
                    )
                auto_df = apply_filters(all_stocks_df)
                auto_df.loc[:, "selection_source"] = "auto"
                logger.info(f"自动池筛选结果: {len(auto_df)} 只")

        if mode in ("manual", "both"):
            if not manual_codes:
                logger.warning("手动池为空")
            else:
                logger.info("[2/7] 手动池: 获取自选股行情...")
                from app.services.fetcher import fetch_stocks_by_codes
                manual_spot_df = fetch_stocks_by_codes(manual_codes)
                if manual_spot_df.empty:
                    raise RuntimeError(f"手动池无法获取 {len(manual_codes)} 只股票的数据")

                logger.info("[3/7] 手动池: 获取分红历史...")
                manual_dividend_map = fetch_dividend_history_batch(manual_spot_df["代码"].tolist())

                logger.info("[4/7] 手动池: 计算衍生指标...")
                manual_df = pd.DataFrame(_build_stock_records(
                    manual_spot_df,
                    manual_dividend_map,
                    "manual",
                    dividend_event_year=dividend_event_year,
                ))
                manual_df.loc[:, "selection_source"] = "manual"
                logger.info(f"手动池结果: {len(manual_df)} 只")

        if mode == "manual":
            filtered_df = manual_df
        elif mode == "ai":
            filtered_df = ai_df
        elif mode == "both":
            if not auto_df.empty and not manual_df.empty:
                auto_codes = set(auto_df["code"].astype(str))
                duplicate_codes = sorted(set(manual_df["code"].astype(str)) & auto_codes)
                if duplicate_codes:
                    logger.info(f"混合模式: 手动池中 {len(duplicate_codes)} 只已在自动池，自动结果优先: {','.join(duplicate_codes)}")
                    manual_df = manual_df[~manual_df["code"].astype(str).isin(auto_codes)]
            filtered_df = pd.concat([auto_df, manual_df], ignore_index=True)
        else:
            filtered_df = auto_df

        if filtered_df.empty:
            logger.warning("当前筛选条件没有匹配股票，将清空当天旧结果并生成空报表")

        logger.info(f"补充 {year_end_price_year} 年末价与今年涨跌（优先缓存，未缓存网络上限 {YEAR_END_NETWORK_LIMIT} 只）...")
        filtered_df = _enrich_year_end_metrics(filtered_df, year_end_price_year, network_limit=YEAR_END_NETWORK_LIMIT)

        logger.info(f"最终股票池: {len(filtered_df)} 只 (mode={mode})")
        grouped = group_by_industry(filtered_df)
        stats = get_summary_stats(filtered_df)

        # === Step 6: 写入数据库 ===
        logger.info("[6/7] 写入 SQLite...")
        session_factory = get_session_factory()
        with session_factory() as db:
            db.query(StockDividendData).filter(StockDividendData.date == today).delete()
            for _, stock in filtered_df.iterrows():
                values = {
                    "code": stock["code"],
                    "name": stock["name"],
                    "industry": stock.get("industry", ""),
                    "market_cap": stock.get("market_cap", 0),
                    "consecutive_years": stock.get("consecutive_years", 0),
                    "latest_price": stock.get("latest_price", 0),
                    "annual_dividend": stock.get("annual_dividend", 0),
                    "dividend_yield": stock.get("dividend_yield", 0),
                    "ex_dividend_date": stock.get("ex_dividend_date", ""),
                    "year_end_price": stock.get("year_end_price", 0),
                    "ytd_return": stock.get("ytd_return", 0),
                    "dividend_price_impact": stock.get("dividend_price_impact", ""),
                    "dividend_detail": stock.get("dividend_detail", ""),
                    "selection_source": stock.get("selection_source", "auto"),
                    "date": today,
                }
                db.add(StockDividendData(**values))
            db.commit()
        logger.info(f"已写入 {len(filtered_df)} 条记录到数据库")

        # === Step 7: 生成报表 + 发送邮件 ===
        logger.info("[7/7] 生成报表 + 发送邮件...")
        output_formats = settings.output.output_format.lower()

        xlsx_path = ""
        pdf_path = ""

        if "xlsx" in output_formats:
            xlsx_path = generate_excel(grouped, report_date=report_date)

        if "pdf" in output_formats:
            pdf_path = generate_pdf(grouped, report_date=report_date)

        # 发送邮件 (邮箱没配也继续)
        mail_configured = bool(
            settings.mail.username and settings.mail.password
            and settings.mail.recipients
            and "your_email" not in settings.mail.username
            and "user1@example" not in (settings.mail.recipients[0] if settings.mail.recipients else "")
        )
        mail_sent = False
        if mail_configured:
            mail_sent = send_report(
                xlsx_path=xlsx_path,
                pdf_path=pdf_path,
                report_date=report_date,
                stock_count=stats["total_stocks"],
                industry_count=stats["total_industries"],
                avg_dividend_yield=stats["avg_dividend_yield"],
                top_industries=stats["top_5_industries"],
            )
        else:
            logger.info("邮件未配置，跳过发送（报表已生成，可在网页查看）")

        # 记录日志
        elapsed = int((time.time() - start_time) * 1000)
        # 报表生成成功就算成功，邮件只是附加
        push_log.status = "success"
        push_log.stock_count = stats["total_stocks"]
        push_log.recipients = str(settings.mail.recipients)
        push_log.xlsx_path = xlsx_path
        push_log.pdf_path = pdf_path
        push_log.duration_ms = elapsed

        logger.info(f"✅ 每日任务完成! 耗时 {elapsed}ms, 覆盖 {stats['total_stocks']} 只股票")

    except Exception as e:
        elapsed = int((time.time() - start_time) * 1000)
        error_detail = traceback.format_exc()
        logger.error(f"❌ 每日任务失败: {e}\n{error_detail}")

        push_log.status = "failed"
        push_log.error_msg = str(e)[:500]
        push_log.duration_ms = elapsed

    finally:
        # 更新推送日志。后台触发时按 push_log_id 精确更新，避免残留 running 锁。
        try:
            session_factory = get_session_factory()
            with session_factory() as db:
                target = None
                if push_log_id:
                    target = db.get(PushLog, push_log_id)
                if target is None and getattr(push_log, "id", None):
                    target = db.get(PushLog, push_log.id)

                if target is None:
                    db.add(push_log)
                else:
                    target.status = push_log.status
                    target.stock_count = push_log.stock_count
                    target.recipients = push_log.recipients
                    target.xlsx_path = push_log.xlsx_path
                    target.pdf_path = push_log.pdf_path
                    target.error_msg = push_log.error_msg
                    target.duration_ms = push_log.duration_ms
                db.commit()
        except Exception as log_err:
            logger.error(f"写入推送日志失败: {log_err}")


if __name__ == "__main__":
    run_daily_job()
