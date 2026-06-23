"""
配置管理模块

从 .env 文件加载所有用户可配置参数，
通过 Settings 单例全局访问。
"""

import os
from dataclasses import dataclass, field
from typing import Optional

from dotenv import load_dotenv

from app.paths import database_path, output_dir

# 加载 .env 到 os.environ
load_dotenv()


def _get_float(key: str, default: Optional[float] = None) -> Optional[float]:
    val = os.getenv(key, "").strip()
    if val == "":
        return default
    try:
        return float(val)
    except ValueError:
        return default


def _get_int(key: str, default: Optional[int] = None) -> Optional[int]:
    val = os.getenv(key, "").strip()
    if val == "":
        return default
    try:
        return int(val)
    except ValueError:
        return default


def _get_bool(key: str, default: bool = False) -> bool:
    val = os.getenv(key, "").strip().lower()
    if val in ("1", "true", "yes"):
        return True
    if val in ("0", "false", "no"):
        return False
    return default


def _get_str(key: str, default: str = "") -> str:
    return os.getenv(key, default).strip()


def _get_list(key: str, default: Optional[list] = None) -> list:
    val = os.getenv(key, "").strip()
    if val == "":
        return default or []
    return [item.strip() for item in val.split(",") if item.strip()]


@dataclass
class MailSettings:
    """邮件配置"""
    username: str = ""
    password: str = ""
    host: str = "smtp.qq.com"
    port: int = 465
    recipients: list = field(default_factory=list)


@dataclass
class FilterSettings:
    """筛选阈值 — 全部可选，None 表示不限制"""
    min_consecutive_years: Optional[int] = 3
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
    exclude_st: bool = True
    exclude_new_listing_days: Optional[int] = 365


@dataclass
class ColorSettings:
    """颜色编码阈值"""
    div_yield_red: float = 5.0        # >= 此值标红
    div_yield_green: float = 3.0       # <  此值标绿
    ytd_red: float = 0.0               # >= 此值标红
    ytd_green: float = -5.0            # <  此值标绿
    consecutive_red: int = 10          # >= 此值标红
    consecutive_green: int = 5         # <  此值标绿


@dataclass
class OutputSettings:
    """输出配置"""
    output_dir: str = "./output"
    output_format: str = "xlsx,pdf"    # xlsx, pdf, both
    pdf_orientation: str = "landscape"
    pdf_page_size: str = "A4"
    pdf_font_path: str = ""


@dataclass
class Settings:
    """全局配置单例"""
    mail: MailSettings = field(default_factory=MailSettings)
    filter: FilterSettings = field(default_factory=FilterSettings)
    color: ColorSettings = field(default_factory=ColorSettings)
    output: OutputSettings = field(default_factory=OutputSettings)
    send_hour: int = 8
    send_minute: int = 30
    log_level: str = "INFO"
    http_proxy: str = ""
    https_proxy: str = ""

    # 数据库路径
    @property
    def db_path(self) -> str:
        return database_path()


def load_settings() -> Settings:
    """从环境变量加载全部配置"""
    return Settings(
        mail=MailSettings(
            username=_get_str("MAIL_USERNAME"),
            password=_get_str("MAIL_PASSWORD"),
            host=_get_str("MAIL_HOST", "smtp.qq.com"),
            port=_get_int("MAIL_PORT", 465) or 465,
            recipients=_get_list("RECIPIENTS"),
        ),
        filter=FilterSettings(
            min_consecutive_years=_get_int("MIN_CONSECUTIVE_YEARS", 3),
            max_consecutive_years=_get_int("MAX_CONSECUTIVE_YEARS"),
            min_market_cap=_get_float("MIN_MARKET_CAP"),
            max_market_cap=_get_float("MAX_MARKET_CAP"),
            min_dividend_yield=_get_float("MIN_DIVIDEND_YIELD"),
            max_dividend_yield=_get_float("MAX_DIVIDEND_YIELD"),
            min_pe_ratio=_get_float("MIN_PE_RATIO"),
            max_pe_ratio=_get_float("MAX_PE_RATIO"),
            min_pb_ratio=_get_float("MIN_PB_RATIO"),
            max_pb_ratio=_get_float("MAX_PB_RATIO"),
            min_latest_price=_get_float("MIN_LATEST_PRICE"),
            max_latest_price=_get_float("MAX_LATEST_PRICE"),
            min_annual_dividend=_get_float("MIN_ANNUAL_DIVIDEND"),
            max_annual_dividend=_get_float("MAX_ANNUAL_DIVIDEND"),
            min_ytd_return=_get_float("MIN_YTD_RETURN"),
            max_ytd_return=_get_float("MAX_YTD_RETURN"),
            exclude_st=_get_bool("EXCLUDE_ST", True),
            exclude_new_listing_days=_get_int("EXCLUDE_NEW_LISTING_DAYS", 365),
        ),
        color=ColorSettings(
            div_yield_red=_get_float("COLOR_DIV_YIELD_RED", 5.0),
            div_yield_green=_get_float("COLOR_DIV_YIELD_GREEN", 3.0),
            ytd_red=_get_float("COLOR_YTD_RED", 0.0),
            ytd_green=_get_float("COLOR_YTD_GREEN", -5.0),
            consecutive_red=_get_int("COLOR_CONSECUTIVE_RED", 10),
            consecutive_green=_get_int("COLOR_CONSECUTIVE_GREEN", 5),
        ),
        output=OutputSettings(
            output_dir=_get_str("OUTPUT_DIR", output_dir()),
            output_format=_get_str("OUTPUT_FORMAT", "xlsx,pdf"),
            pdf_orientation=_get_str("PDF_PAGE_ORIENTATION", "landscape"),
            pdf_page_size=_get_str("PDF_PAGE_SIZE", "A4"),
            pdf_font_path=_get_str("PDF_FONT_PATH", ""),
        ),
        send_hour=_get_int("SEND_HOUR", 8),
        send_minute=_get_int("SEND_MINUTE", 30),
        log_level=_get_str("LOG_LEVEL", "INFO"),
        http_proxy=_get_str("HTTP_PROXY"),
        https_proxy=_get_str("HTTPS_PROXY"),
    )


# 全局单例
settings = load_settings()
