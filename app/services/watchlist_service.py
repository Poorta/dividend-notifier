"""
自选股 WatchList 服务 — 手动选股模式的 CRUD + 搜索
"""
from datetime import datetime
from typing import Optional

from sqlalchemy.orm import Session

from app.models.database import get_session_factory
from app.models.stock import WatchList, AppSettings, StockDividendData
from app.utils.logger import logger


# ---- WatchList CRUD ----

def get_watchlist(db: Optional[Session] = None) -> list[dict]:
    """获取自选股列表"""
    close_db = False
    if db is None:
        db = _get_session()
        close_db = True
    try:
        rows = db.query(WatchList).order_by(WatchList.added_at.desc()).all()
        return [_row_to_dict(r) for r in rows]
    finally:
        if close_db:
            db.close()


def add_stock(code: str, name: str, db: Optional[Session] = None) -> dict:
    """添加一只股票到自选股列表"""
    close_db = False
    if db is None:
        db = _get_session()
        close_db = True
    try:
        if _is_auto_selected(code, db):
            return {
                "status": "auto_exists",
                "message": f"{code} 已在当前自动筛选结果中，无需重复加入手动池",
            }

        existing = db.query(WatchList).filter(WatchList.code == code).first()
        if existing:
            return {"status": "exists", "message": f"{code} {existing.name} 已在列表中"}

        row = WatchList(
            code=code,
            name=name,
            added_at=datetime.now().strftime("%Y-%m-%d %H:%M"),
        )
        db.add(row)
        db.commit()
        logger.info(f"已添加自选股: {code} {name}")
        return {"status": "ok", "message": f"已添加 {code} {name}"}
    finally:
        if close_db:
            db.close()


def remove_stock(code: str, db: Optional[Session] = None) -> dict:
    """从自选股列表删除一只股票"""
    close_db = False
    if db is None:
        db = _get_session()
        close_db = True
    try:
        row = db.query(WatchList).filter(WatchList.code == code).first()
        if not row:
            return {"status": "not_found", "message": f"未找到 {code}"}
        name = row.name
        db.delete(row)
        db.commit()
        logger.info(f"已移除自选股: {code} {name}")
        return {"status": "ok", "message": f"已移除 {code} {name}"}
    finally:
        if close_db:
            db.close()


def batch_add(codes: list[str], db: Optional[Session] = None) -> dict:
    """批量添加股票代码（仅代码，名称需要在搜索时验证）"""
    close_db = False
    if db is None:
        db = _get_session()
        close_db = True
    try:
        added = 0
        errors = []
        auto_skipped = 0
        for code in codes:
            code = code.strip()
            if not code or len(code) < 6:
                errors.append(f"无效代码: {code}")
                continue
            if _is_auto_selected(code, db):
                auto_skipped += 1
                errors.append(f"{code} 已在自动池")
                continue
            existing = db.query(WatchList).filter(WatchList.code == code).first()
            if existing:
                errors.append(f"{code} 已存在")
                continue
            row = WatchList(
                code=code,
                name=code,  # 名称需要后续通过搜索更新
                added_at=datetime.now().strftime("%Y-%m-%d %H:%M"),
            )
            db.add(row)
            added += 1
        db.commit()
        msg = f"添加 {added}只"
        if auto_skipped:
            msg += f"，{auto_skipped}只已在自动池"
        return {"status": "ok", "message": msg, "added": added, "errors": errors if errors else None, "auto_skipped": auto_skipped}
    finally:
        if close_db:
            db.close()


# ---- 选股模式 ----

def get_selection_mode(db: Optional[Session] = None) -> str:
    """获取当前选股模式"""
    close_db = False
    if db is None:
        db = _get_session()
        close_db = True
    try:
        row = db.query(AppSettings).filter(AppSettings.id == 1).first()
        return row.selection_mode if row and row.selection_mode else "filter"
    finally:
        if close_db:
            db.close()


