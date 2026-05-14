"""Tiny opt-in performance tracing for TUI cold paths."""

from __future__ import annotations

import os
import threading
import time
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path
from typing import Any

_FALSEY = {"", "0", "false", "no", "off"}
_THREAD = threading.local()
_PHASE_ORDER = (
    "metadata_findings",
    "review_queues",
    "plan_index",
    "metadata_workbench_rows",
    "workbench_sql",
    "row_assembly",
    "post_warm_fill",
)


def enabled() -> bool:
    value = os.environ.get("SFXWORKBENCH_PERF_LOG", "")
    return value.strip().casefold() not in _FALSEY


def begin_trace(event: str) -> None:
    if not enabled():
        return
    _THREAD.trace = {"event": event, "start": time.perf_counter(), "phases": {}}


def record_phase(name: str, seconds: float) -> None:
    trace = getattr(_THREAD, "trace", None)
    if trace is None:
        return
    phases = trace["phases"]
    phases[name] = float(phases.get(name, 0.0)) + seconds


@contextmanager
def timed(name: str) -> Iterator[None]:
    trace = getattr(_THREAD, "trace", None)
    if trace is None:
        yield
        return
    start = time.perf_counter()
    try:
        yield
    finally:
        record_phase(name, time.perf_counter() - start)


def snapshot_trace(*, clear: bool = True) -> dict[str, Any] | None:
    trace = getattr(_THREAD, "trace", None)
    if trace is None:
        return None
    if clear:
        try:
            del _THREAD.trace
        except AttributeError:
            pass
    return {
        "event": str(trace["event"]),
        "start": float(trace["start"]),
        "phases": dict(trace["phases"]),
    }


def write_trace(trace: dict[str, Any] | None, *, extra_phases: dict[str, float] | None = None) -> None:
    if trace is None or not enabled():
        return
    phases = dict(trace.get("phases", {}))
    if extra_phases:
        for name, seconds in extra_phases.items():
            phases[name] = float(phases.get(name, 0.0)) + seconds
    total = time.perf_counter() - float(trace.get("start", time.perf_counter()))
    ordered = [name for name in _PHASE_ORDER if name in phases]
    ordered.extend(sorted(name for name in phases if name not in ordered))
    fields = [f"{name}={phases[name]:.2f}s" for name in ordered]
    fields.append(f"total={total:.2f}s")
    line = f"{datetime.now().isoformat(timespec='seconds')}  {trace.get('event', 'cold_open')}  {' '.join(fields)}\n"
    try:
        log_path = Path.home() / ".sfxworkbench" / "tui_perf.log"
        log_path.parent.mkdir(parents=True, exist_ok=True)
        with log_path.open("a", encoding="utf-8") as handle:
            handle.write(line)
    except OSError:
        pass
