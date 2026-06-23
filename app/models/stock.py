"""
SQLAlchemy ORM 数据模型

对应 ARCHITECTURE.md §2 的三张核心表：
- StockDividendData: 每日红利股数据快照
- PushLog: 推送执行日志
- WatchList: 用户自选关注列表
"""

from datetime import datetime

from sqlalchemy import Column, Integer, String, Float, Text, UniqueConstraint, Index
from sqlalchemy.orm import DeclarativeBase


class Base(DeclarativeBase):
    pass


class StockDividendData(Base):
    """每日红利股数据快照 — 13列核心指标"""

    __tablename__ = "stock_dividend_data"

    id = Column(Integer, primary_key=True, autoincrement=True)
    code = Column(String(6), nullable=False, comment="股票代码, e.g. 601398")
    name = Column(String(50), nullable=False, comment="股票名称, e.g. 工商银行")
    industry = Column(String(50), default="", comment="所属行业分组")
    market_cap = Column(Float, default=0, comment="总市值(亿元)")
    consecutive_years = Column(Integer, default=0, comment="连续派现年限")
    latest_price = Column(Float, default=0, comment="最新收盘价")
    annual_dividend = Column(Float, default=0, comment="近12个月每股现金分红(元)")
    dividend_yield = Column(Float, default=0, comment="当期股息率(%)")
    ex_dividend_date = Column(String(20), default="", comment="最近除权除息日")
    year_end_price = Column(Float, default=0, comment="年末收盘价(上一自然年12.31)")
    ytd_return = Column(Float, default=0, comment="年初至今涨跌幅(%)")
    dividend_price_impact = Column(String(100), default="", comment="股息率对股价影响")
    dividend_detail = Column(String(200), default="", comment="分红明细(送股/转增/派息)")
    selection_source = Column(String(20), default="auto", comment="来源: auto/manual/ai")
    date = Column(String(10), nullable=False, comment="数据日期 YYYY-MM-DD")
    created_at = Column(
        String(20),
        nullable=False,
        default=lambda: datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        comment="记录创建时间",
    )

    __table_args__ = (
        UniqueConstraint("date", "code", name="uq_date_code"),
        Index("idx_sdd_date", "date"),
        Index("idx_sdd_industry_yield", "industry", "dividend_yield"),
        Index("idx_sdd_code", "code"),
    )

    def __repr__(self):
        return f"<Stock {self.code} {self.name} div_yield={self.dividend_yield}%>"


class PushLog(Base):
    """推送执行日志 — 带状态机"""

    __tablename__ = "push_logs"

    id = Column(Integer, primary_key=True, autoincrement=True)
    date = Column(String(10), nullable=False, comment="推送日期 YYYY-MM-DD")
    stock_count = Column(Integer, default=0, comment="本次覆盖标的数")
    recipients = Column(Text, default="[]", comment="收件人列表 JSON")
    xlsx_path = Column(String(500), default="", comment="xlsx 文件路径")
    pdf_path = Column(String(500), default="", comment="pdf 文件路径")
    status = Column(
        String(20),
        nullable=False,
        default="pending",
        comment="pending | running | success | failed",
    )
    error_msg = Column(Text, default="", comment="失败时的错误信息")
    duration_ms = Column(Integer, default=0, comment="全流程耗时(毫秒)")
    created_at = Column(
        String(20),
        nullable=False,
        default=lambda: datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        comment="记录创建时间",
    )

    __table_args__ = (
        Index("idx_pl_date", "date"),
        Index("idx_pl_status", "status"),
    )

    def __repr__(self):
        return f"<PushLog {self.date} status={self.status} stocks={self.stock_count}>"


