"""
筛选与分组模块

根据 .env 中的用户配置阈值，对全量 A 股数据进行:
1. 条件筛选 (连续派现年数/市值/股息率/PE/PB/股价/YTD/ST)
2. 行业分组
3. 组内按股息率降序排列
"""

import pandas as pd

from app.config import settings
from app.utils.logger import logger


def apply_filters(df: pd.DataFrame) -> pd.DataFrame:
    """
    根据用户配置的筛选条件过滤股票列表。

    所有阈值从 settings.filter 读取，None 表示不限制。

    Args:
        df: 全量股票 DataFrame (已包含衍生指标列)

    Returns:
        过滤后的 DataFrame
    """
    total = len(df)
    fs = settings.filter

    df = _apply_range(df, "consecutive_years", fs.min_consecutive_years, fs.max_consecutive_years, "连续派现年")
    df = _apply_range(df, "market_cap", fs.min_market_cap, fs.max_market_cap, "市值(亿)")
    df = _apply_range(df, "dividend_yield", fs.min_dividend_yield, fs.max_dividend_yield, "股息率(%)")
    df = _apply_range(df, "latest_price", fs.min_latest_price, fs.max_latest_price, "股价")
    df = _apply_range(df, "annual_dividend", fs.min_annual_dividend, fs.max_annual_dividend, "上年每股分红")
    df = _apply_range(df, "ytd_return", fs.min_ytd_return, fs.max_ytd_return, "YTD(%)")

    # PE/PB <= 0 通常代表亏损或数据无意义；设置任一 PE/PB 范围时排除。
    if (fs.min_pe_ratio and fs.min_pe_ratio > 0) or (fs.max_pe_ratio and fs.max_pe_ratio > 0):
        before = len(df)
        df = df[df["pe_ratio"].fillna(0) > 0]
        logger.debug(f"  PE 有效值: {before} → {len(df)}")
    df = _apply_range(df, "pe_ratio", fs.min_pe_ratio, fs.max_pe_ratio, "PE")

    if (fs.min_pb_ratio and fs.min_pb_ratio > 0) or (fs.max_pb_ratio and fs.max_pb_ratio > 0):
        before = len(df)
        df = df[df["pb_ratio"].fillna(0) > 0]
        logger.debug(f"  PB 有效值: {before} → {len(df)}")
    df = _apply_range(df, "pb_ratio", fs.min_pb_ratio, fs.max_pb_ratio, "PB")

    # --- 排除 ST / 退市整理类 ---
    if fs.exclude_st:
        before = len(df)
        df = df[~df["name"].str.contains("ST|退", na=False)]
        logger.debug(f"  排除ST/退市: {before} → {len(df)}")

    logger.info(f"筛选完成: {total} → {len(df)} 只股票")
    return df


def _apply_range(
    df: pd.DataFrame,
    column: str,
    min_value,
    max_value,
    label: str,
) -> pd.DataFrame:
    if column not in df.columns:
        return df
    if min_value is not None and min_value != 0:
        before = len(df)
        df = df[df[column].fillna(0) >= min_value]
        logger.debug(f"  {label} >= {min_value}: {before} → {len(df)}")
    if max_value is not None and max_value != 0:
        before = len(df)
        df = df[df[column].fillna(0) <= max_value]
        logger.debug(f"  {label} <= {max_value}: {before} → {len(df)}")
    return df


def group_by_industry(df: pd.DataFrame) -> dict[str, pd.DataFrame]:
    """
    按行业分组，组内按股息率降序排列。

    Args:
        df: 股票 DataFrame (含 industry 列)

    Returns:
        {行业名: DataFrame}，按行业出现频率降序排列
    """
    grouped = {}
    for industry_name, group_df in df.groupby("industry", sort=False):
        if not industry_name or str(industry_name).strip() == "":
            industry_name = "其他"
        # 组内按股息率降序
        group_df = group_df.sort_values("dividend_yield", ascending=False)
        grouped[industry_name] = group_df

    # 按组内股票数量降序排列
    sorted_groups = dict(
        sorted(grouped.items(), key=lambda x: len(x[1]), reverse=True)
    )

    logger.info(f"行业分组: {len(sorted_groups)} 个行业")
    for ind, grp in sorted_groups.items():
        avg_yield = grp["dividend_yield"].mean()
        logger.info(f"  {ind}: {len(grp)}只, 平均股息率 {avg_yield:.2f}%")

    return sorted_groups


def get_summary_stats(df: pd.DataFrame) -> dict:
    """
    生成筛选结果的市场概览统计。

    Returns:
        {
            "total_stocks": int,
            "total_industries": int,
            "avg_dividend_yield": float,
            "max_dividend_yield": float,
            "top_5_industries": [(name, count), ...],
        }
    """
    if df.empty:
        return {
            "total_stocks": 0,
            "total_industries": 0,
            "avg_dividend_yield": 0,
            "max_dividend_yield": 0,
            "top_5_industries": [],
        }

    industry_counts = df["industry"].value_counts()

    return {
        "total_stocks": len(df),
        "total_industries": df["industry"].nunique(),
        "avg_dividend_yield": round(df["dividend_yield"].mean(), 2),
        "max_dividend_yield": round(df["dividend_yield"].max(), 2),
        "top_5_industries": [
            (name, count)
            for name, count in industry_counts.head(5).items()
        ],
    }
