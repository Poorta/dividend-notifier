"""
衍生指标计算模块

根据原始行情和分红数据，计算 13 列核心指标中的衍生字段:
- 股息率 = 年度现金分红 / 最新价 × 100
- 连续高息年限 (从最近一年往回数)
- YTD 涨跌幅 (年初至今)
- 分红明细文本
"""

from datetime import datetime, timedelta

import pandas as pd

from app.utils.logger import logger


def calc_dividend_yield(cash_dividend: float, latest_price: float) -> float:
    """
    计算当期股息率。

    公式: 股息率 = 每股现金分红 / 最新价 × 100

    Args:
        cash_dividend: 每股现金分红(元)
        latest_price: 最新收盘价

    Returns:
        股息率 (%)，异常时返回 0
    """
    if latest_price is None or latest_price <= 0:
        return 0.0
    if cash_dividend is None or cash_dividend <= 0:
        return 0.0
    return round(cash_dividend / latest_price * 100, 2)


def calc_consecutive_years(dividend_records: pd.DataFrame) -> int:
    """
    计算连续派现年限。

    从最近一年开始，逐年往前检查是否有分红记录，
    直到遇到第一个没有分红的年份为止。

    Args:
        dividend_records: 分红历史 DataFrame，
            需包含 '年份' 或可从 '除权除息日' 提取年份

    Returns:
        连续分红年数
    """
    if dividend_records is None or dividend_records.empty:
        return 0

    # 提取分红年份
    years = set()
    date_col = None

    if "除权除息日" in dividend_records.columns:
        date_col = "除权除息日"
    elif "公告日期" in dividend_records.columns:
        date_col = "公告日期"
    else:
        return 0

    for _, row in dividend_records.iterrows():
        val = row.get(date_col)
        if pd.isna(val) or str(val).strip() == "":
            continue
        try:
            year = int(str(val)[:4])
            years.add(year)
        except (ValueError, IndexError):
            continue

    if not years:
        return 0

    sorted_years = sorted(years, reverse=True)

    # 从最近一年往回数连续年数
    consecutive = 1
    for i in range(len(sorted_years) - 1):
        if sorted_years[i] - sorted_years[i + 1] == 1:
            consecutive += 1
        else:
            break

    return consecutive


def calc_consecutive_high_yield_years(
    dividend_records: pd.DataFrame,
    latest_price: float,
    min_dividend_yield: float,
    start_year: int | None = None,
) -> int:
    """
    计算连续高息年数。

    从最近一个有现金分红的年份往前数；每一年现金分红合计 / 当前股价
    都达到 min_dividend_yield 才算连续。这里用当前股价折算，口径稳定、
    可复现，也避免逐只拉多年历史收盘价造成刷新极慢。
    """
    if dividend_records is None or dividend_records.empty:
        return 0
    if latest_price is None or latest_price <= 0:
        return 0

    yearly_dividends = _annual_dividends_by_year(dividend_records, include_zero_years=True)
    if not yearly_dividends:
        return 0

    threshold = float(min_dividend_yield or 0)
    consecutive = 0
    expected_year = start_year or (datetime.now().year - 1)
    while expected_year in yearly_dividends:
        div_yield = calc_dividend_yield(yearly_dividends[expected_year], latest_price)
        if div_yield < threshold:
            break
        consecutive += 1
        expected_year -= 1

    return consecutive


def calc_consecutive_payout_years(
    dividend_records: pd.DataFrame,
    start_year: int | None = None,
) -> int:
    """计算连续现金分红年数，不要求每年都达到高股息率。"""
    if dividend_records is None or dividend_records.empty:
        return 0

    yearly_dividends = _annual_dividends_by_year(dividend_records, include_zero_years=True)
    if not yearly_dividends:
        return 0

    consecutive = 0
    expected_year = start_year or (datetime.now().year - 1)
    while expected_year in yearly_dividends:
        if yearly_dividends[expected_year] <= 0:
            break
        consecutive += 1
        expected_year -= 1
    return consecutive


