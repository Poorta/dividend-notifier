"""
日志配置模块

标准库 logging，输出到控制台 + 文件。
日志级别从 .env LOG_LEVEL 读取。
"""

import logging
import os
import sys
from datetime import datetime
from logging.handlers import RotatingFileHandler

from app.paths import logs_dir

# 日志格式
CONSOLE_FORMAT = "%(asctime)s  %(levelname)-7s  %(message)s"
FILE_FORMAT = "%(asctime)s  [%(levelname)s]  %(name)s:%(lineno)d  %(message)s"
DATE_FORMAT = "%Y-%m-%d %H:%M:%S"


def setup_logger(
    name: str = "dividend_notifier",
    level: str = "INFO",
    log_dir: str | None = None,
) -> logging.Logger:
    """
    创建并配置 logger。

    Args:
        name: logger 名称
        level: 日志级别 (DEBUG/INFO/WARNING/ERROR)
        log_dir: 日志文件目录

    Returns:
        配置完成的 Logger 实例
    """
    logger = logging.getLogger(name)
    logger.setLevel(getattr(logging, level.upper(), logging.INFO))

    # 避免重复添加 handler
    if logger.handlers:
        return logger

    # === 控制台 handler ===
    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setLevel(logging.DEBUG)
    console_fmt = logging.Formatter(CONSOLE_FORMAT, datefmt=DATE_FORMAT)
    console_handler.setFormatter(console_fmt)
    logger.addHandler(console_handler)

    # === 文件 handler (按天轮转) ===
    if log_dir is None:
        log_dir = logs_dir()
    os.makedirs(log_dir, exist_ok=True)
    today = datetime.now().strftime("%Y-%m-%d")
    log_file = os.path.join(log_dir, f"{today}.log")
    file_handler = RotatingFileHandler(
        log_file,
        maxBytes=10 * 1024 * 1024,  # 10MB
        backupCount=30,
        encoding="utf-8",
    )
    file_handler.setLevel(logging.DEBUG)
    file_fmt = logging.Formatter(FILE_FORMAT, datefmt=DATE_FORMAT)
    file_handler.setFormatter(file_fmt)
    logger.addHandler(file_handler)

    return logger


# 默认 logger 实例
logger = setup_logger()
