"""
颜色编码规则模块

中国股市惯例: 涨=红, 跌=绿。
所有阈值从 settings.color 读取，用户可在 .env 中自定义。
"""

from app.config import settings


def get_dividend_yield_color(yield_val: float) -> str:
    """
    股息率颜色编码。

    Returns:
        "red"   — 高于阈值 (正面/看多)
        "green" — 低于阈值 (警示/看空)
        ""      — 中性不染色
    """
    if yield_val <= 0:
        return ""
    cs = settings.color
    if yield_val >= cs.div_yield_red:
        return "red"
    if yield_val < cs.div_yield_green:
        return "green"
    return ""


def get_ytd_return_color(ytd_val: float) -> str:
    """
    YTD 涨跌幅颜色编码。

    Returns:
        "red"   — 正收益 (正面)
        "green" — 跌幅超阈值 (警示)
        ""      — 中性不染色
    """
    cs = settings.color
    if ytd_val >= cs.ytd_red:
        return "red"
    if ytd_val < cs.ytd_green:
        return "green"
    return ""


def get_consecutive_years_color(years: int) -> str:
    """
    连续高息年限颜色编码。

    Returns:
        "red"   — 长期稳定高息 (正面)
        "green" — 高息年限偏短 (警示)
        ""      — 中性不染色
    """
    cs = settings.color
    if years >= cs.consecutive_red:
        return "red"
    if years < cs.consecutive_green:
        return "green"
    return ""


# === Excel 颜色定义 (ARGB 格式) ===
EXCEL_RED = "FF1A1A"       # 红色字体
EXCEL_GREEN = "008000"     # 绿色字体
EXCEL_HEADER_BG = "1A3A5C"  # 表头深蓝背景
EXCEL_HEADER_FG = "FFFFFF"  # 表头白色字体
EXCEL_INDUSTRY_BG = "D6E4F0"  # 行业分隔行浅蓝背景
EXCEL_FOOTER_BG = "F2F2F2"  # 脚注浅灰背景
EXCEL_BORDER_COLOR = "D0D0D0"  # 边框浅灰


# === PDF 颜色定义 (RGB) ===
PDF_RED = (0.9, 0.1, 0.1)
PDF_GREEN = (0.0, 0.5, 0.0)
PDF_BLACK = (0.0, 0.0, 0.0)
PDF_HEADER_BG = (0.1, 0.23, 0.36)
PDF_HEADER_FG = (1.0, 1.0, 1.0)
PDF_INDUSTRY_BG = (0.84, 0.89, 0.94)
PDF_FOOTER_BG = (0.95, 0.95, 0.95)
