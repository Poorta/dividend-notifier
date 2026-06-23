"""
PDF 报表生成模块

使用 ReportLab 生成 A4 横向 PDF 报表。
字体: macOS 系统黑体 (Heiti SC)，自动探测路径。

功能:
- A4 横向排版
- 列宽按页面可用宽度动态分配比例，自适应内容
- 单元格用 Paragraph 包裹，自动换行
- 行高自适应 (由 Paragraph 高度自动撑开)
- 行业分组 + 颜色编码
- 表头每页重复
- 红利税脚注
"""

import os
import platform
from datetime import datetime
from typing import Optional

import pandas as pd
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4, landscape
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import mm
from reportlab.lib.enums import TA_CENTER, TA_LEFT, TA_RIGHT
from reportlab.platypus import (
    SimpleDocTemplate,
    Table,
    TableStyle,
    Paragraph,
    Spacer,
)
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont

from app.config import settings
from app.utils.colors import (
    PDF_RED,
    PDF_GREEN,
    PDF_BLACK,
    PDF_HEADER_BG,
    PDF_HEADER_FG,
    PDF_INDUSTRY_BG,
    PDF_FOOTER_BG,
    get_dividend_yield_color,
    get_ytd_return_color,
    get_consecutive_years_color,
)
from app.utils.logger import logger


# === 字体自动探测 ===

# macOS 系统黑体候选路径 (按优先级)
_MACOS_FONT_CANDIDATES = [
    "/System/Library/Fonts/STHeiti Light.ttc",
    "/System/Library/Fonts/STHeiti Medium.ttc",
    "/System/Library/Fonts/PingFang.ttc",
    "/System/Library/Fonts/Supplemental/Songti.ttc",
    "/System/Library/Fonts/Supplemental/Arial Unicode.ttf",
]

# Windows 候选
_WINDOWS_FONT_CANDIDATES = [
    "C:/Windows/Fonts/simhei.ttf",
    "C:/Windows/Fonts/msyh.ttc",
    "C:/Windows/Fonts/simsun.ttc",
]

# Linux 候选
_LINUX_FONT_CANDIDATES = [
    "/usr/share/fonts/truetype/droid/DroidSansFallbackFull.ttf",
    "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc",
]


def _find_system_font() -> Optional[str]:
    """自动探测系统中可用的中文字体。"""
    # 用户指定优先级最高
    if settings.output.pdf_font_path:
        if os.path.exists(settings.output.pdf_font_path):
            return settings.output.pdf_font_path
        logger.warning(f"用户指定的字体不存在: {settings.output.pdf_font_path}")

    system = platform.system()
    if system == "Darwin":
        candidates = _MACOS_FONT_CANDIDATES
    elif system == "Windows":
        candidates = _WINDOWS_FONT_CANDIDATES
    else:
        candidates = _LINUX_FONT_CANDIDATES

    for path in candidates:
        if os.path.exists(path):
            logger.info(f"PDF 字体: {path}")
            return path

    logger.warning("未找到系统中文字体，PDF 中文可能无法正常显示")
    return None


# 注册字体 (模块加载时)
_FONT_PATH = _find_system_font()
_FONT_NAME = "CNFont"

if _FONT_PATH:
    try:
        pdfmetrics.registerFont(TTFont(_FONT_NAME, _FONT_PATH))
        _FONT_AVAILABLE = True
    except Exception as e:
        logger.warning(f"字体注册失败: {e}")
        _FONT_AVAILABLE = False
else:
    _FONT_AVAILABLE = False


def _font(size: int = 8, bold: bool = False):
    """创建字体名，兼容无中文字体时的回退"""
    if _FONT_AVAILABLE:
        return (_FONT_NAME, size, "bold" if bold else "normal")
    return ("Helvetica", size, "bold" if bold else "normal")


# === 列定义 (13列 + 宽度比例) ===
# 所有列宽度比例之和 = 1.0，运行时按页面可用宽度等比缩放

PDF_COLUMNS = [
    # (显示名, 数据键名, 宽度比例, 对齐方式)
    ("行业",     "industry",              0.045, TA_LEFT),
    ("名称",     "name",                  0.075, TA_LEFT),
    ("代码",     "code",                  0.055, TA_CENTER),
    ("市值(亿)", "market_cap",            0.060, TA_RIGHT),
    ("派现年",   "consecutive_years",     0.050, TA_CENTER),
    ("最新价",   "latest_price",          0.055, TA_RIGHT),
    ("上年分红", "annual_dividend",       0.060, TA_RIGHT),
    ("股息率%",  "dividend_yield",        0.060, TA_RIGHT),
    ("除权日",   "ex_dividend_date",      0.075, TA_CENTER),
    ("年末价",   "year_end_price",        0.060, TA_RIGHT),
    ("今年涨跌", "ytd_return",            0.060, TA_RIGHT),
    ("4%",       "yield_price_4",         0.045, TA_RIGHT),
    ("5%",       "yield_price_5",         0.045, TA_RIGHT),
    ("6%",       "yield_price_6",         0.045, TA_RIGHT),
    ("7%",       "yield_price_7",         0.045, TA_RIGHT),
    ("8%",       "yield_price_8",         0.045, TA_RIGHT),
    ("分红明细", "dividend_detail",       0.125, TA_LEFT),
]

