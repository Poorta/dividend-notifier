"""
数据获取模块

主力数据源: AkShare
兜底数据源: 东方财富 HTTP API

核心职责:
1. 获取全量 A 股实时行情 (代码/名称/最新价/市值/PE/PB/行业)
2. 获取个股历史分红明细 (每股分红/除权日/送转股)
3. 容错: AkShare 失败时自动切换到东方财富 API
"""

import os
from datetime import datetime, timedelta
from contextlib import contextmanager
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Optional

import akshare as ak
import pandas as pd
import requests

from app.config import settings
from app.paths import cache_dir
from app.utils.logger import logger


CACHE_DIR = cache_dir()


PROXY_ENV_KEYS = (
    "HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY", "NO_PROXY",
    "http_proxy", "https_proxy", "all_proxy", "no_proxy",
)


def _configured_proxies() -> dict[str, str] | None:
    """Only use proxies explicitly configured in .env, never inherited GUI env."""
    proxies = {}
    if settings.http_proxy:
        proxies["http"] = settings.http_proxy
    if settings.https_proxy:
        proxies["https"] = settings.https_proxy
    return proxies or None


def _request_get(url: str, **kwargs) -> requests.Response:
    """GET helper that avoids broken system proxy env inherited by GUI apps."""
    session = requests.Session()
    session.trust_env = False
    headers = {
        "User-Agent": (
            "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
            "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0 Safari/537.36"
        ),
        "Accept": "application/json,text/plain,*/*",
        "Referer": "https://quote.eastmoney.com/",
    }
    headers.update(kwargs.pop("headers", {}) or {})
    kwargs["headers"] = headers
    proxies = _configured_proxies()
    if proxies:
        kwargs["proxies"] = proxies
    return session.get(url, **kwargs)


def _cache_file(name: str, date_scoped: bool = True) -> str:
    os.makedirs(CACHE_DIR, exist_ok=True)
    if date_scoped:
        today = datetime.now().strftime("%Y%m%d")
        return os.path.join(CACHE_DIR, f"{name}_{today}.pkl")
    safe_name = name.replace("/", "_").replace(":", "_")
    return os.path.join(CACHE_DIR, f"{safe_name}.pkl")


def _read_cache(name: str, max_age_days: int | None = None, date_scoped: bool = True):
    path = _cache_file(name, date_scoped=date_scoped)
    if not os.path.exists(path):
        return None
    if max_age_days is not None:
        modified = datetime.fromtimestamp(os.path.getmtime(path))
        if datetime.now() - modified > timedelta(days=max_age_days):
            return None
    try:
        return pd.read_pickle(path)
    except Exception:
        return None


def _write_cache(name: str, value, date_scoped: bool = True):
    path = _cache_file(name, date_scoped=date_scoped)
    try:
        pd.to_pickle(value, path)
    except Exception as e:
        logger.debug(f"缓存写入失败 {path}: {e}")


@contextmanager
def _without_proxy_env():
    """Temporarily hide proxy env vars and macOS system proxies from AkShare."""
    old_values = {key: os.environ.get(key) for key in PROXY_ENV_KEYS}
    original_merge = requests.sessions.Session.merge_environment_settings

    def merge_without_proxy(self, url, proxies, stream, verify, cert):
        settings = original_merge(self, url, proxies, stream, verify, cert)
        settings["proxies"] = _configured_proxies() or {}
        return settings

    for key in PROXY_ENV_KEYS:
        os.environ.pop(key, None)
    requests.sessions.Session.merge_environment_settings = merge_without_proxy
    try:
        yield
    finally:
        requests.sessions.Session.merge_environment_settings = original_merge
        for key, value in old_values.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value


# ============================================================
# 主力: AkShare
# ============================================================

def fetch_a_spot_akshare() -> pd.DataFrame:
    """
    通过 AkShare 获取全量 A 股实时行情。

    Returns:
        DataFrame 包含:
        代码, 名称, 最新价, 涨跌幅, 总市值, 市盈率-动态, 市净率, 60日涨跌幅
    """
    logger.info("AkShare: 正在获取全量 A 股行情...")
    try:
        with _without_proxy_env():
            df = ak.stock_zh_a_spot_em()
        logger.info(f"AkShare: 获取到 {len(df)} 只股票行情")
        return df
    except Exception as e:
        logger.error(f"AkShare spot 接口失败: {e}")
        raise


