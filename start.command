#!/bin/bash
# Dividend Notifier — source launcher for macOS.
# Double click this file to create a local virtual environment and open the app.

set -e

cd "$(dirname "$0")"
clear

echo ""
echo "   Dividend Notifier 启动中..."
echo ""

if ! command -v python3 >/dev/null 2>&1; then
  echo "   未找到 python3。请先安装 Python 3.11 或更高版本。"
  echo "   按回车键关闭窗口..."
  read
  exit 1
fi

if [ ! -d ".venv" ]; then
  echo "   正在创建本地 Python 环境..."
  python3 -m venv .venv
fi

PYTHON="$(pwd)/.venv/bin/python"

echo "   正在检查依赖..."
"$PYTHON" -m pip install --upgrade pip >/dev/null
"$PYTHON" -m pip install -r requirements.txt >/dev/null

lsof -ti:8000 | xargs kill -9 2>/dev/null || true

echo ""
echo "   服务启动成功"
echo "   仪表盘:   http://localhost:8000"
echo "   报表中心: http://localhost:8000/reports"
echo "   通知设置: http://localhost:8000/notifications"
echo "   选股设置: http://localhost:8000/stock-pick"
echo ""
echo "   浏览器会自动打开；关闭这个窗口 = 停止服务。"
echo ""

sleep 2
open "http://localhost:8000" 2>/dev/null || true

PYTHONPATH="$(pwd)" "$PYTHON" -m uvicorn app.main:app --host 127.0.0.1 --port 8000

echo ""
echo "   服务已停止。按回车键关闭窗口..."
read