# 颜色编码列与颜色规则
_COLOR_COLUMNS = {
    "dividend_yield": get_dividend_yield_color,
    "ytd_return": get_ytd_return_color,
    "consecutive_years": get_consecutive_years_color,
}


def _get_report_date() -> str:
    return datetime.now().strftime("%Y.%m.%d")


def _make_para(
    text: str,
    style: ParagraphStyle,
    font_size: int = 6,
    bold: bool = False,
    alignment: int = TA_LEFT,
    text_color: Optional[colors.Color] = None,
    leading: Optional[int] = None,
) -> Paragraph:
    """
    创建一个带自动换行的 Paragraph 单元格。

    关键：用 Paragraph 替代裸字符串，ReportLab 会根据列宽自动换行并撑开行高。
    """
    if not isinstance(text, str):
        text = str(text)

    # 动态创建样式，确保颜色正确
    style_name = f"Cell_{font_size}_{alignment}_{id(text_color)}"
    # 避免重复注册样式 (用 try/except 兜底)
    try:
        _style = ParagraphStyle(
            style_name,
            parent=style,
            fontName=_font(font_size, bold)[0],
            fontSize=font_size,
            leading=leading or font_size + 2,  # 行距
            alignment=alignment,
            textColor=text_color or colors.black,
            wordWrap="CJK",  # CJK 自动换行
        )
    except Exception:
        _style = ParagraphStyle(
            style_name + "_2",
            parent=style,
            fontName=_font(font_size, bold)[0],
            fontSize=font_size,
            leading=leading or font_size + 2,
            alignment=alignment,
            textColor=text_color or colors.black,
            wordWrap="CJK",
        )

    return Paragraph(text, _style)