def fetch_dividend_history(code: str) -> Optional[pd.DataFrame]:
    """
    获取单只股票的历史分红记录。

    Args:
        code: 6位股票代码, e.g. "601398"

    Returns:
        DataFrame 包含:
        公告日期, 除权除息日, 每股派息(税前), 转增总比例, 送股总比例
    """
    cached = _read_cache(f"dividend_{code}", max_age_days=45, date_scoped=False)
    if cached is not None:
        return cached

    try:
        with _without_proxy_env():
            try:
                df = ak.stock_history_dividend_detail(
                    symbol=code,
                    indicator="分红",
                    date="",
                )
            except TypeError:
                df = ak.stock_history_dividend_detail(
                    symbol=code,
                    indicator="分红",
                    adjust="",
                )
        if df is None or df.empty:
            return None
        _write_cache(f"dividend_{code}", df, date_scoped=False)
        return df
    except Exception as e:
        logger.debug(f"获取 {code} 分红历史失败: {e}")
        return None


# ============================================================
# 兜底: 东方财富 HTTP API
# ============================================================

EASTMONEY_SPOT_URL = (
    "https://push2.eastmoney.com/api/qt/clist/get"
)

SINA_SPOT_COUNT_URL = (
    "https://vip.stock.finance.sina.com.cn/quotes_service/api/json_v2.php/"
    "Market_Center.getHQNodeStockCount"
)

SINA_SPOT_URL = (
    "https://vip.stock.finance.sina.com.cn/quotes_service/api/json_v2.php/"
    "Market_Center.getHQNodeData"
)


def fetch_a_spot_eastmoney() -> pd.DataFrame:
    """
    兜底: 通过东方财富 HTTP API 获取全量 A 股行情。

    Returns:
        与 AkShare 输出格式一致的 DataFrame
    """
    logger.info("东方财富 API (兜底): 正在获取全量 A 股行情...")
    cached = _read_cache("spot_eastmoney")
    if cached is not None and not cached.empty:
        logger.info(f"东方财富 API: 使用当天缓存 {len(cached)} 只股票")
        return cached

    params = {
        "pn": "1",
        "pz": "10000",
        "po": "1",
        "np": "1",
        "fltt": "2",
        "invt": "2",
        "fid": "f3",
        "fs": "m:0+t:6,m:0+t:80,m:1+t:2,m:1+t:23",
        "fields": "f2,f3,f12,f14,f15,f16,f17,f20,f21,f23,f100,f115",
    }
    try:
        resp = _request_get(EASTMONEY_SPOT_URL, params=params, timeout=30)
        resp.raise_for_status()
        data = resp.json()
        items = data.get("data", {}).get("diff", [])

        records = []
        for item in items:
            records.append({
                "代码": item.get("f12", ""),
                "名称": item.get("f14", ""),
                "最新价": item.get("f2", 0),
                "涨跌幅": item.get("f3", 0),
                "总市值": item.get("f20", 0),
                "市盈率-动态": item.get("f115", 0),
                "市净率": item.get("f23", 0),
                "60日涨跌幅": 0,
                "行业": item.get("f100", ""),
            })

        df = pd.DataFrame(records)
        _write_cache("spot_eastmoney", df)
        logger.info(f"东方财富 API: 获取到 {len(df)} 只股票")
        return df
    except Exception as e:
        logger.error(f"东方财富 API 兜底也失败: {e}")
        raise


