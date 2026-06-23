"""
数据库连接与初始化

提供 SQLAlchemy engine + session 工厂 + init_db()。
使用 SQLite，数据库文件路径由 config.settings.db_path 决定。
"""

import os

from sqlalchemy import create_engine
from sqlalchemy import inspect, text
from sqlalchemy.orm import sessionmaker, Session

from app.config import settings
from app.models.stock import Base
from app.utils.logger import logger


# === Engine (单例) ===
_engine = None


def get_engine():
    """获取 SQLAlchemy engine (懒加载)"""
    global _engine
    if _engine is None:
        db_path = settings.db_path
        db_dir = os.path.dirname(db_path)
        os.makedirs(db_dir, exist_ok=True)

        _engine = create_engine(
            f"sqlite:///{db_path}",
            echo=False,
            connect_args={"check_same_thread": False},  # SQLite 多线程安全
        )
        logger.info(f"数据库引擎已创建: {db_path}")
    return _engine


# === Session 工厂 ===
SessionLocal = None


def get_session_factory() -> sessionmaker:
    """获取 Session 工厂 (懒加载)"""
    global SessionLocal
    if SessionLocal is None:
        SessionLocal = sessionmaker(
            autocommit=False,
            autoflush=False,
            bind=get_engine(),
        )
    return SessionLocal


def get_session() -> Session:
    """获取一个新的数据库会话 (用于依赖注入)"""
    factory = get_session_factory()
    db = factory()
    try:
        yield db
    finally:
        db.close()


def init_db():
    """
    初始化数据库 — 自动建表。

    等价于 CREATE TABLE IF NOT EXISTS，可安全重复调用。
    """
    engine = get_engine()
    Base.metadata.create_all(bind=engine)
    _migrate_schema(engine)
    logger.info("数据库表初始化完成")


def _migrate_schema(engine):
    """Apply small additive SQLite migrations for existing local databases."""
    inspector = inspect(engine)
    table_names = inspector.get_table_names()
    if "stock_dividend_data" not in table_names:
        return
    columns = {col["name"] for col in inspector.get_columns("stock_dividend_data")}
    with engine.begin() as conn:
        if "selection_source" not in columns:
            conn.execute(text(
                "ALTER TABLE stock_dividend_data "
                "ADD COLUMN selection_source VARCHAR(20) DEFAULT 'auto'"
            ))
            logger.info("数据库迁移完成: stock_dividend_data.selection_source")

    if "app_settings" not in table_names:
        return
    settings_columns = {col["name"] for col in inspector.get_columns("app_settings")}
    ai_columns = {
        "max_consecutive_years": "INTEGER DEFAULT 0",
        "max_market_cap": "FLOAT DEFAULT 0",
        "max_dividend_yield": "FLOAT DEFAULT 0",
        "min_pe_ratio": "FLOAT DEFAULT 0",
        "min_pb_ratio": "FLOAT DEFAULT 0",
        "min_latest_price": "FLOAT DEFAULT 0",
        "max_latest_price": "FLOAT DEFAULT 0",
        "min_annual_dividend": "FLOAT DEFAULT 0",
        "max_annual_dividend": "FLOAT DEFAULT 0",
        "min_ytd_return": "FLOAT DEFAULT 0",
        "max_ytd_return": "FLOAT DEFAULT 0",
        "ai_api_url": "VARCHAR(500) DEFAULT ''",
        "ai_api_key": "VARCHAR(500) DEFAULT ''",
        "ai_model": "VARCHAR(100) DEFAULT ''",
        "ai_prompt": "TEXT DEFAULT ''",
        "ai_top_n": "INTEGER DEFAULT 30",
        "ai_candidate_limit": "INTEGER DEFAULT 250",
    }
    with engine.begin() as conn:
        for name, ddl in ai_columns.items():
            if name not in settings_columns:
                conn.execute(text(f"ALTER TABLE app_settings ADD COLUMN {name} {ddl}"))
                logger.info(f"数据库迁移完成: app_settings.{name}")


def drop_db():
    """
    删除所有表 (仅用于测试/重置)。

    ⚠️ 此操作不可逆！
    """
    engine = get_engine()
    Base.metadata.drop_all(bind=engine)
    logger.warning("所有数据库表已删除")
