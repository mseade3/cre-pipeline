from __future__ import annotations

import json
import logging
from collections.abc import Mapping
from typing import Any

SENSITIVE_FRAGMENTS = (
    "address",
    "authorization",
    "email",
    "password",
    "phone",
    "secret",
    "token",
)


def redact(data: Mapping[str, Any]) -> dict[str, Any]:
    return {
        key: "[REDACTED]" if any(part in key.lower() for part in SENSITIVE_FRAGMENTS) else value
        for key, value in data.items()
    }


def log_event(logger: logging.Logger, event: str, **fields: Any) -> None:
    logger.info(json.dumps({"event": event, **redact(fields)}, default=str, sort_keys=True))


def configure_logging(level: str = "INFO") -> None:
    logging.basicConfig(level=level.upper(), format="%(message)s")
