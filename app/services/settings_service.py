"""
用户配置读写服务

管理 app_settings 表（单行）的 CRUD。
启动时将 DB 配置 merge 到全局 settings 单例，
Web 页面修改后同步写 DB + 更新运行时配置。
"""

from typing import Optional

from sqlalchemy.orm import Session

from app.config import settings, ColorSettings, FilterSettings, MailSettings, OutputSettings
from app.models.database import get_session_factory
from app.models.stock import AppSettings
from app.utils.logger import logger


def _get_session() -> Session:
    """获取一个新的 DB session"""
    return get_session_factory()()


def init_default_settings(db: Optional[Session] = None) -> AppSettings:
    """
    确保 app_settings 表中存在默认行 (id=1)。
    如果不存在则用 .env 默认值创建。
    """
    close_db = False
    if db is None:
        db = _get_session()
        close_db = True
    try:
        row = db.query(AppSettings).filter(AppSettings.id == 1).first()
        if row is None:
            row = AppSettings(id=1)
            # 从 .env 加载初始默认值
            row.mail_username = settings.mail.username
            row.mail_password = settings.mail.password
            row.mail_host = settings.mail.host
            row.mail_port = settings.mail.port
            row.recipients = ",".join(settings.mail.recipients) if settings.mail.recipients else ""
            row.send_hour = settings.send_hour
            row.send_minute = settings.send_minute
            row.min_consecutive_years = settings.filter.min_consecutive_years or 3
            row.max_consecutive_years = settings.filter.max_consecutive_years or 0
            row.min_market_cap = settings.filter.min_market_cap or 0
            row.max_market_cap = settings.filter.max_market_cap or 0
            row.min_dividend_yield = settings.filter.min_dividend_yield or 0
            row.max_dividend_yield = settings.filter.max_dividend_yield or 0
            row.min_pe_ratio = settings.filter.min_pe_ratio or 0
            row.max_pe_ratio = settings.filter.max_pe_ratio or 0
            row.min_pb_ratio = settings.filter.min_pb_ratio or 0
            row.max_pb_ratio = settings.filter.max_pb_ratio or 0
            row.min_latest_price = settings.filter.min_latest_price or 0
            row.max_latest_price = settings.filter.max_latest_price or 0
            row.min_annual_dividend = settings.filter.min_annual_dividend or 0
            row.max_annual_dividend = settings.filter.max_annual_dividend or 0
            row.min_ytd_return = settings.filter.min_ytd_return or 0
            row.max_ytd_return = settings.filter.max_ytd_return or 0
            row.exclude_st = 1 if settings.filter.exclude_st else 0
            row.exclude_new_listing_days = settings.filter.exclude_new_listing_days or 365
            row.color_div_yield_red = settings.color.div_yield_red
            row.color_div_yield_green = settings.color.div_yield_green
            row.color_ytd_red = settings.color.ytd_red
            row.color_ytd_green = settings.color.ytd_green
            row.color_consecutive_red = settings.color.consecutive_red
            row.color_consecutive_green = settings.color.consecutive_green
            row.output_format = settings.output.output_format
            row.ai_api_url = ""
            row.ai_api_key = ""
            row.ai_model = ""
            row.ai_prompt = ""
            row.ai_top_n = 30
            row.ai_candidate_limit = 250
            db.add(row)
            db.commit()
            logger.info("已创建默认应用配置 (app_settings id=1)")
        return row
    finally:
        if close_db:
            db.close()


def load_settings_from_db(db: Optional[Session] = None):
    """
    从 DB 加载用户配置，merge 覆盖到全局 settings 单例。

    调用时机: FastAPI 启动时。
    """
    close_db = False
    if db is None:
        db = _get_session()
        close_db = True
    try:
        row = db.query(AppSettings).filter(AppSettings.id == 1).first()
        if row is None:
            return
        # 邮件
        if row.mail_username:
            settings.mail.username = row.mail_username
        if row.mail_password:
            settings.mail.password = row.mail_password
        if row.mail_host:
            settings.mail.host = row.mail_host
        settings.mail.port = row.mail_port
        if row.recipients:
            settings.mail.recipients = [r.strip() for r in row.recipients.split(",") if r.strip()]
        # 推送时间
        settings.send_hour = row.send_hour
        settings.send_minute = row.send_minute
        # 筛选
        settings.filter.min_consecutive_years = row.min_consecutive_years
        settings.filter.max_consecutive_years = row.max_consecutive_years if row.max_consecutive_years > 0 else None
        settings.filter.min_market_cap = row.min_market_cap if row.min_market_cap > 0 else None
        settings.filter.max_market_cap = row.max_market_cap if row.max_market_cap > 0 else None
        settings.filter.min_dividend_yield = row.min_dividend_yield if row.min_dividend_yield > 0 else None
        settings.filter.max_dividend_yield = row.max_dividend_yield if row.max_dividend_yield > 0 else None
        settings.filter.min_pe_ratio = row.min_pe_ratio if row.min_pe_ratio > 0 else None
        settings.filter.max_pe_ratio = row.max_pe_ratio if row.max_pe_ratio > 0 else None
        settings.filter.min_pb_ratio = row.min_pb_ratio if row.min_pb_ratio > 0 else None
        settings.filter.max_pb_ratio = row.max_pb_ratio if row.max_pb_ratio > 0 else None
        settings.filter.min_latest_price = row.min_latest_price if row.min_latest_price > 0 else None
        settings.filter.max_latest_price = row.max_latest_price if row.max_latest_price > 0 else None
        settings.filter.min_annual_dividend = row.min_annual_dividend if row.min_annual_dividend > 0 else None
        settings.filter.max_annual_dividend = row.max_annual_dividend if row.max_annual_dividend > 0 else None
        settings.filter.min_ytd_return = row.min_ytd_return if row.min_ytd_return != 0 else None
        settings.filter.max_ytd_return = row.max_ytd_return if row.max_ytd_return != 0 else None
        settings.filter.exclude_st = bool(row.exclude_st)
        settings.filter.exclude_new_listing_days = row.exclude_new_listing_days if row.exclude_new_listing_days > 0 else None
        # 颜色
        settings.color.div_yield_red = row.color_div_yield_red
        settings.color.div_yield_green = row.color_div_yield_green
        settings.color.ytd_red = row.color_ytd_red
        settings.color.ytd_green = row.color_ytd_green
        settings.color.consecutive_red = row.color_consecutive_red
        settings.color.consecutive_green = row.color_consecutive_green
        # 输出
        settings.output.output_format = row.output_format or "xlsx,pdf"
        logger.info("已从 DB 加载用户配置")
    finally:
        if close_db:
            db.close()


