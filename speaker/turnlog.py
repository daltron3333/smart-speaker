"""One JSON line per turn with how long each stage took, for the 4-second target."""

from __future__ import annotations

import json
import logging
import statistics
from datetime import datetime
from pathlib import Path

log = logging.getLogger(__name__)


def write(path: Path, record: dict) -> None:
    record = {"at": datetime.now().isoformat(timespec="seconds"), **record}
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a") as f:
            f.write(json.dumps(record) + "\n")
    except OSError as e:
        log.warning("could not write %s: %s", path, e)
    timings = {k: v for k, v in record.items() if k.endswith("_s")}
    log.info("turn %s", " ".join(f"{k}={v}" for k, v in timings.items()))


def summarize(path: Path, field: str = "first_audio_s", last: int | None = None) -> str:
    """Median and slowest value of `field` over the logged turns (optionally the last N)."""
    rows = [json.loads(line) for line in path.read_text().splitlines() if line.strip()]
    if last:
        rows = rows[-last:]
    values = sorted(r[field] for r in rows if isinstance(r.get(field), (int, float)))
    if not values:
        return f"No turns with {field} in {path}."
    lines = [
        f"{len(values)} turns with {field}",
        f"  median  {statistics.median(values):.2f} s",
        f"  p90     {values[min(len(values) - 1, int(0.9 * len(values)))]:.2f} s",
        f"  slowest {values[-1]:.2f} s",
    ]
    for stage in ("record_s", "stt_s", "claude_first_s", "tts_first_s", "total_s"):
        stage_values = [r[stage] for r in rows if isinstance(r.get(stage), (int, float))]
        if stage_values:
            lines.append(f"  {stage:<15} median {statistics.median(stage_values):.2f} s")
    return "\n".join(lines)