def set_selection_mode(mode: str) -> dict:
    """设置选股模式"""
    if mode not in ("filter", "manual", "both", "ai"):
        return {"status": "error", "message": f"无效模式: {mode}"}

    db = _get_session()
    try:
        row = db.query(AppSettings).filter(AppSettings.id == 1).first()
        if row is None:
            row = AppSettings(id=1)
            db.add(row)
        row.selection_mode = mode
        db.commit()
        logger.info(f"选股模式已切换为: {mode}")
        return {"status": "ok", "message": f"选股模式已切换为: {mode}", "mode": mode}
    finally:
        db.close()


def get_watchlist_codes(db: Optional[Session] = None) -> list[str]:
    """获取自选股代码列表（纯 codes，给 daily_job 用）"""
    close_db = False
    if db is None:
        db = _get_session()
        close_db = True
    try:
        rows = db.query(WatchList.code).all()
        return [r[0] for r in rows]
    finally:
        if close_db:
            db.close()


def _is_auto_selected(code: str, db: Session) -> bool:
    """In mixed mode, prevent adding a stock that is already in the latest auto pool."""
    mode = get_selection_mode(db)
    if mode != "both":
        return False

    latest_date = db.query(StockDividendData.date).filter(
        StockDividendData.selection_source == "auto"
    ).order_by(StockDividendData.date.desc()).limit(1).scalar()
    if not latest_date:
        return False

    return db.query(StockDividendData.id).filter(
        StockDividendData.date == latest_date,
        StockDividendData.code == code,
        StockDividendData.selection_source == "auto",
    ).first() is not None


# ---- 搜索股票（通过 AkShare） ----

def search_stocks(query: str) -> list[dict]:
    """
    根据名称或代码模糊搜索股票。
    优先用东方财富搜索 API（快） → 回退 AkShare（慢但数据全）。
    始终返回 code + name。
    """
    if not query or len(query) < 1:
        return []

    # 优先：东方财富搜索 API（毫秒级）
    results = _search_eastmoney(query)
    if results:
        return results

    # 回退：AkShare 全量扫描（秒级）
    try:
        import akshare as ak

        df = ak.stock_zh_a_spot_em()
        q = query.upper()
        mask = df["代码"].str.contains(q, na=False) | df["名称"].str.contains(query, na=False)
        matched = df[mask].head(10)

        results = []
        for _, row in matched.iterrows():
            results.append({
                "code": row["代码"],
                "name": row["名称"],
                "latest_price": float(row.get("最新价", 0) or 0),
                "pe_ratio": float(row.get("市盈率-动态", 0) or 0),
                "market_cap": float(row.get("总市值", 0) or 0) / 1e8,
            })
        return results
    except Exception as e:
        logger.warning(f"股票搜索失败 (query={query}): {e}")
        return []


def _search_eastmoney(query: str) -> list[dict]:
    """东方财富搜索 API（快，毫秒级）"""
    try:
        import requests

        url = "https://searchapi.eastmoney.com/api/suggest/get"
        params = {
            "input": query,
            "type": "14",
            "token": "D43BF722C8E33BDC906FB84D85E326E8",
            "count": 10,
        }
        resp = requests.get(url, params=params, timeout=5)
        data = resp.json()
        stocks = data.get("QuotationCodeTable", {}).get("Data", [])
        results = []
        for s in stocks:
            if s.get("MktNum") in ("1", "0"):  # 沪市(1)或深市(0)
                results.append({
                    "code": s["Code"],
                    "name": s["Name"],
                    "latest_price": 0,
                    "pe_ratio": 0,
                    "market_cap": 0,
                })
        return results
    except Exception:
        return []


# ---- Helpers ----

def _get_session() -> Session:
    factory = get_session_factory()
    return factory()


def _row_to_dict(row: WatchList) -> dict:
    return {
        "id": row.id,
        "code": row.code,
        "name": row.name,
        "added_at": row.added_at,
        "notes": row.notes or "",
    }