def _annual_dividends_by_year(
    dividend_records: pd.DataFrame,
    include_zero_years: bool = False,
) -> dict[int, float]:
    """Return {fiscal-ish year: cash dividend per share}, aggregating rows per year."""
    if dividend_records is None or dividend_records.empty:
        return {}

    yearly = {}
    for _, row in dividend_records.iterrows():
        year = _infer_dividend_year(row)
        if year is None:
            continue
        dividend = _cash_dividend_per_share(row)
        if dividend > 0 and not _is_effective_cash_event(row):
            continue
        if dividend <= 0 and not include_zero_years:
            continue
        yearly[year] = yearly.get(year, 0.0) + dividend

    return yearly


def calc_ttm_dividend_from_records(dividend_records: pd.DataFrame, as_of: datetime | None = None) -> float:
    """
    计算近12个月每股现金分红。

    使用除权除息日；如果还处于预案阶段没有除权日，则用公告日期纳入。
    这样可以避免多年不分配的公司继续拿很久以前的分红冒充当前股息率，
    也能覆盖一年多次分红的公司。
    """
    if dividend_records is None or dividend_records.empty:
        return 0.0

    as_of = as_of or datetime.now()
    start = as_of - timedelta(days=365)
    total = 0.0
    for _, row in dividend_records.iterrows():
        cash = _cash_dividend_per_share(row)
        if cash <= 0:
            continue
        event_date = _dividend_event_date(row)
        if event_date is None:
            continue
        if start.date() <= event_date.date() <= as_of.date():
            total += cash

    return round(total, 4)


def calc_year_dividend_from_records(dividend_records: pd.DataFrame, event_year: int | None = None) -> float:
    """
    计算指定财年的每股现金分红合计。

    A股“2025年分红”通常由 2025 下半年的中期分红和 2026 上半年的
    年度分红组成，因此按财年窗口聚合：YYYY-07-01 至 YYYY+1-06-30。
    还没有除权日的预案不计入，避免把未实施分红提前年化。
    """
    if dividend_records is None or dividend_records.empty:
        return 0.0

    event_year = event_year or (datetime.now().year - 1)
    total = 0.0
    for _, row in dividend_records.iterrows():
        year = _infer_dividend_year(row)
        if year != event_year:
            continue
        if not _is_effective_cash_event(row):
            continue
        total += _cash_dividend_per_share(row)
    return round(total, 4)


def calc_annual_dividend_from_records(dividend_records: pd.DataFrame) -> float:
    """
    从分红历史中提取上年财年每股现金分红合计。

    Args:
        dividend_records: 分红历史 DataFrame (stock_history_dividend_detail 输出)

    Returns:
        每股分红金额(元)
    """
    return calc_year_dividend_from_records(dividend_records, datetime.now().year - 1)


def calc_ytd_return(latest_price: float, year_start_price: float) -> float:
    """
    计算年初至今涨跌幅。

    公式: YTD = (最新价 - 年初价) / 年初价 × 100

    Args:
        latest_price: 最新收盘价
        year_start_price: 年初(01-01 前一个交易日)收盘价

    Returns:
        YTD (%)，异常时返回 0
    """
    if year_start_price is None or year_start_price <= 0:
        return 0.0
    if latest_price is None or latest_price <= 0:
        return 0.0
    return round((latest_price - year_start_price) / year_start_price * 100, 2)


def get_last_ex_dividend_date(dividend_records: pd.DataFrame, event_year: int | None = None) -> str:
    """
    获取最近一次除权除息日。

    Args:
        dividend_records: 分红历史 DataFrame

    Returns:
        除权除息日字符串 (YYYY-MM-DD)，无数据返回空字符串
    """
    if dividend_records is None or dividend_records.empty:
        return ""

    event_year = event_year or (datetime.now().year - 1)
    dated = []
    for _, row in dividend_records.iterrows():
        if _cash_dividend_per_share(row) <= 0:
            continue
        if _infer_dividend_year(row) != event_year:
            continue
        if "除权除息日" not in row.index:
            continue
        raw_ex_date = pd.to_datetime(row.get("除权除息日"), errors="coerce")
        if pd.isna(raw_ex_date):
            continue
        event_date = _dividend_event_date(row)
        if event_date is not None:
            dated.append((event_date, row))

    if not dated:
        return ""

    event_date, row = sorted(dated, key=lambda item: item[0], reverse=True)[0]
    return event_date.strftime("%Y-%m-%d")


