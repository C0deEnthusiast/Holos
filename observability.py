"""
Holos Observability — Agent 0B
Centralizes: structlog setup, Sentry init, ai_calls logging.
Import at app startup: from observability import setup_observability, log_ai_call
"""
import os
import time
import uuid
from typing import Any

import structlog

# ── Structlog setup ──────────────────────────────────────────────
def setup_structlog() -> None:
    structlog.configure(
        processors=[
            structlog.contextvars.merge_contextvars,
            structlog.processors.add_log_level,
            structlog.processors.TimeStamper(fmt="iso"),
            structlog.dev.ConsoleRenderer() if os.getenv("ENV") != "production"
            else structlog.processors.JSONRenderer(),
        ],
        wrapper_class=structlog.make_filtering_bound_logger(
            structlog.stdlib.NAME_TO_LEVEL.get(
                os.getenv("LOG_LEVEL", "INFO").upper(), 20
            )
        ),
        context_class=dict,
        logger_factory=structlog.PrintLoggerFactory(),
    )


def setup_sentry() -> None:
    dsn = os.getenv("SENTRY_DSN")
    if not dsn:
        return
    try:
        import sentry_sdk  # type: ignore[import]
        from sentry_sdk.integrations.flask import FlaskIntegration  # type: ignore[import]
        sentry_sdk.init(
            dsn=dsn,
            integrations=[FlaskIntegration()],
            environment=os.getenv("ENV", "development"),
            traces_sample_rate=0.1,
            profiles_sample_rate=0.1,
            send_default_pii=False,
        )
        structlog.get_logger("holos.observability").info("Sentry initialized")
    except ImportError:
        structlog.get_logger("holos.observability").warning(
            "sentry-sdk not installed — skipping Sentry setup"
        )


def setup_observability() -> None:
    """Call once at app startup."""
    setup_structlog()
    setup_sentry()


# ── ai_calls logger ─────────────────────────────────────────────
log = structlog.get_logger("holos.ai_calls")


def log_ai_call(
    *,
    user_id: str | None,
    scan_id: str | None = None,
    provider: str,
    model_id: str,
    purpose: str,
    input_tokens: int = 0,
    output_tokens: int = 0,
    cached_tokens: int = 0,
    latency_ms: int = 0,
    success: bool = True,
    error_code: str | None = None,
) -> None:
    """
    Write one row to ai_calls + emit structlog event.
    Cost estimate: Gemini Flash ≈ $0.075/M input, $0.30/M output (2025 pricing).
    """
    cost_cents = _estimate_cost_cents(provider, model_id, input_tokens, output_tokens, cached_tokens)

    log.info(
        "ai_call",
        user_id=user_id,
        scan_id=scan_id,
        provider=provider,
        model_id=model_id,
        purpose=purpose,
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        cached_tokens=cached_tokens,
        cost_cents=float(cost_cents),
        latency_ms=latency_ms,
        success=success,
        error_code=error_code,
    )

    try:
        from app import supabase  # lazy import to avoid circular dep
        if supabase:
            supabase.table("ai_calls").insert({
                "id": str(uuid.uuid4()),
                "user_id": user_id,
                "scan_id": scan_id,
                "provider": provider,
                "model_id": model_id,
                "purpose": purpose,
                "input_tokens": input_tokens,
                "output_tokens": output_tokens,
                "cached_tokens": cached_tokens,
                "cost_cents": float(cost_cents),
                "latency_ms": latency_ms,
                "success": success,
                "error_code": error_code,
            }).execute()
    except Exception as e:
        log.warning("ai_calls_insert_failed", error=str(e))


def _estimate_cost_cents(
    provider: str, model_id: str, input_tokens: int, output_tokens: int, cached_tokens: int
) -> float:
    """Rough cost estimate in cents. Update rates monthly."""
    rates: dict[str, tuple[float, float]] = {
        # (input_per_M_cents, output_per_M_cents)
        "gemini-2.5-flash-preview": (0.075 * 100, 0.30 * 100),
        "gemini-2.5-pro": (1.25 * 100, 10.0 * 100),
        "gemini-3-flash-preview": (0.075 * 100, 0.30 * 100),
        "claude-sonnet-4-6": (3.0 * 100, 15.0 * 100),
    }
    key = next((k for k in rates if k in model_id), None)
    if not key:
        return 0.0
    in_rate, out_rate = rates[key]
    return (input_tokens / 1_000_000 * in_rate) + (output_tokens / 1_000_000 * out_rate)


class AICallTimer:
    """Context manager: times an AI call and logs it on exit."""
    def __init__(self, **kwargs: Any) -> None:
        self._kwargs = kwargs
        self._start = 0.0

    def __enter__(self) -> "AICallTimer":
        self._start = time.monotonic()
        return self

    def set(self, **kwargs: Any) -> None:
        self._kwargs.update(kwargs)

    def __exit__(self, exc_type: Any, exc_val: Any, exc_tb: Any) -> None:
        latency_ms = int((time.monotonic() - self._start) * 1000)
        self._kwargs.setdefault("latency_ms", latency_ms)
        self._kwargs.setdefault("success", exc_type is None)
        if exc_type is not None:
            self._kwargs["error_code"] = exc_type.__name__
        log_ai_call(**self._kwargs)
