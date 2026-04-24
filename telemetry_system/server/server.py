"""
telemetry_system/server/server.py
====================================
Telemetry ingestion server.

Architecture:
  - TCP+TLS listener  → hands out per-client AES-256-GCM session keys.
  - UDP listener      → receives encrypted telemetry datagrams, dispatches
                        decryption/parsing to a thread-pool.
  - Summary thread    → periodically logs per-client stats and prunes idle clients.

Both the TCP handshake and UDP packet-processing are deliberately decoupled:
the TCP phase is heavy (TLS math) but infrequent; the UDP phase is lightweight
but extremely high-volume.  The lock is held only for brief dict lookups/updates —
never around I/O.
"""

import socket
import threading
import time
import argparse
import logging
import struct
import csv
import sys
import os
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

# ── Ensure telemetry_system/ is on sys.path so 'common' is importable ────────
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from common.ssl_utils import create_server_ssl_context, generate_session_key, decrypt_udp_payload
from common.packet   import parse_packet
from aggregator      import ClientState

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger(__name__)


class TelemetryServer:
    def __init__(self, host: str, port: int, cert: str, key: str,
                 metrics_file: str = None, window_size: int = 100):
        self.host        = host
        self.port        = port
        self.ssl_context = create_server_ssl_context(cert, key)
        self.window_size = window_size

        # Shared state — always accessed under self.lock
        self.client_states: dict[int, ClientState] = {}
        self.client_keys:   dict[int, bytes]       = {}
        self.lock = threading.Lock()

        self.running  = threading.Event()
        self.running.set()

        # Bounded pool — avoids unbounded thread creation under burst traffic
        self.executor = ThreadPoolExecutor(max_workers=32, thread_name_prefix="udp-worker")

        self.metrics_file = metrics_file
        if self.metrics_file:
            with open(self.metrics_file, "w", newline="") as f:
                csv.writer(f).writerow(
                    ["timestamp_epoch", "client_id", "received", "lost", "loss_pct", "avg_latency_ms"]
                )

    # ── TCP handshake ─────────────────────────────────────────────────────────

    def _handle_tcp_handshake(self, tcp_conn: socket.socket, addr):
        """Wrap the raw TCP socket in TLS, receive client-id, send session key."""
        try:
            secure_sock = self.ssl_context.wrap_socket(tcp_conn, server_side=True)
            try:
                raw = secure_sock.recv(2)
                if len(raw) != 2:
                    log.warning("Incomplete client-id from %s — dropping.", addr)
                    return

                client_id   = struct.unpack("!H", raw)[0]
                session_key = generate_session_key()

                with self.lock:
                    self.client_keys[client_id] = session_key
                    if client_id not in self.client_states:
                        self.client_states[client_id] = ClientState(client_id, self.window_size)

                secure_sock.sendall(session_key)
                log.info("Handshake complete — client %d registered.", client_id)
            finally:
                secure_sock.close()
        except Exception as exc:
            log.error("Handshake error from %s: %s", addr, exc)

    def _tcp_listener_thread(self):
        """Accept TCP connections and dispatch each handshake to the thread pool."""
        srv = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        srv.bind((self.host, self.port))
        srv.listen(50)
        srv.settimeout(1.0)
        log.info("TCP/TLS listener bound to %s:%d", self.host, self.port)

        while self.running.is_set():
            try:
                conn, addr = srv.accept()
                # Use the executor so TLS handshakes don't spawn unlimited threads
                self.executor.submit(self._handle_tcp_handshake, conn, addr)
            except socket.timeout:
                continue
            except Exception as exc:
                if self.running.is_set():
                    log.error("TCP accept error: %s", exc)

        srv.close()

    # ── UDP ingestion ─────────────────────────────────────────────────────────

    def _udp_listener_thread(self):
        """Receive UDP datagrams and hand them off to worker threads."""
        srv = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        try:
            # 2 MB receive buffer to absorb burst traffic without kernel drops
            srv.setsockopt(socket.SOL_SOCKET, socket.SO_RCVBUF, 2 * 1024 * 1024)
        except OSError:
            pass
        srv.bind((self.host, self.port))
        srv.settimeout(1.0)
        log.info("UDP listener bound to %s:%d", self.host, self.port)

        while self.running.is_set():
            try:
                data, _ = srv.recvfrom(4096)
                if len(data) < 2:
                    continue
                self.executor.submit(self._process_udp_packet, data)
            except socket.timeout:
                continue
            except Exception as exc:
                if self.running.is_set():
                    log.error("UDP recv error: %s", exc)

        srv.close()

    def _process_udp_packet(self, data: bytes):
        """Decrypt and parse one UDP datagram, then update the client state."""
        try:
            client_id         = struct.unpack("!H", data[:2])[0]
            encrypted_payload = data[2:]

            # Grab references under a brief lock — decryption happens outside
            with self.lock:
                key   = self.client_keys.get(client_id)
                state = self.client_states.get(client_id)

            if key is None or state is None:
                return  # Unknown client — handshake hasn't happened yet

            # Expensive crypto outside the lock to avoid contention
            plaintext   = decrypt_udp_payload(key, encrypted_payload)
            packet_data = parse_packet(plaintext)

            with self.lock:
                if client_id in self.client_states:  # Guard against concurrent prune
                    self.client_states[client_id].update(
                        packet_data["seq_no"],
                        packet_data["sensor_value"],
                        packet_data["timestamp"],
                    )
        except Exception as exc:
            log.debug("UDP packet processing error: %s", exc)

    # ── Summary / metrics ─────────────────────────────────────────────────────

    def _summary_printer_thread(self):
        """Every 10 s: log per-client summaries, write metrics, prune idle clients."""
        while self.running.is_set():
            time.sleep(10)
            now = time.time()

            # ── Build snapshot under lock (no I/O inside lock) ────────────────
            with self.lock:
                snapshot  = {cid: state.get_summary()
                             for cid, state in self.client_states.items()}
                to_remove = [cid for cid, state in self.client_states.items()
                             if state.is_inactive(timeout=30)]
                active_count = len(self.client_states) - len(to_remove)

                for cid in to_remove:
                    del self.client_states[cid]
                    self.client_keys.pop(cid, None)

            # ── Log and write metrics outside the lock ────────────────────────
            for cid, s in snapshot.items():
                if cid in to_remove:
                    continue
                log.info(
                    "Client %d | Recv: %d | Lost: %.2f%% | Latency: %.2f ms",
                    cid, s["received"], s["loss_pct"], s["avg_latency_ms"],
                )

            log.info("SUMMARY | Active Clients: %d", active_count)

            if self.metrics_file and snapshot:
                with open(self.metrics_file, "a", newline="") as f:
                    w = csv.writer(f)
                    for cid, s in snapshot.items():
                        if cid not in to_remove:
                            w.writerow([
                                now, cid,
                                s["received"], s["lost"],
                                s["loss_pct"], s["avg_latency_ms"],
                            ])

            if to_remove:
                log.info("Pruned %d idle client(s): %s", len(to_remove), to_remove)

    # ── Lifecycle ─────────────────────────────────────────────────────────────

    def start(self):
        threads = [
            threading.Thread(target=self._tcp_listener_thread,   name="tcp-listener",  daemon=True),
            threading.Thread(target=self._udp_listener_thread,   name="udp-listener",  daemon=True),
            threading.Thread(target=self._summary_printer_thread, name="summary-print", daemon=True),
        ]
        for t in threads:
            t.start()
        log.info("TelemetryServer started. Press Ctrl+C to stop.")

        try:
            while True:
                time.sleep(1)
        except KeyboardInterrupt:
            log.info("Shutting down…")
            self.running.clear()
            self.executor.shutdown(wait=False)
            for t in threads:
                t.join(timeout=3)
            log.info("Server stopped.")


# ── Entry point ───────────────────────────────────────────────────────────────

if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Secure UDP Telemetry Server",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    parser.add_argument("--host",    default="0.0.0.0",            help="Bind address")
    parser.add_argument("--port",    type=int, default=9000,        help="Bind port (shared TCP+UDP)")
    parser.add_argument("--cert",    default="../certs/server.crt", help="Path to TLS certificate (PEM)")
    parser.add_argument("--key",     default="../certs/server.key", help="Path to TLS private key (PEM)")
    parser.add_argument("--metrics", default=None,                  help="CSV file path for benchmark metrics output")
    parser.add_argument("--window",  type=int, default=100,         help="Rolling window size for per-client stats")
    args = parser.parse_args()

    TelemetryServer(args.host, args.port, args.cert, args.key, args.metrics, args.window).start()
