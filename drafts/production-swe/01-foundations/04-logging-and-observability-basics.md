# 04 — Logging and Observability Basics

## Why Logging Is Not `print()`

`print()` is synchronous, unstructured, and goes to stdout without metadata. In a production system, it is worse than useless: it pollutes container logs, can't be queried, can't be filtered by severity, and contains no context about *when* something happened, in *which service*, in *which request*, or in *which thread*.

Logging in production serves a different purpose than debugging during development:

- **Diagnosability**: given an incident, reconstruct what happened and why, without a debugger
- **Auditability**: what operations occurred, on which entities, triggered by whom
- **Alertability**: emit signals that monitoring systems can detect and route to the right people
- **Operational awareness**: is the system behaving normally under current load?

This chapter covers the *foundations* of logging — the vocabulary, the decisions, and the Python tools. The full observability stack (metrics, distributed tracing, alerting, SLOs) is in Chapter 08.

---

## 1. What Makes a Good Log Entry

A log entry is not a string. It is a **structured event** with a timestamp, a severity level, a message, and a set of key-value pairs that provide context.

### Anatomy of a Good Log Entry

```
{
  "timestamp": "2024-03-15T14:32:01.234Z",
  "level": "ERROR",
  "service": "feature-pipeline",
  "logger": "mypackage.pipeline.loader",
  "message": "Feature fetch failed for entity",
  "entity_id": "user-12345",
  "feature_group": "purchase_history",
  "duration_ms": 1423,
  "error": "ConnectionRefusedError: [Errno 111] Connection refused",
  "attempt": 3,
  "max_attempts": 3,
  "trace_id": "4bf92f3577b34da6",
  "span_id": "00f067aa0ba902b7"
}
```