def fetch_a_spot_sina() -> pd.DataFrame:
    """
    兜底: 通过新浪行情中心分页获取全量 A 股行情。

    这个接口与 AkShare/东方财富 push2 不是同一个入口，在本机网络下更稳定。
    """
    logger.info("新浪行情 API (兜底): 正在获取全量 A 股行情...")
    cached = _read_cache("spot_sina")
    if cached is not None and not cached.empty:
        logger.info(f"新浪行情 API: 使用当天缓存 {len(cached)} 只股票")
        return cached

    try:
        count_resp = _request_get(
            SINA_SPOT_COUNT_URL,
            params={"node": "hs_a"},
            timeout=15,
            headers={"Referer": "https://finance.sina.com.cn/"},
        )
        count_resp.raise_for_status()
        total = int(str(count_resp.text).strip().strip('"'))

        page_size = 100
        pages = (total + page_size - 1) // page_size

        def fetch_page(page: int) -> list[dict]:
            resp = _request_get(
                SINA_SPOT_URL,
                params={
                    "page": page,
                    "num": page_size,
                    "sort": "symbol",
                    "asc": 1,
                    "node": "hs_a",
                    "symbol": "",
                    "_s_r_a": "page",
                },
                timeout=20,
                headers={"Referer": "https://finance.sina.com.cn/"},
            )
            resp.raise_for_status()
            return resp.json()

        all_items = []
        with ThreadPoolExecutor(max_workers=8) as executor:
            futures = {executor.submit(fetch_page, page): page for page in range(1, pages + 1)}
            for future in as_completed(futures):
                page = futures[future]
                try:
                    all_items.extend(future.result())
                except Exception as e:
                    logger.warning(f"新浪行情第 {page} 页失败: {e}")

        records = []
        for item in all_items:
            code = str(item.get("code", "")).strip()
            latest_price = _safe_float(item.get("trade"))
            if len(code) != 6 or latest_price <= 0:
                continue
            records.append({
                "代码": code,
                "名称": item.get("name", ""),
                "最新价": latest_price,
                "涨跌幅": _safe_float(item.get("changepercent")),
                "总市值": _safe_float(item.get("mktcap")) * 10000,
                "市盈率-动态": _safe_float(item.get("per")),
                "市净率": _safe_float(item.get("pb")),
                "60日涨跌幅": 0,
                "行业": "",
            })

        df = pd.DataFrame(records)
        _write_cache("spot_sina", df)
        logger.info(f"新浪行情 API: 获取到 {len(df)} 只股票")
        return df
    except Exception as e:
        logger.error(f"新浪行情 API 兜底也失败: {e}")
        raise


def fetch_a_spot_with_fallback() -> pd.DataFrame:
    """
    获取全量 A 股行情。优先使用当前网络下更稳定的新浪入口。
    """
    try:
        return enrich_spot_industry(fetch_a_spot_sina())
    except Exception as e:
        logger.warning(f"新浪失败，切换到 AkShare: {e}")
        try:
            return enrich_spot_industry(fetch_a_spot_akshare())
        except Exception as e2:
            logger.warning(f"AkShare 失败，切换到东方财富兜底: {e2}")
            try:
                return fetch_a_spot_eastmoney()
            except Exception as e3:
                logger.error(f"所有数据源均失败: {e3}")
                raise RuntimeError("无法获取 A 股行情数据，请检查网络连接") from e3


def enrich_spot_industry(df: pd.DataFrame) -> pd.DataFrame:
    """Backfill missing industry names without changing the primary quote source."""
    if df is None or df.empty or "代码" not in df.columns:
        return df

    industry_missing = "行业" not in df.columns or df["行业"].fillna("").astype(str).str.strip().eq("").all()
    if not industry_missing:
        return df

    industry_df = _read_cache("spot_eastmoney")
    if industry_df is None or industry_df.empty:
        logger.info("行业回填: 未找到东方财富行情缓存，跳过网络回填以保证刷新速度")
        return df

    if industry_df.empty or "行业" not in industry_df.columns:
        return df

    industry_map = (
        industry_df.assign(代码=industry_df["代码"].astype(str).str.zfill(6))
        .set_index("代码")["行业"]
        .fillna("")
        .astype(str)
        .to_dict()
    )
    result = df.copy()
    result["代码"] = result["代码"].astype(str).str.zfill(6)
    result["行业"] = result["代码"].map(industry_map).fillna("")
    filled = result["行业"].astype(str).str.strip().ne("").sum()
    logger.info(f"行业回填完成: {filled}/{len(result)} 只")
    return result


def fetch_dividend_summary() -> pd.DataFrame:
    """一次性获取全市场历史分红概要，用于自动池快速候选筛选。"""
    logger.info("AkShare: 正在获取全市场分红概要...")
    cached = _read_cache("dividend_summary")
    if cached is not None and not cached.empty:
        logger.info(f"分红概要: 使用当天缓存 {len(cached)} 只")
        return cached

    try:
        with _without_proxy_env():
            df = ak.stock_history_dividend()
        if df is None or df.empty:
            return pd.DataFrame()
        df = df.copy()
        df["代码"] = df["代码"].astype(str).str.zfill(6)
        _write_cache("dividend_summary", df)
        logger.info(f"分红概要获取完成: {len(df)} 只")
        return df
    except Exception as e:
        logger.warning(f"分红概要获取失败: {e}")
        return pd.DataFrame()


