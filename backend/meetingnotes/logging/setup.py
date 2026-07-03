"""Logging that a person can read.

A rotating file at MeetingVault/logs/backend.log: ISO timestamp, level, the
meeting id and stage where relevant, and a plain message. A companion file,
backend.jsonl, holds the same records as one JSON object per line for later
searching. Logs carry identifiers and error detail only; never transcript or
summary text.
"""

from __future__ import annotations

import json
import logging
from datetime import datetime
from logging.handlers import RotatingFileHandler
from pathlib import Path

LOG_NAME = "backend.log"
JSON_LOG_NAME = "backend.jsonl"


def _timestamp(record: logging.LogRecord) -> str:
    return datetime.fromtimestamp(record.created).astimezone().isoformat(timespec="seconds")


def _context(record: logging.LogRecord) -> tuple[str | None, str | None]:
    return getattr(record, "meeting_id", None), getattr(record, "stage", None)


class HumanFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        meeting_id, stage = _context(record)
        context = ""
        if meeting_id:
            context = f" [meeting {meeting_id}" + (f", stage {stage}" if stage else "") + "]"
        return f"{_timestamp(record)} {record.levelname}{context} {record.getMessage()}"


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        meeting_id, stage = _context(record)
        entry = {
            "ts": _timestamp(record),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }
        if meeting_id:
            entry["meeting_id"] = meeting_id
        if stage:
            entry["stage"] = stage
        return json.dumps(entry)


def configure_logging(
    logs_dir: Path, level: str = "info",
    max_bytes: int = 1_000_000, backup_count: int = 3,
) -> logging.Logger:
    """Set up the meetingnotes logger tree to write both files. Safe to call
    again (say, after a config change): handlers are replaced, not stacked."""
    logs_dir.mkdir(parents=True, exist_ok=True)
    logger = logging.getLogger("meetingnotes")
    logger.setLevel(getattr(logging, level.upper(), logging.INFO))
    for handler in list(logger.handlers):
        logger.removeHandler(handler)
        handler.close()

    human = RotatingFileHandler(
        logs_dir / LOG_NAME, maxBytes=max_bytes, backupCount=backup_count
    )
    human.setFormatter(HumanFormatter())
    machine = RotatingFileHandler(
        logs_dir / JSON_LOG_NAME, maxBytes=max_bytes, backupCount=backup_count
    )
    machine.setFormatter(JsonFormatter())
    logger.addHandler(human)
    logger.addHandler(machine)
    return logger
