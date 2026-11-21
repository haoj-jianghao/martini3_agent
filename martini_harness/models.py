"""Chat models through OpenRouter, one per agent node, sharing one request-rate limiter.

The API key is read from OPENROUTER_API_KEY, or from customized_harness/.env (KEY=value lines) if the variable
is not set. Free models have per-minute and per-day request limits, so every model shares one limiter set by
`requests_per_minute`, and the agent middleware retries failed calls and falls back to the next model.
"""
from __future__ import annotations

import os

from langchain_core.rate_limiters import InMemoryRateLimiter
from langchain_openrouter import ChatOpenRouter

from .config import HARNESS_ROOT, HarnessConfig

_LIMITER: InMemoryRateLimiter | None = None


def load_dotenv() -> None:
    path = HARNESS_ROOT / ".env"
    if not path.exists():
        return
    for line in path.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, _, v = line.partition("=")
        k = k.strip().removeprefix("export ").strip()
        os.environ.setdefault(k, v.strip().strip("'\""))


def _limiter(cfg: HarnessConfig) -> InMemoryRateLimiter:
    global _LIMITER
    if _LIMITER is None:
        rpm = float(cfg.raw.get("requests_per_minute", 15))
        _LIMITER = InMemoryRateLimiter(requests_per_second=rpm / 60.0, check_every_n_seconds=0.2, max_bucket_size=1)
    return _LIMITER


def chat_model(cfg: HarnessConfig, model_id: str) -> ChatOpenRouter:
    load_dotenv()
    if not os.environ.get("OPENROUTER_API_KEY"):
        raise RuntimeError("OPENROUTER_API_KEY is not set (export it, or put it in customized_harness/.env)")
    return ChatOpenRouter(model=model_id, temperature=cfg.raw.get("temperature", 0.0),
                          max_tokens=cfg.raw.get("max_tokens", 4096), max_retries=2,
                          # ChatOpenRouter's request_timeout is in milliseconds (SDK timeout_ms)
                          request_timeout=int(cfg.raw.get("request_timeout_s", 180) * 1000), rate_limiter=_limiter(cfg),
                          reasoning=({"effort": cfg.raw["reasoning_effort"]} if cfg.raw.get("reasoning_effort") else None),
                          app_title="martini-harness")


def node_models(cfg: HarnessConfig, node: str) -> tuple[ChatOpenRouter, list[ChatOpenRouter]]:
    """Primary model of a node and its fallbacks (excluding the primary)."""
    primary = cfg.model_for(node)
    return chat_model(cfg, primary), [chat_model(cfg, m) for m in cfg.fallbacks if m != primary]