def fetch_dividend_history_batch(
    codes: list[str],
    network_limit: int | None = None,
) -> dict[str, pd.DataFrame]:
    """
    批量获取所有股票的分红历史。

    Args:
        codes: 股票代码列表

    Returns:
        {code: DataFrame} 分红历史映射
    """
    dividend_map = {}
    unique_codes = []
    seen = set()
    for code in codes:
        code = str(code).strip().zfill(6)
        if len(code) == 6 and code not in seen:
            seen.add(code)
            unique_codes.append(code)

    total = len(unique_codes)
    failed = 0
    missing_codes = []

    for code in unique_codes:
        cached = _read_cache(f"dividend_{code}", max_age_days=45, date_scoped=False)
        if cached is not None and not cached.empty:
            dividend_map[code] = cached
        else:
            missing_codes.append(code)

    if dividend_map:
        logger.info(f"分红明细缓存命中: {len(dividend_map)}/{total}")

    if network_limit is not None and len(missing_codes) > network_limit:
        skipped = len(missing_codes) - network_limit
        logger.info(f"分红明细未缓存 {len(missing_codes)} 只，本次限量补 {network_limit} 只，跳过 {skipped} 只")
        missing_codes = missing_codes[:network_limit]

    if not missing_codes:
        logger.info(f"分红数据获取完成: 成功 {len(dividend_map)}, 失败 {failed}")
        return dividend_map

    max_workers = min(12, max(1, len(missing_codes)))
    completed = 0
    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        futures = {executor.submit(fetch_dividend_history, code): code for code in missing_codes}
        for future in as_completed(futures):
            code = futures[future]
            try:
                df = future.result()
            except Exception:
                df = None
            if df is not None and not df.empty:
                dividend_map[code] = df
            else:
                failed += 1

            completed += 1
            if completed % 50 == 0 or completed == len(missing_codes):
                logger.info(f"  分红数据进度: {completed}/{len(missing_codes)} (总成功 {len(dividend_map)}/{total}, 失败 {failed})")

    logger.info(f"分红数据获取完成: 成功 {len(dividend_map)}, 失败 {failed}")
    return dividend_map


def fetch_year_end_prices_batch(
    codes: list[str],
    year: int,
    network_limit: int | None = None,
) -> dict[str, float]:
    """Fetch the last trading close around Dec 31 for each stock, with daily cache.

    Historical quote APIs are much slower and less stable than realtime quotes.  The
    caller can cap uncached network fetches so a broad screen does not block refresh.
    """
    prices = {}
    unique_codes = sorted({str(code).zfill(6) for code in codes if str(code).strip()})
    total = len(unique_codes)
    if total == 0:
        return prices

    missing_codes = []
    for code in unique_codes:
        cached = _read_cache(f"year_end_{year}_{code}", date_scoped=False)
        if cached is None:
            missing_codes.append(code)
            continue
        try:
            price = float(cached)
        except (TypeError, ValueError):
            missing_codes.append(code)
            continue
        if price > 0:
            prices[code] = price

    if network_limit is not None and len(missing_codes) > network_limit:
        skipped = len(missing_codes) - network_limit
        logger.info(f"  年末价未缓存 {len(missing_codes)} 只，本次限量补 {network_limit} 只，跳过 {skipped} 只")
        missing_codes = missing_codes[:network_limit]
    if not missing_codes:
        logger.info(f"  年末价缓存命中: {len(prices)}/{total}")
        return prices

    def _tx_symbol(code: str) -> str:
        return f"sh{code}" if code.startswith("6") else f"sz{code}"

    def _last_close(df: pd.DataFrame, close_columns: tuple[str, ...]) -> float:
        if df is None or df.empty:
            return 0.0
        for col in close_columns:
            if col in df.columns:
                series = pd.to_numeric(df[col], errors="coerce").dropna()
                if not series.empty:
                    return float(series.iloc[-1])
        return 0.0

    def fetch_one(code: str) -> tuple[str, float]:
        try:
            with _without_proxy_env():
                df = ak.stock_zh_a_hist(
                    symbol=code,
                    period="daily",
                    start_date=f"{year}1220",
                    end_date=f"{year}1231",
                    adjust="",
                )
            close_price = _last_close(df, ("收盘", "close"))
            if close_price > 0:
                _write_cache(f"year_end_{year}_{code}", close_price, date_scoped=False)
                return code, close_price
        except Exception as e:
            logger.debug(f"东财获取 {code} {year} 年末价失败: {e}")

        try:
            with _without_proxy_env():
                df = ak.stock_zh_a_hist_tx(
                    symbol=_tx_symbol(code),
                    start_date=f"{year}1220",
                    end_date=f"{year}1231",
                    adjust="",
                    timeout=10,
                )
            close_price = _last_close(df, ("close", "收盘"))
            if close_price > 0:
                _write_cache(f"year_end_{year}_{code}", close_price, date_scoped=False)
                return code, close_price
        except Exception as e:
            logger.debug(f"腾讯获取 {code} {year} 年末价失败: {e}")

        return code, 0.0

    max_workers = min(12, max(1, len(missing_codes)))
    completed = 0
    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        futures = {executor.submit(fetch_one, code): code for code in missing_codes}
        for future in as_completed(futures):
            code, price = future.result()
            if price > 0:
                prices[code] = price
            completed += 1
            if completed % 50 == 0 or completed == len(missing_codes):
                logger.info(f"  年末价进度: {completed}/{len(missing_codes)} (总命中 {len(prices)}/{total})")

    return prices


