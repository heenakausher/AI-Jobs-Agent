"""Performance metrics tracking."""

import time
from typing import Any, Dict, List


class MetricsTracker:
    """Tracks performance metrics across pipeline stages."""

    def __init__(self) -> None:
        self._start_time: float = time.time()
        self._phase_times: Dict[str, float] = {}
        self._counts: Dict[str, int] = {}
        self._lists: Dict[str, List[float]] = {}

    def start_phase(self, name: str) -> None:
        self._phase_times[name + "_start"] = time.time()

    def end_phase(self, name: str) -> float:
        start = self._phase_times.pop(name + "_start", None)
        if start is None:
            return 0.0
        duration = time.time() - start
        self._phase_times[name] = self._phase_times.get(name, 0.0) + duration
        return duration

    def record_value(self, key: str, value: float) -> None:
        if key not in self._lists:
            self._lists[key] = []
        self._lists[key].append(value)

    def increment(self, key: str, count: int = 1) -> None:
        self._counts[key] = self._counts.get(key, 0) + count

    def get_phase_time(self, name: str) -> float:
        return self._phase_times.get(name, 0.0)

    def get_count(self, key: str) -> int:
        return self._counts.get(key, 0)

    def average(self, key: str) -> float:
        vals = self._lists.get(key, [])
        if not vals:
            return 0.0
        return sum(vals) / len(vals)

    def total_elapsed(self) -> float:
        return time.time() - self._start_time

    def summary(self) -> Dict[str, Any]:
        return {
            "total_runtime": self.total_elapsed(),
            "phases": dict(self._phase_times),
            "counts": dict(self._counts),
            "averages": {k: self.average(k) for k in self._lists},
        }

    def print_summary(self) -> None:
        import logging
        log = logging.getLogger("agent")
        log.info("")
        log.info("%s", "=" * 50)
        log.info("PERFORMANCE METRICS")
        log.info("%s", "=" * 50)
        log.info("Total runtime:           %7.1fs", self.total_elapsed())

        for phase, dur in sorted(self._phase_times.items()):
            pct = (dur / self.total_elapsed() * 100) if self.total_elapsed() > 0 else 0
            log.info("  %-25s %7.1fs  %5.1f%%", phase, dur, pct)

        for key, val in sorted(self._counts.items()):
            log.info("  %-25s %7d", key, val)

        for key in sorted(self._lists.keys()):
            avg = self.average(key)
            vals = self._lists[key]
            if vals:
                log.info("  %-25s %7.2f  (n=%d)", key, avg, len(vals))
