"""
邮件推送模块

使用 yagmail 通过 SMTP 发送邮件附件 (xlsx + pdf)。
"""

import os
from typing import Optional

import yagmail

from app.config import settings
from app.utils.logger import logger


def send_report(
    xlsx_path: str,
    pdf_path: str,
    report_date: str,
    stock_count: int,
    industry_count: int,
    avg_dividend_yield: float,
    top_industries: list[tuple[str, int]],
    recipients: Optional[list[str]] = None,
) -> bool:
    """
    发送邮件报表推送。

    Args:
        xlsx_path: Excel 文件路径
        pdf_path: PDF 文件路径
        report_date: 报表日期
        stock_count: 覆盖标的数
        industry_count: 行业数
        avg_dividend_yield: 平均股息率
        top_industries: Top 行业列表 [(name, count), ...]
        recipients: 收件人列表，默认 settings.mail.recipients

    Returns:
        True 发送成功, False 失败
    """
    if recipients is None:
        recipients = settings.mail.recipients

    if not recipients:
        logger.warning("未配置收件人，跳过邮件发送")
        return False

    if not settings.mail.username or not settings.mail.password:
        logger.warning("未配置邮箱账号/密码，跳过邮件发送")
        return False

    # 构建行业分布文本
    industry_text = " | ".join(
        f"{name}({count}只)" for name, count in top_industries[:8]
    )

    # 邮件主题
    subject = f"📊 Dividend Notifier · 养老收息红利股汇总 {report_date}"

    # 邮件正文
    body = f"""今日覆盖高股息标的共 {stock_count} 只，分布在 {industry_count} 个行业。
平均股息率 {avg_dividend_yield}%。

行业分布概况：
{industry_text}

📎 附件 (手机可直接打开查看)：
  · {os.path.basename(xlsx_path)}
  · {os.path.basename(pdf_path)}

⚠️ 免责声明：本报告仅供信息参考，不构成投资建议。投资有风险，入市需谨慎。
持有期≤1个月：红利税20% | 1个月~1年：红利税10% | >1年：免税

Powered by AkShare | Dividend Notifier (Open Source)
"""

    try:
        yag = yagmail.SMTP(
            user=settings.mail.username,
            password=settings.mail.password,
            host=settings.mail.host,
            port=settings.mail.port,
        )

        attachments = []
        if os.path.exists(xlsx_path):
            attachments.append(xlsx_path)
        if os.path.exists(pdf_path):
            attachments.append(pdf_path)

        yag.send(
            to=recipients,
            subject=subject,
            contents=body,
            attachments=attachments,
        )

        logger.info(f"邮件已发送至 {len(recipients)} 位收件人: {recipients}")
        return True

    except Exception as e:
        logger.error(f"邮件发送失败: {e}")
        return False