class AppSettings(Base):
    """
    用户可配置项 — 单行表 (id=1)，通过 Web 页面读写。

    所有字段对应原 .env 中的用户配置项。
    启动时从 DB 加载，merge 覆盖 .env 默认值。
    """

    __tablename__ = "app_settings"

    id = Column(Integer, primary_key=True, default=1)
    # 邮件
    mail_username = Column(String(200), default="", comment="发件邮箱")
    mail_password = Column(String(200), default="", comment="SMTP 授权码")
    mail_host = Column(String(100), default="smtp.qq.com", comment="SMTP 服务器")
    mail_port = Column(Integer, default=465, comment="SMTP 端口")
    recipients = Column(Text, default="", comment="收件人(逗号分隔)")
    # 推送时间
    send_hour = Column(Integer, default=8, comment="推送小时 0-23")
    send_minute = Column(Integer, default=30, comment="推送分钟 0-59")
    schedule_enabled = Column(Integer, default=0, comment="定时推送开关 1=开 0=关")
    # 筛选阈值
    min_consecutive_years = Column(Integer, default=3, comment="最低连续派现年数")
    max_consecutive_years = Column(Integer, default=0, comment="最高连续派现年数, 0=不限")
    min_market_cap = Column(Float, default=0, comment="最低市值(亿), 0=不限")
    max_market_cap = Column(Float, default=0, comment="最高市值(亿), 0=不限")
    min_dividend_yield = Column(Float, default=0, comment="最低股息率(%), 0=不限")
    max_dividend_yield = Column(Float, default=0, comment="最高股息率(%), 0=不限")
    min_pe_ratio = Column(Float, default=0, comment="最低市盈率, 0=不限")
    max_pe_ratio = Column(Float, default=0, comment="最高市盈率, 0=不限")
    min_pb_ratio = Column(Float, default=0, comment="最低市净率, 0=不限")
    max_pb_ratio = Column(Float, default=0, comment="最高市净率, 0=不限")
    min_latest_price = Column(Float, default=0, comment="最低股价, 0=不限")
    max_latest_price = Column(Float, default=0, comment="最高股价, 0=不限")
    min_annual_dividend = Column(Float, default=0, comment="最低上年每股分红, 0=不限")
    max_annual_dividend = Column(Float, default=0, comment="最高上年每股分红, 0=不限")
    min_ytd_return = Column(Float, default=0, comment="最低YTD涨跌幅, 0=不限")
    max_ytd_return = Column(Float, default=0, comment="最高YTD涨跌幅, 0=不限")
    exclude_st = Column(Integer, default=1, comment="排除ST 1=是")
    exclude_new_listing_days = Column(Integer, default=365, comment="排除上市不足N天")
    selection_mode = Column(String(20), default="filter", comment="选股模式: filter/manual/both/ai")
    # AI 选股
    ai_api_url = Column(String(500), default="", comment="AI Chat Completions API URL")
    ai_api_key = Column(String(500), default="", comment="AI API Key")
    ai_model = Column(String(100), default="", comment="AI 模型名称")
    ai_prompt = Column(Text, default="", comment="AI 选股提示词")
    ai_top_n = Column(Integer, default=30, comment="AI 最多选择股票数")
    ai_candidate_limit = Column(Integer, default=250, comment="发送给 AI 的候选股票数")
    # 颜色阈值
    color_div_yield_red = Column(Float, default=5.0, comment="股息率>=此值红色")
    color_div_yield_green = Column(Float, default=3.0, comment="股息率<此值绿色")
    color_ytd_red = Column(Float, default=0.0, comment="YTD>=此值红色")
    color_ytd_green = Column(Float, default=-5.0, comment="YTD<此值绿色")
    color_consecutive_red = Column(Integer, default=10, comment="连续高息年>=此值红色")
    color_consecutive_green = Column(Integer, default=5, comment="连续高息年<此值绿色")
    # 输出
    output_format = Column(String(20), default="xlsx,pdf", comment="xlsx, pdf, both")
    updated_at = Column(
        String(20),
        default=lambda: datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
    )

    def to_dict(self) -> dict:
        return {c.name: getattr(self, c.name) for c in self.__table__.columns if c.name != "id"}


class WatchList(Base):
    """用户自选关注列表 (P2，本期可选)"""

    __tablename__ = "watch_list"

    id = Column(Integer, primary_key=True, autoincrement=True)
    code = Column(String(6), nullable=False, unique=True, comment="股票代码")
    name = Column(String(50), nullable=False, comment="股票名称")
    added_at = Column(
        String(20),
        nullable=False,
        default=lambda: datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        comment="添加时间",
    )
    notes = Column(String(500), default="", comment="备注")

    def __repr__(self):
        return f"<WatchList {self.code} {self.name}>"
