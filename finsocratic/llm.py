"""Pluggable LLM provider for the FinSocratic research agent.

The agent keeps deterministic computation as the single source of truth for
every number. The language model is used only for reasoning, critical
questioning, hypothesis generation and prose — it never fabricates a figure.

DeepSeek is the default backend, reached through its OpenAI-compatible
``/chat/completions`` endpoint.

Configuration (environment variables, or a ``.env`` file at the project root):

- ``DEEPSEEK_API_KEY``  (required for AI mode)
- ``DEEPSEEK_BASE_URL`` (default ``https://api.deepseek.com``)
- ``DEEPSEEK_MODEL``    (default ``deepseek-chat``; use ``deepseek-reasoner``
  for the heavier red-team / attribution passes)
"""
from __future__ import annotations

import json
import os
import re
from pathlib import Path
from typing import Any

import requests

ROOT = Path(__file__).resolve().parents[1]

DEFAULT_BASE_URL = "https://api.deepseek.com"
DEFAULT_MODEL = "deepseek-chat"
DEFAULT_REASONER_MODEL = "deepseek-reasoner"

_TIMEOUT = 180
_HEADERS = {"Content-Type": "application/json"}


def _load_dotenv() -> None:
    """Load ``.env`` into ``os.environ`` without a third-party dependency."""
    path = ROOT / ".env"
    if not path.is_file():
        return
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        if key and key not in os.environ:
            os.environ[key] = value


def _env(name: str, default: str = "") -> str:
    return os.environ.get(name, default).strip()


def config() -> dict[str, Any]:
    _load_dotenv()
    api_key = _env("DEEPSEEK_API_KEY")
    return {
        "available": bool(api_key),
        "base_url": _env("DEEPSEEK_BASE_URL", DEFAULT_BASE_URL).rstrip("/"),
        "model": _env("DEEPSEEK_MODEL", DEFAULT_MODEL),
        "reasoner_model": _env("DEEPSEEK_REASONER_MODEL", DEFAULT_REASONER_MODEL),
        "provider": "deepseek",
        "configured": bool(api_key),
        "note": "数字由确定性计算生成；模型仅用于推理、质疑与行文，不生成数值。",
    }


def is_available() -> bool:
    return bool(config()["available"])


def status() -> dict[str, Any]:
    return config()


def _post(messages: list[dict[str, str]], *, model: str, temperature: float,
          max_tokens: int, json_mode: bool = False) -> str | None:
    cfg = config()
    if not cfg["available"]:
        return None
    payload: dict[str, Any] = {
        "model": model,
        "messages": messages,
        "temperature": temperature,
        "max_tokens": max_tokens,
        "stream": False,
    }
    if json_mode:
        payload["response_format"] = {"type": "json_object"}
    url = f"{cfg['base_url']}/chat/completions"
    headers = {**_HEADERS, "Authorization": f"Bearer {_env('DEEPSEEK_API_KEY')}"}
    response = requests.post(url, headers=headers, json=payload, timeout=_TIMEOUT)
    response.raise_for_status()
    data = response.json()
    try:
        return data["choices"][0]["message"]["content"]
    except (KeyError, IndexError, TypeError):
        return None


def chat(messages: list[dict[str, str]], *, model: str | None = None,
         temperature: float = 0.2, max_tokens: int = 2000) -> str | None:
    """Return a model completion or ``None`` when no backend is configured."""
    cfg = config()
    return _post(messages, model=model or cfg["model"], temperature=temperature,
                 max_tokens=max_tokens)


def complete(prompt: str, *, model: str | None = None, temperature: float = 0.2,
             max_tokens: int = 2000) -> str | None:
    return chat([{"role": "user", "content": prompt}], model=model,
                temperature=temperature, max_tokens=max_tokens)


def _extract_json(text: str) -> dict[str, Any] | None:
    """Parse a JSON object from a model reply, tolerating surrounding prose."""
    if not text:
        return None
    start = text.find("{")
    end = text.rfind("}")
    if start < 0 or end <= start:
        return None
    candidate = text[start:end + 1]
    try:
        parsed = json.loads(candidate)
    except json.JSONDecodeError:
        # Strip markdown code fences and retry once.
        candidate = re.sub(r"```(?:json)?|```", "", candidate).strip()
        try:
            parsed = json.loads(candidate)
        except json.JSONDecodeError:
            return None
    return parsed if isinstance(parsed, dict) else None


def json_object(prompt: str, *, model: str | None = None, temperature: float = 0.0,
                max_tokens: int = 3000) -> dict[str, Any] | None:
    """Ask the model for a JSON object and parse it robustly.

    ``deepseek-reasoner`` does not accept ``response_format``, so JSON mode is
    disabled for reasoning models; the prompt plus ``_extract_json`` still
    yields a structured object.
    """
    cfg = config()
    model = model or cfg["model"]
    json_mode = "reasoner" not in model
    text = _post(
        [{"role": "system", "content": "只输出一个合法的 JSON 对象，不要输出任何其他文字、解释或 Markdown 代码块。"},
         {"role": "user", "content": prompt}],
        model=model, temperature=temperature,
        max_tokens=max_tokens, json_mode=json_mode,
    )
    return _extract_json(text or "")
