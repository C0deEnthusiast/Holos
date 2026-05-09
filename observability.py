"""
Agent 0B — Observability
observability.py: Centralized structured logging, Sentry integration, AI call instrumentation,
scan cost accumulation, and Flask request timing. This file owns all observability concerns.
No business logic lives here — only measurement and reporting.
"""

import logging
import os
import time
import functools
import threading
from typing import Optional, Callable

import structlog

try:
    import sentry_sdk
    from sentry_sdk.integrations.flask import FlaskIntegration
    SENTRY_AVAILABLE = True
except ImportError:
    SENTRY_AVAILABLE = False

# ── Module-level state ────────────────────────────────────────────────────

_start_time: float = time.time()
_last_scan_cost_cents: float = 0.0
_gemini_status_cache: dict = {"status": "unknown", "last_checked": 0.0}
_GEMINI_STATUS_TTL: float = 300.0  # re-check every 5 minutes

# Thread-local: each worker thread accumulates its own stats independently
_tls = threading.local()

# ── Token pricing: cents per 1M tokens ───────────────────────────────────
# Update these rates when Google changes pricing. All other cost math derives from them.
MODEL_PRICING: dict[str, dict[str, float]] = {
    "gemini-2.5-pro":         {"input": 350.0,  "output": 1050.0},
    "gemini-2.5-flash":       {"input": 7.5,    "output": 30.0},
    "gemini-flash-lite":      {"input": 1.0,    "output": 4.0},
    "gemini-3-flash-preview": {"input": 7.5,    "output": 30.0},  # treat as Flash pricing
}


def _get_pricing(model_name: str) -> dict[str, float]:
    """Partial-match model name against pricing table. Falls back to Flash rates."""
    for key, pricing in MODEL_PRICING.items():
        if key in model_name.lower():
            return pricing
    return MODEL_PRICING["gemini-2.5-flash"]


# ── Logging configuration ─────────────────────────────────────────────────

def configure_logging(debug: bool = True) -> None:
    """
    Initialize structlog. Call once at app startup before any loggers are used.
    DEBUG=True → pretty ConsoleRenderer for human reading.
    DEBUG=False → JSON lines for log aggregators (Datadog, Loki, etc.).
    """
    logging.basicConfig(
        format="%(message)s",
        level=logging.DEBUG if debug else logging.INFO,
    )
    # Suppress noisy third-party loggers regardless of debug mode
    for noisy in ("httpcore", "httpx", "urllib3", "hpack", "h2"):
        logging.getLogger(noisy).setLevel(logging.WARNING)

    shared_processors = [
        structlog.contextvars.merge_contextvars,
        structlog.stdlib.add_log_level,
        structlog.processors.TimeStamper(fmt="iso"),
    ]

    if debug:
        renderer = structlog.dev.ConsoleRenderer()
    else:
        renderer = structlog.processors.JSONRenderer()

    structlog.configure(
        processors=shared_processors + [
            structlog.processors.format_exc_info,
            renderer,
        ],
        wrapper_class=structlog.make_filtering_bound_logger(
            logging.DEBUG if debug else logging.INFO
        ),
        context_class=dict,
        logger_factory=structlog.PrintLoggerFactory(),
        cache_logger_on_first_use=True,
    )


def get_logger(name: str, **initial_values) -> structlog.BoundLogger:
    """Return a bound structlog logger. Bind agent_id and any static context at call site."""
    return structlog.get_logger(name, **initial_values)


# ── Sentry ────────────────────────────────────────────────────────────────

def init_sentry(dsn: Optional[str], environment: str = "development") -> bool:
    """Initialize Sentry. Silently skips if DSN is not set — Sentry is optional in dev."""
    if not dsn or not SENTRY_AVAILABLE:
        return False
    sentry_sdk.init(
        dsn=dsn,
        integrations=[FlaskIntegration()],
        environment=environment,
        traces_sample_rate=0.2,
        send_default_pii=False,
    )
    return True


def get_sentry_status() -> str:
    if not SENTRY_AVAILABLE:
        return "not_installed"
    try:
        client = sentry_sdk.get_client()
        return "ok" if (client and client.dsn) else "not_configured"
    except Exception:
        return "error"


# ── Scan cost accumulator ─────────────────────────────────────────────────

def init_scan_cost() -> None:
    """Call at the start of each /api/scan request to zero the per-scan accumulator."""
    _tls.scan_cost_cents = 0.0
    _tls.ai_call_stats = []


def get_scan_cost() -> float:
    return getattr(_tls, "scan_cost_cents", 0.0)


def finalize_scan_cost() -> float:
    """Persist the scan total so /api/health/detailed can report it. Returns total."""
    global _last_scan_cost_cents
    total = get_scan_cost()
    _last_scan_cost_cents = round(total, 4)
    return _last_scan_cost_cents