def save_settings_to_db(data: dict, db: Optional[Session] = None):
    """
    将 Web 表单提交的配置写入 DB，并同步更新全局 settings。

    Args:
        data: 前端提交的 JSON dict，键名与 AppSettings 列名一致
    """
    close_db = False
    if db is None:
        db = _get_session()
        close_db = True
    try:
        row = db.query(AppSettings).filter(AppSettings.id == 1).first()
        if row is None:
            row = AppSettings(id=1)
            db.add(row)

        # 映射字段: data key → row attribute
        str_fields = [
            "mail_username", "mail_password", "mail_host", "recipients",
            "output_format", "selection_mode",
            "ai_api_url", "ai_api_key", "ai_model", "ai_prompt",
        ]
        int_fields = [
            "mail_port", "send_hour", "send_minute", "schedule_enabled",
            "min_consecutive_years", "max_consecutive_years",
            "exclude_st", "exclude_new_listing_days",
            "color_consecutive_red", "color_consecutive_green",
            "ai_top_n", "ai_candidate_limit",
        ]
        float_fields = [
            "min_market_cap", "max_market_cap",
            "min_dividend_yield", "max_dividend_yield",
            "min_pe_ratio", "max_pe_ratio",
            "min_pb_ratio", "max_pb_ratio",
            "min_latest_price", "max_latest_price",
            "min_annual_dividend", "max_annual_dividend",
            "min_ytd_return", "max_ytd_return",
            "color_div_yield_red", "color_div_yield_green",
            "color_ytd_red", "color_ytd_green",
        ]

        for key in str_fields:
            if key in data:
                setattr(row, key, str(data[key]) if data[key] is not None else "")
        for key in int_fields:
            if key in data and data[key] is not None:
                setattr(row, key, int(data[key]))
        for key in float_fields:
            if key in data and data[key] is not None:
                setattr(row, key, float(data[key]))

        db.commit()
        # 同步到全局 settings
        load_settings_from_db(db)
        logger.info("用户配置已保存到 DB 并同步到运行时")
    finally:
        if close_db:
            db.close()


def get_settings_dict(db: Optional[Session] = None) -> dict:
    """获取当前配置字典 (用于 API 响应)"""
    close_db = False
    if db is None:
        db = _get_session()
        close_db = True
    try:
        row = db.query(AppSettings).filter(AppSettings.id == 1).first()
        if row:
            return row.to_dict()
        # fallback: 从运行时 settings 构造
        return {
            "mail_username": settings.mail.username,
            "mail_password": "",  # 不回显密码
            "mail_host": settings.mail.host,
            "mail_port": settings.mail.port,
            "recipients": ",".join(settings.mail.recipients),
            "send_hour": settings.send_hour,
            "send_minute": settings.send_minute,
            "schedule_enabled": 0,
            "min_consecutive_years": settings.filter.min_consecutive_years or 3,
            "max_consecutive_years": settings.filter.max_consecutive_years or 0,
            "min_market_cap": settings.filter.min_market_cap or 0,
            "max_market_cap": settings.filter.max_market_cap or 0,
            "min_dividend_yield": settings.filter.min_dividend_yield or 0,
            "max_dividend_yield": settings.filter.max_dividend_yield or 0,
            "min_pe_ratio": settings.filter.min_pe_ratio or 0,
            "max_pe_ratio": settings.filter.max_pe_ratio or 0,
            "min_pb_ratio": settings.filter.min_pb_ratio or 0,
            "max_pb_ratio": settings.filter.max_pb_ratio or 0,
            "min_latest_price": settings.filter.min_latest_price or 0,
            "max_latest_price": settings.filter.max_latest_price or 0,
            "min_annual_dividend": settings.filter.min_annual_dividend or 0,
            "max_annual_dividend": settings.filter.max_annual_dividend or 0,
            "min_ytd_return": settings.filter.min_ytd_return or 0,
            "max_ytd_return": settings.filter.max_ytd_return or 0,
            "exclude_st": 1 if settings.filter.exclude_st else 0,
            "exclude_new_listing_days": settings.filter.exclude_new_listing_days or 365,
            "color_div_yield_red": settings.color.div_yield_red,
            "color_div_yield_green": settings.color.div_yield_green,
            "color_ytd_red": settings.color.ytd_red,
            "color_ytd_green": settings.color.ytd_green,
            "color_consecutive_red": settings.color.consecutive_red,
            "color_consecutive_green": settings.color.consecutive_green,
            "output_format": settings.output.output_format,
            "selection_mode": "filter",
            "ai_api_url": "",
            "ai_api_key": "",
            "ai_model": "",
            "ai_prompt": "",
            "ai_top_n": 30,
            "ai_candidate_limit": 250,
        }
    finally:
        if close_db:
            db.close()