def _safe_float(value) -> float:
    try:
        return float(value or 0)
    except (TypeError, ValueError):
        return 0.0


def fetch_stocks_by_codes(codes: list[str]) -> pd.DataFrame:
    """
    按代码列表获取 A 股实时行情，仅拉取指定股票（跳过全量扫描）。

    Args:
        codes: 6位股票代码列表

    Returns:
        DataFrame，字段与 fetch_a_spot_with_fallback() 一致
    """
    try:
        df = fetch_stocks_by_codes_tencent(codes)
        if df is not None and not df.empty:
            return df
    except Exception as e:
        logger.warning(f"腾讯个股行情失败，回退全量行情: {e}")

    # 最后再拉全量过滤，避免手动模式被全量接口优先拖垮。
    spot_df = fetch_a_spot_with_fallback()
    if spot_df is None or spot_df.empty:
        logger.warning("fetch_stocks_by_codes: 无法获取行情数据")
        return pd.DataFrame()

    filtered = spot_df[spot_df["代码"].isin(codes)].copy()
    logger.info(f"fetch_stocks_by_codes: {len(codes)} 代码 → 匹配 {len(filtered)} 只")
    return filtered


def fetch_stocks_by_codes_tencent(codes: list[str]) -> pd.DataFrame:
    """
    通过腾讯行情接口获取指定股票，适合手动选股模式的小批量请求。
    """
    normalized = []
    for code in codes:
        code = str(code).strip()
        if len(code) != 6:
            continue
        prefix = "sh" if code.startswith(("5", "6", "9")) else "sz"
        normalized.append(prefix + code)

    if not normalized:
        return pd.DataFrame()

    url = "https://qt.gtimg.cn/q=" + ",".join(normalized)
    resp = _request_get(
        url,
        timeout=15,
        headers={
            "Referer": "https://gu.qq.com/",
            "Accept": "*/*",
        },
    )
    resp.raise_for_status()
    text = resp.content.decode("gbk", errors="ignore")

    records = []
    for line in text.splitlines():
        if '="' not in line:
            continue
        payload = line.split('="', 1)[1].rsplit('"', 1)[0]
        fields = payload.split("~")
        if len(fields) < 46 or not fields[2]:
            continue
        try:
            latest_price = float(fields[3] or 0)
            total_market_cap = float(fields[45] or 0) * 1e8
            pe_ratio = float(fields[39] or 0)
            pb_ratio = float(fields[46] or 0) if len(fields) > 46 else 0
        except (TypeError, ValueError):
            continue
        if latest_price <= 0:
            continue
        records.append({
            "代码": fields[2],
            "名称": fields[1],
            "最新价": latest_price,
            "涨跌幅": float(fields[32] or 0),
            "总市值": total_market_cap,
            "市盈率-动态": pe_ratio,
            "市净率": pb_ratio,
            "60日涨跌幅": 0,
            "行业": "",
        })

    df = pd.DataFrame(records)
    logger.info(f"腾讯个股行情: {len(codes)} 代码 → 获取 {len(df)} 只")
    return df