def record_ai_call_stat(model: str, input_tokens: int, output_tokens: int, latency_ms: float) -> float:
    """
    Record a single Gemini API call. Called directly from _call_gemini after each response.
    Returns the cost in cents for this call.
    """
    pricing = _get_pricing(model)
    cost_cents = (
        input_tokens * pricing["input"] + output_tokens * pricing["output"]
    ) / 1_000_000

    stat = {
        "model": model,
        "input_tokens": input_tokens,
        "output_tokens": output_tokens,
        "latency_ms": round(latency_ms, 1),
        "cost_cents": round(cost_cents, 4),
    }

    stats: list = getattr(_tls, "ai_call_stats", [])
    stats.append(stat)
    _tls.ai_call_stats = stats

    current_cost = getattr(_tls, "scan_cost_cents", 0.0)
    _tls.scan_cost_cents = current_cost + cost_cents

    log = get_logger("ai")
    log.info(
        "ai_call_complete",
        model=model,
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        latency_ms=round(latency_ms, 1),
        cost_cents=round(cost_cents, 4),
    )

    return cost_cents


# ── AI call decorator ─────────────────────────────────────────────────────

def observe_ai_call(model_name: str, agent: str = "0B") -> Callable:
    """
    Decorator for functions that make one or more Gemini API calls.
    Logs function-level latency and aggregated token totals after the function returns.
    Per-API-call stats are recorded by record_ai_call_stat() inside _call_gemini.
    Usage: @observe_ai_call("gemini-2.5-pro", agent="2")
    """
    def decorator(fn: Callable) -> Callable:
        log = get_logger("ai", agent_id=agent)

        @functools.wraps(fn)
        def wrapper(*args, **kwargs):
            # Snapshot stats before call so we isolate only this function's calls
            stats_before = list(getattr(_tls, "ai_call_stats", []))
            start = time.time()

            result = fn(*args, **kwargs)

            latency_ms = (time.time() - start) * 1000
            all_stats = getattr(_tls, "ai_call_stats", [])
            new_stats = all_stats[len(stats_before):]  # only stats from this invocation

            total_input = sum(s["input_tokens"] for s in new_stats)
            total_output = sum(s["output_tokens"] for s in new_stats)
            total_cost = sum(s["cost_cents"] for s in new_stats)

            log.info(
                "ai_function_complete",
                function=fn.__name__,
                model=model_name,
                api_calls=len(new_stats),
                total_input_tokens=total_input,
                total_output_tokens=total_output,
                total_cost_cents=round(total_cost, 4),
                latency_ms=round(latency_ms, 1),
            )
            return result

        return wrapper
    return decorator


# ── Flask middleware ──────────────────────────────────────────────────────

def setup_observability(app, supabase_client=None) -> None:
    """
    Register Flask before/after request hooks and initialize Sentry.
    Call from app.py after the Flask app is created.
    """
    from config import Config

    configure_logging(debug=Config.DEBUG)

    environment = os.environ.get("FLASK_ENV", "development")
    sentry_initialized = init_sentry(Config.SENTRY_DSN, environment)

    log = get_logger("startup", agent_id="0B")
    log.info(
        "observability_initialized",
        debug=Config.DEBUG,
        environment=environment,
        sentry=sentry_initialized,
        structlog="ok",
    )

    _register_hooks(app)


def _register_hooks(app) -> None:
    log = get_logger("http", agent_id="0B")

    @app.before_request
    def _before():
        from flask import g, request
        g.request_start = time.time()

        if SENTRY_AVAILABLE:
            try:
                auth = request.headers.get("Authorization", "")
                if auth.startswith("Bearer "):
                    token_prefix = auth.split(" ")[1][:8]
                    sentry_sdk.set_user({"id": f"bearer:{token_prefix}"})
            except Exception:
                pass

    @app.after_request
    def _after(response):
        from flask import g, request
        duration_ms = round((time.time() - g.get("request_start", time.time())) * 1000, 1)
        log.info(
            "http_request",
            method=request.method,
            path=request.path,
            status_code=response.status_code,
            duration_ms=duration_ms,
        )
        return response


# ── Health helpers ────────────────────────────────────────────────────────

def get_uptime_seconds() -> float:
    return round(time.time() - _start_time, 1)


def check_gemini_status() -> str:
    """Check Gemini API reachability. Result is cached for GEMINI_STATUS_TTL seconds."""
    global _gemini_status_cache
    now = time.time()
    if now - _gemini_status_cache["last_checked"] < _GEMINI_STATUS_TTL:
        return _gemini_status_cache["status"]

    api_key = os.environ.get("GEMINI_API_KEY", "")
    if not api_key:
        _gemini_status_cache = {"status": "no_key", "last_checked": now}
        return "no_key"

    try:
        from google import genai as _genai
        _client = _genai.Client(api_key=api_key)
        # Cheapest possible check: list the first model, no generation needed
        next(iter(_client.models.list()), None)
        _gemini_status_cache = {"status": "ok", "last_checked": now}
        return "ok"
    except Exception as e:
        status = "quota_exhausted" if "429" in str(e) else "error"
        _gemini_status_cache = {"status": status, "last_checked": now}
        return status


def check_supabase_status(supabase_client) -> str:
    if not supabase_client:
        return "not_configured"
    try:
        supabase_client.table("profiles").select("id").limit(1).execute()
        return "ok"
    except Exception:
        return "error"


def get_last_scan_cost() -> float:
    return _last_scan_cost_cents


# ── Auto-configure at import time ─────────────────────────────────────────
# Runs immediately so loggers work from the first import, before setup_observability() is called.
_debug_flag = os.environ.get("FLASK_DEBUG", "true").lower() == "true"
configure_logging(debug=_debug_flag)
