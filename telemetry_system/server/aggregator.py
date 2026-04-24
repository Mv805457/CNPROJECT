"""
telemetry_system/server/aggregator.py
=======================================
Per-client state tracking for the telemetry server.

Tracks:
  - Received / lost packet counts via sequence-number gap detection.
  - Rolling window of sensor values for min/max/mean/std-dev.
  - Rolling window of end-to-end latency measurements.
  - Last-seen timestamp for idle-client pruning.
"""

import time
import math
import logging
from collections import deque

log = logging.getLogger(__name__)


class ClientState:
    """
    Tracks state, sequence gaps, and end-to-end latencies for a single
    telemetry client.

    All public methods are **not** thread-safe by themselves — the caller
    (``server.py``) is responsible for holding ``self.lock`` around calls.
    """

    def __init__(self, client_id: int, window_size: int = 100):
        self.client_id   = client_id
        self.window_size = window_size

        # Sequence tracking
        self.last_seq_no:      int | None = None
        self.packets_received: int        = 0
        self.packets_lost:     int        = 0

        # Rolling windows (bounded by window_size)
        self.sensor_values: deque[float] = deque(maxlen=window_size)
        self.latencies:     deque[float] = deque(maxlen=window_size)

        self.last_seen: float = time.time()

    # ── Update ────────────────────────────────────────────────────────────────

    def update(self, seq_no: int, sensor_value: float, packet_timestamp: float) -> None:
        """
        Record the arrival of a packet with the given sequence number.

        Gap detection:
          - ``seq_no == expected``   → normal, no loss.
          - ``seq_no > expected``    → gap detected, count missing packets as lost.
          - ``seq_no <= last_seq_no``→ duplicate or out-of-order; ignored to prevent
                                       double-counting.

        Latency is clamped to ``≥ 0`` to defend against minor client/server
        clock skew causing spurious negative values.
        """
        now            = time.time()
        self.last_seen = now

        # Clamp latency — negative values indicate clock skew, not time travel
        latency_ms = max(0.0, (now - packet_timestamp) * 1000.0)
        self.latencies.append(latency_ms)

        self.packets_received += 1

        if self.last_seq_no is not None:
            gap = seq_no - self.last_seq_no - 1
            if gap > 0:
                self.packets_lost += gap
                log.debug(
                    "Client %d: detected gap of %d packet(s) (seq %d → %d).",
                    self.client_id, gap, self.last_seq_no, seq_no,
                )
            # Ignore out-of-order / duplicate arrivals (gap < 0) — do not advance
            # last_seq_no backwards as that would cause future false positives.
            if seq_no <= self.last_seq_no:
                log.debug(
                    "Client %d: ignoring out-of-order / duplicate seq %d (last seen %d).",
                    self.client_id, seq_no, self.last_seq_no,
                )
                return

        self.last_seq_no = seq_no
        self.sensor_values.append(sensor_value)

    # ── Predicates ────────────────────────────────────────────────────────────

    def is_inactive(self, timeout: float = 30.0) -> bool:
        """Return ``True`` if no packet has been received within *timeout* seconds."""
        return (time.time() - self.last_seen) > timeout

    # ── Statistics ────────────────────────────────────────────────────────────

    def get_summary(self) -> dict:
        """
        Compute and return a statistics snapshot.

        Returns a dict with keys:
          ``client_id``, ``received``, ``lost``, ``loss_pct``,
          ``min``, ``max``, ``mean``, ``std_dev``, ``avg_latency_ms``.
        """
        sensor_list = list(self.sensor_values)
        if sensor_list:
            min_val  = min(sensor_list)
            max_val  = max(sensor_list)
            mean_val = sum(sensor_list) / len(sensor_list)
            variance = sum((x - mean_val) ** 2 for x in sensor_list) / len(sensor_list)
            std_dev  = math.sqrt(variance)
        else:
            min_val = max_val = mean_val = std_dev = 0.0

        lat_list    = list(self.latencies)
        avg_latency = (sum(lat_list) / len(lat_list)) if lat_list else 0.0

        total_expected = self.packets_received + self.packets_lost
        loss_pct       = (self.packets_lost / total_expected * 100.0) if total_expected > 0 else 0.0

        return {
            "client_id":     self.client_id,
            "received":      self.packets_received,
            "lost":          self.packets_lost,
            "loss_pct":      loss_pct,
            "min":           min_val,
            "max":           max_val,
            "mean":          mean_val,
            "std_dev":       std_dev,
            "avg_latency_ms": avg_latency,
        }
