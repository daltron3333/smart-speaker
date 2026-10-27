"""The time and date (F6), sent with every question, and the timer tools Claude can call (F7)."""

from __future__ import annotations

import json
import logging
import threading
import time
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Callable

log = logging.getLogger(__name__)

MAX_TIMER_S = 24 * 60 * 60

# There is no clock tool: the time arrives with each question (Skills.time_note), which saves
# a second round trip to the API on the speaker's most common question.
TOOLS = [
    {
        "name": "set_timer",
        "description": "Start a countdown timer. When it ends, the speaker rings and says the "
        "timer is done, so there is no need to remind the user yourself.",
        "input_schema": {
            "type": "object",
            "properties": {
                "duration_seconds": {
                    "type": "integer",
                    "description": f"Length of the timer in seconds, from 1 to {MAX_TIMER_S}.",
                },
                "label": {
                    "type": "string",
                    "description": "Optional short name the user gave the timer, such as 'pasta'.",
                },
            },
            "required": ["duration_seconds"],
        },
    },
    {
        "name": "list_timers",
        "description": "List the running timers with their ids, labels and time remaining.",
        "input_schema": {"type": "object", "properties": {}},
    },
    {
        "name": "cancel_timer",
        "description": "Cancel a running timer by id. Omit timer_id to cancel every running timer. "
        "If the user names one timer and you don't know its id, call list_timers first.",
        "input_schema": {
            "type": "object",
            "properties": {"timer_id": {"type": "integer", "description": "Id from list_timers."}},
        },
    },
]


def describe_duration(seconds: float, before_noun: bool = False) -> str:
    """10 -> '10 seconds', 3725 -> '1 hour, 2 minutes and 5 seconds'.

    before_noun drops the plural, as in 'a 10 minute timer'.
    """
    seconds = max(0, int(round(seconds)))
    hours, rest = divmod(seconds, 3600)
    minutes, secs = divmod(rest, 60)
    parts = []
    for amount, unit in ((hours, "hour"), (minutes, "minute"), (secs, "second")):
        if amount:
            plural = "" if amount == 1 or before_noun else "s"
            parts.append(f"{amount} {unit}{plural}")
    if not parts:
        return "0 seconds"
    if len(parts) == 1:
        return parts[0]
    return ", ".join(parts[:-1]) + " and " + parts[-1]


@dataclass
class _Timer:
    id: int
    seconds: int
    label: str
    ends_at: float
    handle: threading.Timer = field(repr=False)

    def name(self) -> str:
        if self.label:
            return f"{self.label} timer"
        return f"{describe_duration(self.seconds, before_noun=True)} timer"


class Timers:
    """Countdown timers that call on_done(announcement) from a background thread when they end."""

    def __init__(self, on_done: Callable[[str], None], clock: Callable[[], float] = time.monotonic):
        self._on_done = on_done
        self._clock = clock
        self._timers: dict[int, _Timer] = {}
        self._next_id = 1
        self._lock = threading.Lock()

    def set(self, seconds: int, label: str = "") -> _Timer:
        with self._lock:
            timer_id = self._next_id
            self._next_id += 1
            handle = threading.Timer(seconds, self._fire, args=(timer_id,))
            handle.daemon = True
            timer = _Timer(timer_id, seconds, label.strip(), self._clock() + seconds, handle)
            self._timers[timer_id] = timer
        handle.start()
        log.info("timer %d set: %s", timer_id, timer.name())
        return timer

    def cancel(self, timer_id: int | None = None) -> list[_Timer]:
        with self._lock:
            ids = list(self._timers) if timer_id is None else [timer_id]
            cancelled = [self._timers.pop(i) for i in ids if i in self._timers]
        for timer in cancelled:
            timer.handle.cancel()
        return cancelled

    def running(self) -> list[tuple[_Timer, float]]:
        now = self._clock()
        with self._lock:
            return [(t, max(0.0, t.ends_at - now)) for t in self._timers.values()]

    def _fire(self, timer_id: int) -> None:
        with self._lock:
            timer = self._timers.pop(timer_id, None)
        if timer is None:
            return
        log.info("timer %d done", timer_id)
        self._on_done(f"Your {timer.name()} is done.")


class Skills:
    """Runs the tool calls in a Claude reply and builds the tool_result blocks."""

    tools = TOOLS

    def __init__(self, timers: Timers, now: Callable[[], datetime] = lambda: datetime.now().astimezone()):
        self.timers = timers
        self._now = now

    def run(self, block: Any) -> dict:
        """block is a tool_use content block; returns the matching tool_result."""
        try:
            handler = getattr(self, f"_tool_{block.name}", None)
            if handler is None:
                raise ValueError(f"Unknown tool {block.name!r}")
            if not isinstance(block.input, dict):
                raise ValueError("Tool input must be an object")
            content = json.dumps(handler(block.input))
            return {"type": "tool_result", "tool_use_id": block.id, "content": content}
        except ValueError as e:
            log.warning("tool %s failed: %s", block.name, e)
            return {"type": "tool_result", "tool_use_id": block.id, "content": str(e), "is_error": True}

    def time_note(self) -> str:
        """The local time and date in the form put in front of each question."""
        now = self._now()
        time_of_day = now.strftime("%I:%M %p").lstrip("0")
        date = now.strftime("%A, %B %d, %Y").replace(" 0", " ")
        return f"[Local time: {time_of_day} on {date}, {now.tzname() or 'local time'}]"

    def _tool_set_timer(self, args: dict) -> dict:
        seconds = args.get("duration_seconds")
        if isinstance(seconds, float) and seconds.is_integer():
            seconds = int(seconds)
        if not isinstance(seconds, int) or isinstance(seconds, bool) or not 1 <= seconds <= MAX_TIMER_S:
            raise ValueError(f"duration_seconds must be a whole number from 1 to {MAX_TIMER_S}")
        label = args.get("label") or ""
        if not isinstance(label, str):
            raise ValueError("label must be a string")
        timer = self.timers.set(seconds, label[:40])
        return {"timer_id": timer.id, "name": timer.name(), "duration": describe_duration(seconds)}

    def _tool_list_timers(self, _: dict) -> dict:
        return {
            "timers": [
                {"timer_id": t.id, "name": t.name(), "remaining": describe_duration(left)}
                for t, left in self.timers.running()
            ]
        }

    def _tool_cancel_timer(self, args: dict) -> dict:
        timer_id = args.get("timer_id")
        if timer_id is not None and (not isinstance(timer_id, int) or isinstance(timer_id, bool)):
            raise ValueError("timer_id must be an integer")
        cancelled = self.timers.cancel(timer_id)
        if timer_id is not None and not cancelled:
            raise ValueError(f"No running timer with id {timer_id}")
        return {"cancelled": [t.name() for t in cancelled]}
