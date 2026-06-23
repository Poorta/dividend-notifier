"""
AI 选股服务。

把本地已经计算好的候选股票指标交给 OpenAI-compatible Chat Completions API，
要求模型只返回股票代码，再由系统校验代码是否存在于候选池。
"""

import json
import re
from dataclasses import dataclass
from typing import Optional

import pandas as pd
import requests
from sqlalchemy.orm import Session

from app.models.database import get_session_factory
from app.models.stock import AppSettings
from app.utils.logger import logger


DEFAULT_AI_PROMPT = """你是A股红利策略选股助手。
请从候选股票中选择更适合长期收息的标的，优先考虑：
1. 股息率较高且连续高息年数稳定；
2. 市值不要太小，避免流动性和财务风险过高；
3. PE/PB 不要明显异常；
4. 分红记录清晰，避免只因股价暴跌造成的虚高股息率。

只返回 JSON，格式为：
{"codes":["600000","601398"],"reason":"一句话概括选择逻辑"}
不要返回候选池之外的代码。"""


@dataclass
class AiPickerConfig:
    api_url: str
    api_key: str
    model: str
    prompt: str
    top_n: int
    candidate_limit: int


def get_ai_config(db: Optional[Session] = None) -> AiPickerConfig:
    close_db = False
    if db is None:
        db = get_session_factory()()
        close_db = True
    try:
        row = db.query(AppSettings).filter(AppSettings.id == 1).first()
        prompt = (row.ai_prompt or "").strip() if row else ""
        return AiPickerConfig(
            api_url=(row.ai_api_url or "").strip() if row else "",
            api_key=(row.ai_api_key or "").strip() if row else "",
            model=(row.ai_model or "").strip() if row else "",
            prompt=prompt or DEFAULT_AI_PROMPT,
            top_n=max(1, min(int(row.ai_top_n or 30), 200)) if row else 30,
            candidate_limit=max(20, min(int(row.ai_candidate_limit or 250), 800)) if row else 250,
        )
    finally:
        if close_db:
            db.close()


def pick_stocks_with_ai(candidates: pd.DataFrame, config: AiPickerConfig) -> tuple[list[str], str]:
    """
    调用 AI 从候选池中选择股票代码。

    Returns:
        (validated_codes, reason)
    """
    if candidates is None or candidates.empty:
        raise RuntimeError("AI 选股候选池为空")
    if not config.api_url:
        raise RuntimeError("请先填写 AI API URL")
    if not config.model:
        raise RuntimeError("请先填写 AI 模型名称")

    df = _format_candidates(candidates, config.candidate_limit)
    valid_codes = set(df["code"].astype(str).str.zfill(6))
    candidate_text = df.to_csv(index=False)

    payload = {
        "model": config.model,
        "messages": [
            {
                "role": "system",
                "content": "你只能基于用户给出的候选股票表选股。输出必须是可解析 JSON。",
            },
            {
                "role": "user",
                "content": (
                    f"{config.prompt}\n\n"
                    f"最多选择 {config.top_n} 只股票。\n"
                    "候选股票 CSV 字段说明：code/name/industry/market_cap/latest_price/"
                    "annual_dividend/dividend_yield/consecutive_years/pe_ratio/pb_ratio/"
                    "ex_dividend_date/dividend_detail。\n\n"
                    f"{candidate_text}"
                ),
            },
        ],
        "temperature": 0.1,
    }

    headers = {"Content-Type": "application/json"}
    if config.api_key:
        headers["Authorization"] = f"Bearer {config.api_key}"

    url = _normalize_chat_url(config.api_url)
    logger.info(f"AI选股: 调用模型 {config.model}, 候选 {len(df)} 只, 目标最多 {config.top_n} 只")
    resp = requests.post(url, headers=headers, json=payload, timeout=90)
    resp.raise_for_status()
    data = resp.json()
    content = _extract_message_content(data)
    codes, reason = _parse_ai_codes(content)

    selected = []
    seen = set()
    for code in codes:
        code = str(code).strip().zfill(6)
        if code in valid_codes and code not in seen:
            selected.append(code)
            seen.add(code)
        if len(selected) >= config.top_n:
            break

    if not selected:
        raise RuntimeError("AI 未返回有效候选代码，请检查提示词或模型输出")

    logger.info(f"AI选股完成: 返回 {len(selected)} 只")
    return selected, reason


def _format_candidates(candidates: pd.DataFrame, limit: int) -> pd.DataFrame:
    cols = [
        "code", "name", "industry", "market_cap", "latest_price",
        "annual_dividend", "dividend_yield", "consecutive_years",
        "pe_ratio", "pb_ratio", "ex_dividend_date", "dividend_detail",
    ]
    df = candidates.copy()
    for col in cols:
        if col not in df.columns:
            df[col] = ""
    df["code"] = df["code"].astype(str).str.zfill(6)
    sort_cols = [c for c in ["dividend_yield", "consecutive_years", "market_cap"] if c in df.columns]
    if sort_cols:
        df = df.sort_values(sort_cols, ascending=[False] * len(sort_cols))
    return df[cols].head(limit)


def _normalize_chat_url(api_url: str) -> str:
    url = api_url.strip().rstrip("/")
    if url.endswith("/chat/completions"):
        return url
    if url.endswith("/v1"):
        return f"{url}/chat/completions"
    return f"{url}/chat/completions"


def _extract_message_content(data: dict) -> str:
    try:
        return data["choices"][0]["message"]["content"] or ""
    except (KeyError, IndexError, TypeError):
        raise RuntimeError("AI API 响应格式不符合 Chat Completions")


def _parse_ai_codes(content: str) -> tuple[list[str], str]:
    text = (content or "").strip()
    json_text = _find_json_object(text)
    if json_text:
        try:
            data = json.loads(json_text)
            raw_codes = data.get("codes") or data.get("stock_codes") or data.get("selected_codes") or []
            if isinstance(raw_codes, list):
                return [str(c) for c in raw_codes], str(data.get("reason", "") or "")
        except json.JSONDecodeError:
            pass

    codes = re.findall(r"\b\d{6}\b", text)
    return codes, ""


def _find_json_object(text: str) -> str:
    start = text.find("{")
    end = text.rfind("}")
    if start >= 0 and end > start:
        return text[start:end + 1]
    return ""
