#!/usr/bin/env python3
"""
launchd 配置更新脚本

根据 .env 中的 SEND_HOUR / SEND_MINUTE 自动生成 plist 文件
并注册到 macOS launchd。

用法:
    python scripts/update_launchd.py
"""

import os
import sys
import subprocess

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, PROJECT_ROOT)

from app.config import settings
from app.utils.logger import logger

PLIST_NAME = "com.dividend.notifier"
PLIST_PATH = os.path.expanduser(f"~/Library/LaunchAgents/{PLIST_NAME}.plist")
VENV_PYTHON = sys.executable
DAILY_JOB = os.path.join(PROJECT_ROOT, "scripts", "daily_job.py")
LOGS_DIR = os.path.join(PROJECT_ROOT, "logs")

PLIST_TEMPLATE = """<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN"
  "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>Label</key>
    <string>{label}</string>
    <key>ProgramArguments</key>
    <array>
        <string>{python}</string>
        <string>{script}</string>
    </array>
    <key>StartCalendarInterval</key>
    <dict>
        <key>Hour</key><integer>{hour}</integer>
        <key>Minute</key><integer>{minute}</integer>
    </dict>
    <key>StandardOutPath</key>
    <string>{stdout_log}</string>
    <key>StandardErrorPath</key>
    <string>{stderr_log}</string>
    <key>WorkingDirectory</key>
    <string>{work_dir}</string>
    <key>EnvironmentVariables</key>
    <dict>
        <key>PATH</key>
        <string>/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin</string>
    </dict>
    <key>RunAtLoad</key>
    <false/>
</dict>
</plist>
"""


def update_launchd():
    """生成 plist 并注册到 launchd"""

    # 确保日志目录存在
    os.makedirs(LOGS_DIR, exist_ok=True)

    plist_content = PLIST_TEMPLATE.format(
        label=PLIST_NAME,
        python=VENV_PYTHON,
        script=DAILY_JOB,
        hour=settings.send_hour,
        minute=settings.send_minute,
        stdout_log=os.path.join(LOGS_DIR, "stdout.log"),
        stderr_log=os.path.join(LOGS_DIR, "stderr.log"),
        work_dir=PROJECT_ROOT,
    )

    # 写入 plist
    os.makedirs(os.path.dirname(PLIST_PATH), exist_ok=True)
    with open(PLIST_PATH, "w") as f:
        f.write(plist_content)

    logger.info(f"plist 已写入: {PLIST_PATH}")

    # 先卸载旧的(如果存在)
    subprocess.run(
        ["launchctl", "unload", PLIST_PATH],
        capture_output=True,
    )

    # 加载新的
    result = subprocess.run(
        ["launchctl", "load", PLIST_PATH],
        capture_output=True,
        text=True,
    )

    if result.returncode == 0:
        logger.info("✅ launchd 已注册成功!")
        logger.info(f"   任务将在每天 {settings.send_hour:02d}:{settings.send_minute:02d} 执行")
        logger.info(f"   手动测试: launchctl start {PLIST_NAME}")
    else:
        logger.error(f"launchd 注册失败: {result.stderr}")

    # 验证
    check = subprocess.run(
        ["launchctl", "list", PLIST_NAME],
        capture_output=True,
        text=True,
    )
    logger.info(f"launchctl list 输出:\n{check.stdout}")


if __name__ == "__main__":
    print(f"Dividend Notifier - launchd 配置工具")
    print(f"推送时间: {settings.send_hour:02d}:{settings.send_minute:02d}")
    print(f"Python:    {VENV_PYTHON}")
    print(f"脚本:      {DAILY_JOB}")
    print()
    update_launchd()