**What makes it good:**
- **ISO8601 UTC timestamp**: no ambiguity about timezone or format
- **Severity level**: machine-filterable
- **Service name**: essential in distributed systems
- **Logger name**: traces back to the code that emitted it
- **Human message**: brief, consistent, search-friendly (don't embed variable values in the message — use structured fields)
- **Structured fields**: key-value pairs that can be queried (e.g., `entity_id:user-12345`)
- **Trace/span IDs**: correlate with distributed tracing (Chapter 08)

### The Most Common Logging Mistake

Embedding variable data inside the message string:

```python
# Bad: the message varies per call — unsearchable
logger.error(f"Failed to fetch features for user {user_id} after {retries} retries")

# Good: fixed message, variable data as structured fields
logger.error("Feature fetch failed", user_id=user_id, retries=retries)
```

With the first approach, grepping your logs for all feature fetch failures requires a regex. With the second, it's `message:"Feature fetch failed"` — exact match, instant.

---

## 2. Log Levels

Python's stdlib defines five levels. Use them consistently:

| Level | Numeric | When to Use |
|-------|---------|-------------|
| `DEBUG` | 10 | Detailed internal state during development; disabled in production |
| `INFO` | 20 | Normal operational events: startup, shutdown, job completion, config loaded |
| `WARNING` | 30 | Something unexpected but recoverable: fallback used, rate limit approaching, deprecated config key |
| `ERROR` | 40 | A specific operation failed but the service continues: request failed, job failed, retry exhausted |
| `CRITICAL` | 50 | The service may be compromised: infrastructure down, data corruption detected, unhandled exception |

### Level Usage Guidelines

**DEBUG** — emit freely, filter aggressively. Never log sensitive data (PII, credentials) at any level, but especially not at DEBUG where it's tempting to "just dump everything."

```python
logger.debug("Entering feature transformation", features=features, step="normalize")
```

**INFO** — the narrative of normal operation. If you replay INFO logs, you should be able to reconstruct what the system did.

```python
logger.info("Pipeline started", job_id=job_id, dataset_size=len(dataset))
logger.info("Pipeline completed", job_id=job_id, duration_ms=duration, records_processed=count)
```

**WARNING** — something worth knowing, but not paging anyone. Watch aggregate warning rates.

```python
logger.warning("Cache miss, falling back to DB", key=cache_key, latency_ms=latency)
logger.warning("Config key deprecated", old_key="max_iter", new_key="max_epochs")
```

**ERROR** — a specific operation failed. Should trigger investigation (though not necessarily immediate paging). Always include the exception.

```python
logger.error("Feature store request failed", entity_id=entity_id, exc_info=True)
```

**CRITICAL** — something is wrong with the system, not just a request. Should always page someone.

```python
logger.critical("Cannot connect to feature store after N retries — serving degraded", 
                attempts=N, exc_info=True)
```

---

## 3. Python's `logging` Module

The stdlib `logging` module is the foundation. Understanding it is required even if you use structlog on top.

### Core Architecture

```
Logger
  └── Handler(s)
        └── Formatter
```

- **Logger**: what your code calls (`logger.info(...)`)
- **Handler**: where output goes (stdout, file, HTTP endpoint, Sentry)
- **Formatter**: how output is formatted (plain text, JSON)
- **Filter**: optional predicate on which records to pass

### Basic Setup

```python
import logging

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(name)s %(levelname)s %(message)s",
)

logger = logging.getLogger(__name__)
logger.info("Application started")
```

`__name__` is the key pattern. It creates a logger named after the module (e.g., `mypackage.pipeline.loader`), which gives you hierarchical control:

```python
# Silence noisy library at root level
logging.getLogger("urllib3").setLevel(logging.WARNING)
logging.getLogger("boto3").setLevel(logging.WARNING)

# Your code runs at INFO
logging.getLogger("mypackage").setLevel(logging.INFO)
```

### Production Configuration via `dictConfig`

For production, use `dictConfig` instead of `basicConfig`:

```python
import logging.config

LOGGING_CONFIG = {
    "version": 1,
    "disable_existing_loggers": False,  # important: don't silence third-party loggers
    "formatters": {
        "json": {
            "()": "pythonjsonlogger.jsonlogger.JsonFormatter",
            "format": "%(asctime)s %(name)s %(levelname)s %(message)s",
        },
        "plain": {
            "format": "%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        },
    },
    "handlers": {
        "stdout": {
            "class": "logging.StreamHandler",
            "stream": "ext://sys.stdout",
            "formatter": "json",  # JSON in production
        },
    },
    "root": {
        "level": "INFO",
        "handlers": ["stdout"],
    },
    "loggers": {
        "mypackage": {"level": "DEBUG", "propagate": True},
        "urllib3": {"level": "WARNING", "propagate": True},
    },
}

logging.config.dictConfig(LOGGING_CONFIG)
```

### Adding Context with `LoggerAdapter`

`LoggerAdapter` lets you attach fixed context (e.g., request ID, job ID) to all log calls from a logger without passing it every time:

```python
import logging
from typing import Any

class ContextLogger(logging.LoggerAdapter):
    def process(
        self, msg: str, kwargs: dict[str, Any]
    ) -> tuple[str, dict[str, Any]]:
        extra = kwargs.setdefault("extra", {})
        extra.update(self.extra)
        return msg, kwargs

def get_job_logger(job_id: str) -> logging.LoggerAdapter:
    base_logger = logging.getLogger("mypackage.pipeline")
    return ContextLogger(base_logger, {"job_id": job_id})

# Usage
def run_job(job_id: str, data: list) -> None:
    logger = get_job_logger(job_id)
    logger.info("Job started", extra={"record_count": len(data)})
    # All log entries from this function include job_id automatically
```

### `exc_info` — Always Log the Full Exception

```python
try:
    result = risky_operation()
except OperationError as e:
    # Bad: just the message, no traceback
    logger.error("Operation failed: %s", e)

    # Good: full traceback in the log entry
    logger.error("Operation failed", exc_info=True)

    # Also good: explicit exception
    logger.exception("Operation failed")  # equivalent to error + exc_info=True
```

---

## 4. Structured Logging with `structlog`

`structlog` is the recommended library for structured logging in Python. It adds:

- First-class key-value context binding
- Processor pipeline (you control how log entries are formatted/enriched)
- Drop-in compatibility with stdlib `logging` handlers
- Thread-local and async-local context

```bash
uv add structlog
```

### Configuration

```python
import structlog
import logging

def configure_logging(level: str = "INFO", json_output: bool = True) -> None:
    """Configure structlog with stdlib logging backend."""
    
    shared_processors = [
        structlog.contextvars.merge_contextvars,       # async/thread context
        structlog.stdlib.add_log_level,                # "level": "info"
        structlog.stdlib.add_logger_name,              # "logger": "mypackage.x"
        structlog.processors.TimeStamper(fmt="iso"),   # "timestamp": "..."
        structlog.processors.StackInfoRenderer(),
    ]

    if json_output:
        # Production: JSON output
        structlog.configure(
            processors=shared_processors + [
                structlog.stdlib.ProcessorFormatter.wrap_for_formatter,
            ],
            logger_factory=structlog.stdlib.LoggerFactory(),
            cache_logger_on_first_use=True,
        )
        formatter = structlog.stdlib.ProcessorFormatter(
            processor=structlog.processors.JSONRenderer(),
            foreign_pre_chain=shared_processors,
        )
    else:
        # Development: colored human-readable output
        structlog.configure(
            processors=shared_processors + [
                structlog.dev.ConsoleRenderer(colors=True),
            ],
            logger_factory=structlog.stdlib.LoggerFactory(),
            cache_logger_on_first_use=True,
        )
        formatter = structlog.stdlib.ProcessorFormatter(
            processor=structlog.dev.ConsoleRenderer(colors=True),
            foreign_pre_chain=shared_processors,
        )

    handler = logging.StreamHandler()
    handler.setFormatter(formatter)
    
    root_logger = logging.getLogger()
    root_logger.handlers = [handler]
    root_logger.setLevel(level)
```

### Basic Usage

```python
import structlog

logger = structlog.get_logger(__name__)

# Simple structured call
logger.info("pipeline_started", job_id="job-001", dataset_size=10_000)
# → {"timestamp": "...", "level": "info", "event": "pipeline_started", 
#    "job_id": "job-001", "dataset_size": 10000}

# Error with exception
try:
    result = load_data(path)
except FileNotFoundError:
    logger.error("data_load_failed", path=str(path), exc_info=True)

# Warning with duration
logger.warning("slow_query", duration_ms=3421, threshold_ms=1000, query_id=qid)
```

### Context Binding — The Key Feature

`bind()` returns a new logger with additional context attached. All subsequent calls carry it:

```python
# Bind job-level context once
job_logger = logger.bind(job_id="job-001", model="bert-base")

# All calls carry job_id and model
job_logger.info("epoch_started", epoch=1)
job_logger.info("epoch_completed", epoch=1, loss=0.342, accuracy=0.91)
job_logger.warning("lr_scheduler_plateau", current_lr=0.0001)
```

### `contextvars` — Async and Thread-Safe Context

For services handling many concurrent requests, use `contextvars` to bind request-scoped context without passing loggers around:

```python
import structlog
from contextvars import ContextVar

# In your request middleware / task entrypoint
def process_request(request_id: str, user_id: str) -> None:
    # Binds to the current async context — safe in asyncio
    structlog.contextvars.bind_contextvars(
        request_id=request_id,
        user_id=user_id,
    )
    
    # Now any logger in any function called from here
    # automatically includes request_id and user_id
    do_work()

def do_work() -> None:
    log = structlog.get_logger(__name__)
    log.info("doing_work")
    # → {"event": "doing_work", "request_id": "req-xyz", "user_id": "usr-123", ...}
```

### FastAPI Middleware Example

```python
from fastapi import FastAPI, Request
import structlog
import uuid

app = FastAPI()

@app.middleware("http")
async def logging_middleware(request: Request, call_next):
    request_id = str(uuid.uuid4())
    structlog.contextvars.clear_contextvars()
    structlog.contextvars.bind_contextvars(
        request_id=request_id,
        method=request.method,
        path=request.url.path,
    )
    
    logger = structlog.get_logger()
    logger.info("request_started")
    
    response = await call_next(request)
    
    logger.info(
        "request_completed",
        status_code=response.status_code,
    )
    return response
```

### `structlog` vs `logging` stdlib — When to Use What

| | stdlib `logging` | structlog |
|---|---|---|
| Zero deps | ✅ | ❌ (lightweight) |
| Structured key-value context | Awkward via `extra={}` | First-class `.bind()` |
| Processor pipeline | No | Yes — format, filter, enrich |
| Async context propagation | No | Yes (`contextvars`) |
| JSON output | Via formatter | Built-in processor |
| Dev console (colored) | No | Built-in `ConsoleRenderer` |
| Compatible with stdlib handlers | N/A | Yes — drop-in |

**Recommendation:** Use structlog for all application code. Its `LoggerFactory` routes through stdlib handlers, so third-party libraries that use `logging.getLogger()` are captured too.

---

## 5. What to Log (and What Not To)

### Log Events, Not State Dumps

A log entry should record that **something happened**, not dump the current state of your objects.

```python
# Bad: state dump — hard to read, may be huge
logger.debug("Model state", model=str(model.__dict__))

# Good: event with relevant fields
logger.info("model_checkpoint_saved", epoch=10, val_loss=0.234, path=str(checkpoint_path))
```

### Operational Checkpoints

For long-running jobs (batch inference, data pipelines), log operational checkpoints:

```python
logger.info("batch_started", batch_id=batch_id, size=len(batch))
# ... processing ...
logger.info("batch_completed", batch_id=batch_id, duration_ms=duration, 
            records_in=len(batch), records_out=len(results), skipped=len(skipped))
```

This gives you:
- Progress tracking without polling
- Throughput calculation (`records_in / duration_ms`)
- Skip rate monitoring

### Sensitive Data — Never Log

- Passwords, API keys, tokens
- PII: names, emails, phone numbers, IP addresses (check your jurisdiction)
- Full request/response bodies from external APIs
- Model weights or gradients

```python
# Bad
logger.info("User authenticated", username=username, password=password)

# Good
logger.info("User authenticated", user_id=user.id, auth_method="oauth2")
```

If you must log request bodies for debugging, sanitize first:

```python
def sanitize_payload(payload: dict) -> dict:
    SENSITIVE_KEYS = {"password", "token", "api_key", "secret", "authorization"}
    return {
        k: "***" if k.lower() in SENSITIVE_KEYS else v
        for k, v in payload.items()
    }
```

### Volume Control

Logs are not free. In high-throughput services:

- **Avoid DEBUG in production** — log only on explicit flag/config
- **Sample high-frequency events** — don't log every cache hit at INFO level
- **Aggregate where possible** — "processed 1000 records in 2.3s" vs 1000 individual records

```python
import random

def process_record(record: dict) -> None:
    result = transform(record)
    
    # Sample 1% of successful records at DEBUG
    if random.random() < 0.01:
        logger.debug("record_processed", record_id=record["id"], sample=True)
    
    return result
```

---

## 6. Logging Configuration Patterns

### Environment-Driven Configuration

```python
from pydantic_settings import BaseSettings
from typing import Literal

class LogSettings(BaseSettings):
    log_level: Literal["DEBUG", "INFO", "WARNING", "ERROR"] = "INFO"
    log_format: Literal["json", "console"] = "json"
    log_service_name: str = "unknown-service"

    class Config:
        env_prefix = "LOG_"

settings = LogSettings()
configure_logging(
    level=settings.log_level,
    json_output=(settings.log_format == "json"),
)
```

### Twelve-Factor App Logging

Following [12-factor](https://12factor.net/logs) principles:

- **Log to stdout only** — the container runtime, log aggregator, or orchestrator routes it
- **Never write to files** from within the app — file rotation, permissions, and disk space management belong to the infrastructure layer
- **Never ship to a remote endpoint from within the app** — Datadog, CloudWatch, Splunk agents read from stdout/container logs externally

```python
# This is the correct handler for 12-factor services
handler = logging.StreamHandler(sys.stdout)  # always stdout, never stderr for normal logs
```

---

## 7. A Complete Logging Setup Example

A minimal but production-ready logging setup for a Python service:

```python
# src/mypackage/logging_config.py
from __future__ import annotations

import logging
import sys
from typing import Literal

import structlog


def configure_logging(
    level: str = "INFO",
    format: Literal["json", "console"] = "json",
    service_name: str = "service",
) -> None:
    """Configure structured logging for the application.

    Call this once at application startup, before any loggers are created.

    Args:
        level: Minimum log level. One of DEBUG, INFO, WARNING, ERROR, CRITICAL.
        format: Output format. Use 'json' in production, 'console' in development.
        service_name: Identifies this service in log aggregation systems.
    """
    shared_processors: list = [
        structlog.contextvars.merge_contextvars,
        structlog.stdlib.add_log_level,
        structlog.stdlib.add_logger_name,
        structlog.processors.TimeStamper(fmt="iso", utc=True),
        structlog.processors.StackInfoRenderer(),
        structlog.processors.format_exc_info,
        # Add service name to every log entry
        structlog.processors.CallsiteParameterAdder(
            [structlog.processors.CallsiteParameter.FILENAME,
             structlog.processors.CallsiteParameter.LINENO],
        ),
    ]

    if format == "json":
        renderer = structlog.processors.JSONRenderer()
    else:
        renderer = structlog.dev.ConsoleRenderer(colors=True)

    structlog.configure(
        processors=shared_processors + [
            structlog.stdlib.ProcessorFormatter.wrap_for_formatter,
        ],
        logger_factory=structlog.stdlib.LoggerFactory(),
        wrapper_class=structlog.stdlib.BoundLogger,
        cache_logger_on_first_use=True,
    )

    formatter = structlog.stdlib.ProcessorFormatter(
        processor=renderer,
        foreign_pre_chain=shared_processors,
    )

    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(formatter)

    root = logging.getLogger()
    root.handlers = [handler]
    root.setLevel(level)

    # Silence noisy libraries
    for noisy in ["urllib3", "botocore", "boto3", "s3transfer"]:
        logging.getLogger(noisy).setLevel(logging.WARNING)
```

```python
# src/mypackage/main.py
from mypackage.logging_config import configure_logging
from mypackage.settings import AppSettings

def main() -> None:
    settings = AppSettings()
    configure_logging(
        level=settings.log_level,
        format=settings.log_format,
        service_name="feature-pipeline",
    )
    
    log = structlog.get_logger()
    log.info("service_started", version=settings.version, env=settings.env)
    # ... rest of startup
```

---

## Summary

| Concept | Rule |
|---------|------|
| Log format | Always structured (JSON in prod, console in dev) |
| Message string | Fixed and searchable — never embed variables |
| Variable data | Structured key-value fields |
| Log levels | DEBUG (dev only), INFO (operational), WARNING (recoverable anomaly), ERROR (operation failed), CRITICAL (system at risk) |
| Context | Bind job/request ID at the start of each unit of work |
| Exceptions | Always `exc_info=True` on ERROR and above |
| Sensitive data | Never log credentials, tokens, or PII |
| Output destination | Stdout only (12-factor) |
| Library | structlog over raw stdlib for application code |

> **Logging is the cheapest observability tool you have. The cost is paid at design time (good structure) not at runtime. An hour spent on good log structure saves hours of production debugging.**

## What's Next

This chapter covers the foundations of logging. Chapter 08 (Observability) extends this with:
- **Metrics**: counters, histograms, gauges with Prometheus
- **Distributed tracing**: OpenTelemetry, spans, trace propagation across services
- **Alerting**: SLOs, error budgets, alert routing
- **Profiling**: CPU and memory profiling in production
