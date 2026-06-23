"""
Task 3 验证: 数据获取 → 衍生指标计算 → 筛选分组

测试完整的数据流水线。
"""

import pandas as pd
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.config import settings
from app.services.fetcher import (
    fetch_a_spot_akshare,
    fetch_dividend_history,
    fetch_dividend_history_batch,
)
from app.services.calculator import (
    calc_dividend_yield,
    calc_consecutive_years,
    calc_consecutive_high_yield_years,
    calc_ttm_dividend_from_records,
    calc_year_dividend_from_records,
    calc_annual_dividend_from_records,
    get_last_ex_dividend_date,
    get_dividend_detail_text,
)
from app.services.screener import apply_filters, group_by_industry


# 测试股票列表 (代表性高股息标的)
TEST_CODES = [
    "601398",  # 工商银行
    "601939",  # 建设银行
    "601288",  # 农业银行
    "600036",  # 招商银行
    "601088",  # 中国神华
    "600900",  # 长江电力
    "600519",  # 贵州茅台
    "000858",  # 五粮液
]


def test_fetch_spot():
    """测试行情获取"""
    print("\n=== 1. 测试行情获取 ===")
    try:
        df = fetch_a_spot_akshare()
        print(f"获取 {len(df)} 只股票行情")
        print(f"列名: {list(df.columns)}")

        # 筛出测试代码
        test_df = df[df["代码"].isin(TEST_CODES)]
        print(f"\n测试股票行情:")
        for _, row in test_df.iterrows():
            print(f"  {row['代码']} {row['名称']}: "
                  f"最新价={row.get('最新价', 'N/A')}, "
                  f"市值={row.get('总市值', 'N/A')}, "
                  f"PE={row.get('市盈率-动态', 'N/A')}")
        return True
    except Exception as e:
        print(f"行情获取失败: {e}")
        return False


def test_dividend():
    """测试分红数据"""
    print("\n=== 2. 测试分红数据 ===")

    for code in TEST_CODES[:4]:  # 只测前4个，避免太慢
        df = fetch_dividend_history(code)
        if df is not None and not df.empty:
            print(f"\n  {code} 分红记录 ({len(df)} 条):")
            print(f"  列名: {list(df.columns)}")
            print(f"  最近一条: {df.iloc[0].to_dict()}")

            # 计算衍生指标
            annual_div = calc_annual_dividend_from_records(df)
            consecutive = calc_consecutive_years(df)
            ex_date = get_last_ex_dividend_date(df)
            detail = get_dividend_detail_text(df)

            print(f"  → 上年/股红利: {annual_div}")
            print(f"  → 连续派现年限(旧口径): {consecutive}")
            print(f"  → 最近除权日: {ex_date}")
            print(f"  → 分红明细: {detail}")
        else:
            print(f"  {code}: 无分红数据")
        import time
        time.sleep(0.5)

    return True


def test_calculator():
    """测试衍生指标计算"""
    print("\n=== 3. 测试衍生指标计算 ===")

    # 模拟数据
    print(f"  股息率 = 0.5 / 6.80 * 100 = {calc_dividend_yield(0.5, 6.80):.2f}%")
    print(f"  股息率 = 0.3 / 4.50 * 100 = {calc_dividend_yield(0.3, 4.50):.2f}%")

    return True


def test_consecutive_high_yield_years():
    """测试连续高息年数按年度股息率断点计算"""
    df = pd.DataFrame([
        {"公告日期": "2025-08-20", "除权除息日": "2025-08-28", "每股派息(税前)": 0.35, "进度": "实施"},
        {"公告日期": "2024-08-20", "除权除息日": "2024-08-28", "每股派息(税前)": 0.28, "进度": "实施"},
        {"公告日期": "2023-08-20", "除权除息日": "2023-08-28", "每股派息(税前)": 0.40, "进度": "实施"},
    ])

    assert calc_consecutive_high_yield_years(df, latest_price=10, min_dividend_yield=3, start_year=2025) == 1
    assert calc_consecutive_high_yield_years(df, latest_price=10, min_dividend_yield=2.5, start_year=2025) == 3


def test_zero_dividend_year_breaks_high_yield_chain():
    """最近年份不分配时，不能拿旧分红冒充当前高股息"""
    df = pd.DataFrame([
        {"公告日期": "2026-04-29", "除权除息日": "", "派息": 0.0, "进度": "不分配"},
        {"公告日期": "2025-04-28", "除权除息日": "", "派息": 0.0, "进度": "不分配"},
        {"公告日期": "2021-07-15", "除权除息日": "2021-07-23", "派息": 3.5, "进度": "实施"},
    ])

    assert calc_annual_dividend_from_records(df) == 0
    assert calc_consecutive_high_yield_years(df, latest_price=1.19, min_dividend_yield=3) == 0


def test_fiscal_year_dividend_sums_implemented_events_only():
    """上年财年分红只合并已实施事件，不提前计入未除权预案"""
    df = pd.DataFrame([
        {"公告日期": "2026-04-29", "除权除息日": "", "派息": 20.0, "进度": "预案"},
        {"公告日期": "2026-01-16", "除权除息日": "2026-01-23", "派息": 10.0, "进度": "实施"},
        {"公告日期": "2025-08-22", "除权除息日": "2025-08-29", "派息": 20.0, "进度": "实施"},
        {"公告日期": "2024-08-22", "除权除息日": "2024-08-28", "派息": 23.8, "进度": "实施"},
    ])

    assert calc_year_dividend_from_records(df, event_year=2025) == 3.0
    assert calc_ttm_dividend_from_records(df, as_of=pd.Timestamp("2026-06-23").to_pydatetime()) == 5.0


def main():
    print("=" * 50)
    print("Task 3 验证: 数据流水线")
    print("=" * 50)

    results = []
    results.append(("行情获取", test_fetch_spot()))
    results.append(("分红数据", test_dividend()))
    results.append(("衍生指标", test_calculator()))

    print("\n" + "=" * 50)
    print("验证结果:")
    all_pass = True
    for name, passed in results:
        status = "✅ PASS" if passed else "❌ FAIL"
        print(f"  {status}  {name}")
        if not passed:
            all_pass = False

    if all_pass:
        print("\n🎉 全部通过! Task 3 验证完成。")
    else:
        print("\n⚠️  部分测试失败，请检查日志。")


if __name__ == "__main__":
    main()