def generate_pdf(
    grouped_stocks: dict[str, pd.DataFrame],
    output_dir: Optional[str] = None,
    report_date: Optional[str] = None,
) -> str:
    """
    生成 PDF 报表。

    Args:
        grouped_stocks: {行业名: DataFrame} 按行业分组+排序后的数据
        output_dir: 输出目录
        report_date: 报表日期

    Returns:
        生成的 pdf 文件路径
    """
    if output_dir is None:
        output_dir = settings.output.output_dir
    if report_date is None:
        report_date = _get_report_date()

    os.makedirs(output_dir, exist_ok=True)

    filename = f"dividend_report_{report_date.replace('.', '')}.pdf"
    filepath = os.path.join(output_dir, filename)

    # A4 横向尺寸
    page_w, page_h = landscape(A4)  # (842, 595) in points
    left_margin = 10 * mm
    right_margin = 10 * mm
    top_margin = 12 * mm
    bottom_margin = 12 * mm

    # 可用宽度 = 页面宽 - 左右边距
    available_width = page_w - left_margin - right_margin

    # 按比例分配列宽
    col_widths = []
    for _, _, ratio, _ in PDF_COLUMNS:
        col_widths.append(available_width * ratio)

    doc = SimpleDocTemplate(
        filepath,
        pagesize=landscape(A4),
        leftMargin=left_margin,
        rightMargin=right_margin,
        topMargin=top_margin,
        bottomMargin=bottom_margin,
    )

    elements = []
    styles = getSampleStyleSheet()

    # === 标题 ===
    title_text = f"最新养老收息红利股汇总  {report_date}"
    title_para = Paragraph(
        f'<font face="{_FONT_NAME if _FONT_AVAILABLE else "Helvetica"}" size="14" color="#1A3A5C">'
        f'<b>{title_text}</b></font>',
        styles["Title"],
    )
    elements.append(title_para)
    elements.append(Spacer(1, 6 * mm))

    # === 构建表头 (用 Paragraph 包裹) ===
    header_alignment_by_idx = {}
    header_row = []
    for idx, (col_name, _, _, alignment) in enumerate(PDF_COLUMNS):
        header_alignment_by_idx[idx] = alignment
        cell = _make_para(
            col_name,
            styles["Normal"],
            font_size=7,
            bold=True,
            alignment=TA_CENTER,  # 表头统一居中
            text_color=PDF_HEADER_FG,
            leading=9,
        )
        header_row.append(cell)

    table_data = [header_row]

    # === 构建数据行 (每行全部用 Paragraph 包裹，自动换行) ===
    # 预计算颜色列索引
    color_col_indices = {}
    for col_key, color_fn in _COLOR_COLUMNS.items():
        for idx, (_, data_key, _, _) in enumerate(PDF_COLUMNS):
            if data_key == col_key:
                color_col_indices[col_key] = idx
                break

    for industry_name, group_df in grouped_stocks.items():
        # 行业分隔行
        industry_text = f"【{industry_name}】({len(group_df)}只)"
        separator_row = [_make_para(industry_text, styles["Normal"], font_size=7, bold=True, text_color=colors.Color(0.1, 0.23, 0.36), leading=10)]
        # 其余列填空
        for _ in range(len(PDF_COLUMNS) - 1):
            separator_row.append(_make_para("", styles["Normal"], font_size=6))
        table_data.append(separator_row)

        for _, stock in group_df.iterrows():
            row = []
            for idx, (col_name, col_key, _, alignment) in enumerate(PDF_COLUMNS):
                val = stock.get(col_key, "")

                # 格式化数值
                display_text = ""
                if isinstance(val, float):
                    if col_key in ("market_cap", "latest_price", "year_end_price"):
                        display_text = f"{val:.2f}"
                    elif col_key in ("dividend_yield", "ytd_return", "annual_dividend"):
                        display_text = f"{val:.2f}"
                    elif col_key == "consecutive_years":
                        display_text = f"{val:.0f}"
                    else:
                        display_text = f"{val:.2f}" if val != int(val) else f"{val:.0f}"
                else:
                    display_text = str(val) if val else ""

                # 确定该单元格的文字颜色 (颜色编码)
                cell_color = PDF_BLACK
                if col_key in _COLOR_COLUMNS:
                    raw_val = val if isinstance(val, (int, float)) else 0
                    result = _COLOR_COLUMNS[col_key](raw_val or 0)
                    if result == "red":
                        cell_color = PDF_RED
                    elif result == "green":
                        cell_color = PDF_GREEN

                cell = _make_para(
                    display_text,
                    styles["Normal"],
                    font_size=6,
                    alignment=alignment,
                    text_color=cell_color,
                    leading=7,
                )
                row.append(cell)

            table_data.append(row)

    # === 创建 Table ===
    table = Table(table_data, colWidths=col_widths, repeatRows=1)

    # === 表格样式 (Padding 设为最小，高度由 Paragraph 自动撑开) ===
    style_commands = [
        # 表头背景
        ("BACKGROUND", (0, 0), (-1, 0), PDF_HEADER_BG),
        ("ALIGN", (0, 0), (-1, 0), "CENTER"),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        # 网格线
        ("GRID", (0, 0), (-1, -1), 0.5, colors.Color(0.8, 0.8, 0.8)),
        # 内边距 (尽量小，让 Paragraph 自己控制)
        ("TOPPADDING", (0, 0), (-1, -1), 0),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 0),
        ("LEFTPADDING", (0, 0), (-1, -1), 2),
        ("RIGHTPADDING", (0, 0), (-1, -1), 2),
    ]

    # 行业分隔行样式 + 颜色编码
    data_row_idx = 1  # start after header
    for industry_name, group_df in grouped_stocks.items():
        # 行业分隔行
        style_commands.append(("BACKGROUND", (0, data_row_idx), (-1, data_row_idx), PDF_INDUSTRY_BG))
        style_commands.append(("SPAN", (0, data_row_idx), (-1, data_row_idx)))

        data_row_idx += 1

        # 数据行 - 跳过(颜色已在 Paragraph 中设置，此处不额外覆盖)
        data_row_idx += len(group_df)

    table.setStyle(TableStyle(style_commands))
    elements.append(table)

    # === 脚注 ===
    elements.append(Spacer(1, 8 * mm))
    total_stocks = sum(len(g) for g in grouped_stocks.values())
    footnotes = [
        f"覆盖标的: {total_stocks}只  |  行业数: {len(grouped_stocks)}  |  生成时间: {datetime.now().strftime('%Y-%m-%d %H:%M')}",
        "红利税规则：持有期≤1个月(20%) | 1个月~1年(10%) | >1年(免税)",
        "免责声明：本报告仅供信息参考，不构成投资建议。投资有风险，入市需谨慎。",
        "Powered by AkShare | Dividend Notifier (Open Source)",
    ]
    for note in footnotes:
        p = Paragraph(
            f'<font face="{_FONT_NAME if _FONT_AVAILABLE else "Helvetica"}" size="7" color="#888888">'
            f'{note}</font>',
            styles["Normal"],
        )
        elements.append(p)

    doc.build(elements)
    logger.info(f"PDF 报表已生成: {filepath}")
    return filepath