def get_dividend_detail_text(dividend_records: pd.DataFrame, event_year: int | None = None) -> str:
    """
    生成分红明细文本 (送股/转增/派息)。

    格式: "10派X元" 或 "10送X转X派X"

    Args:
        dividend_records: 分红历史 DataFrame

    Returns:
        分红明细文本
    """
    if dividend_records is None or dividend_records.empty:
        return ""

    event_year = event_year or (datetime.now().year - 1)
    rows = []
    for _, row in dividend_records.iterrows():
        if _infer_dividend_year(row) != event_year:
            continue
        event_date = _dividend_event_date(row)
        if event_date is None:
            continue
        if _cash_dividend_per_share(row) <= 0:
            continue
        if not _is_effective_cash_event(row):
            continue
        rows.append((event_date, row))

    if not rows:
        return ""

    parts = []
    for _, latest in sorted(rows, key=lambda item: item[0], reverse=True)[:4]:
        text = _dividend_row_text(latest)
        progress = str(latest.get("进度", "") or "").strip()
        if text and progress and progress != "实施":
            text = f"{text}({progress})"
        if text:
            parts.append(text)

    return "+".join(parts) if parts else ""


def _dividend_row_text(row) -> str:
    parts = []

    cash = _cash_dividend_per_share(row)
    if cash > 0:
        parts.append(f"10派{cash * 10:g}元")

    # 送股
    for col in ["送股总比例", "送股"]:
        if col in row.index and not pd.isna(row[col]):
            try:
                val = float(row[col])
                if val > 0:
                    parts.append(f"10送{int(val * 10)}股")
                break
            except (ValueError, TypeError):
                pass

    # 转增
    for col in ["转增总比例", "转增"]:
        if col in row.index and not pd.isna(row[col]):
            try:
                val = float(row[col])
                if val > 0:
                    parts.append(f"10转{int(val * 10)}股")
                break
            except (ValueError, TypeError):
                pass

    return "/".join(parts) if parts else ""


def _cash_dividend_per_share(row) -> float:
    for col in ["每股派息(税前)", "派息"]:
        if col not in row.index:
            continue
        raw = row.get(col)
        if pd.isna(raw) or str(raw).strip() == "":
            return 0.0
        try:
            value = float(raw)
        except (ValueError, TypeError):
            return 0.0
        if col == "派息":
            value = value / 10
        return max(value, 0.0)
    return 0.0


def _is_effective_cash_event(row) -> bool:
    """Only count implemented dividends or rows with a concrete ex-dividend date."""
    if _cash_dividend_per_share(row) <= 0:
        return False
    if "除权除息日" in row.index:
        ex_date = pd.to_datetime(row.get("除权除息日"), errors="coerce")
        if not pd.isna(ex_date):
            return True
    progress = str(row.get("进度", "") or "").strip()
    return progress == "实施"


def _dividend_event_date(row) -> datetime | None:
    for col in ["除权除息日", "公告日期"]:
        if col not in row.index:
            continue
        value = pd.to_datetime(row.get(col), errors="coerce")
        if not pd.isna(value):
            return value.to_pydatetime()
    return None


def _infer_dividend_year(row) -> int | None:
    """Infer fiscal dividend year from announcement date."""
    for col in ["报告期", "年份", "年度"]:
        if col in row.index and not pd.isna(row.get(col)):
            text = str(row.get(col))
            try:
                return int(text[:4])
            except ValueError:
                pass

    announce = None
    if "公告日期" in row.index:
        announce = pd.to_datetime(row.get("公告日期"), errors="coerce")
    if announce is None or pd.isna(announce):
        event_date = _dividend_event_date(row)
        if event_date is None:
            return None
        announce = pd.Timestamp(event_date)

    year = int(announce.year)
    if int(announce.month) <= 7:
        return year - 1
    return year


def get_dividend_price_impact(ytd_return: float, dividend_yield: float) -> str:
    """
    分析股息率对股价的影响（除权后填权情况）。

    简单判断：YTD 为正且股息率高 → "填权强势"
             YTD 为负且股息率高 → "贴权/承压"

    Args:
        ytd_return: YTD 涨跌幅 (%)
        dividend_yield: 股息率 (%)

    Returns:
        影响分析文本
    """
    if ytd_return > 5:
        return "填权强势 ↑"
    elif ytd_return > 0:
        return "小幅填权 ↗"
    elif ytd_return > -5:
        return "窄幅震荡 →"
    else:
        return "贴权承压 ↓"
