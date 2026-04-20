import time
import math
import logging
from collections import deque

class ClientState:
    """
    Tracks state, sequence gaps, tracking end-to-end latencies
    for a single telemetry client.
    """
    def __init__(self, client_id, window_size=100):
        self.client_id = client_id
        self.window_size = window_size
        self.last_seq_no = None
        self.packets_received = 0
        self.packets_lost = 0
        self.sensor_values = deque(maxlen=window_size)
        self.latencies = deque(maxlen=window_size)
        self.last_seen = time.time()

    def update(self, seq_no, sensor_value, packet_timestamp):
        """Update client statistics including transit latency."""
        now = time.time()
        self.last_seen = now
        latency = (now - packet_timestamp) * 1000.0 # to ms
        self.latencies.append(latency)
        
        self.packets_received += 1
        if self.last_seq_no is not None:
            gap = seq_no - self.last_seq_no - 1
            if gap > 0:
                self.packets_lost += gap
                # Avoid spamming logs during high-rate bursts to prevent lock contention
                # logging.warning(f"Client {self.client_id} lost {gap} packets.")
                
        if self.last_seq_no is None or seq_no > self.last_seq_no:
            self.last_seq_no = seq_no
            
        self.sensor_values.append(sensor_value)

    def is_inactive(self, timeout=30):
        """Return True if no packets received within the timeout window in seconds."""
        return (time.time() - self.last_seen) > timeout

    def get_summary(self):
        """Calculate and return statistical summaries."""
        # Sensor aggregates
        sensor_list = list(self.sensor_values)
        if not sensor_list:
            min_val = max_val = mean_val = std_dev = 0.0
        else:
            min_val = min(sensor_list)
            max_val = max(sensor_list)
            mean_val = sum(sensor_list) / len(sensor_list)
            std_dev = math.sqrt(sum((x - mean_val) ** 2 for x in sensor_list) / len(sensor_list))
            
        # Latency aggregates
        lat_list = list(self.latencies)
        avg_latency = (sum(lat_list) / len(lat_list)) if lat_list else 0.0
        
        total_expected = self.packets_received + self.packets_lost
        loss_pct = (self.packets_lost / total_expected * 100.0) if total_expected > 0 else 0.0
        
        return {
            "client_id": self.client_id,
            "received": self.packets_received,
            "lost": self.packets_lost,
            "loss_pct": loss_pct,
            "min": min_val,
            "max": max_val,
            "mean": mean_val,
            "std_dev": std_dev,
            "avg_latency_ms": avg_latency
        }
