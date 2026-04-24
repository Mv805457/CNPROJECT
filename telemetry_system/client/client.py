"""
telemetry_system/client/client.py
====================================
Secure UDP Telemetry Client.

Protocol:
  1. TCP+TLS handshake  → receives a 32-byte AES-256-GCM session key from the server.
  2. UDP stream         → sends encrypted, sequenced telemetry datagrams at the
                          configured rate until the optional duration elapses.

The client prepends its (unencrypted) 16-bit ``client_id`` to every UDP datagram
so the server can look up the corresponding session key before decryption.
"""

import socket
import ssl
import time
import argparse
import struct
import random
import sys
import os
import logging
from pathlib import Path

# ── Ensure telemetry_system/ is on sys.path so 'common' is importable ────────
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from common.packet   import create_packet
from common.ssl_utils import create_client_ssl_context, encrypt_udp_payload

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger(__name__)

_HANDSHAKE_RETRIES = 3
_HANDSHAKE_BACKOFF = 2.0  # seconds between retry attempts


class TelemetryClient:
    def __init__(self, host: str, port: int, client_id: int,
                 rate: float, duration: int):
        self.host      = host
        self.port      = port
        self.client_id = client_id
        self.rate      = rate
        self.duration  = duration
        self.session_key: bytes | None = None

    # ── Handshake ─────────────────────────────────────────────────────────────

    def perform_handshake(self) -> None:
        """
        Open a TLS-wrapped TCP connection to the server and exchange a session key.

        Retries up to ``_HANDSHAKE_RETRIES`` times with a fixed back-off delay
        so that transient network errors do not immediately kill the client.

        Raises ``RuntimeError`` if all attempts are exhausted.
        """
        context = create_client_ssl_context()
        last_exc = None

        for attempt in range(1, _HANDSHAKE_RETRIES + 1):
            tcp_sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            try:
                # Wrap the raw socket with TLS before connecting
                secure_sock = context.wrap_socket(tcp_sock, server_hostname=self.host)
                secure_sock.settimeout(10.0)
                secure_sock.connect((self.host, self.port))

                # Identify ourselves with our 16-bit client-id
                secure_sock.sendall(struct.pack("!H", self.client_id))

                # Receive the 32-byte AES-256-GCM session key
                key = b""
                while len(key) < 32:
                    chunk = secure_sock.recv(32 - len(key))
                    if not chunk:
                        raise ConnectionError("Server closed connection before sending full key.")
                    key += chunk

                self.session_key = key
                log.info("Client %d: secure session established.", self.client_id)
                return  # Success

            except Exception as exc:
                last_exc = exc
                log.warning(
                    "Client %d: handshake attempt %d/%d failed: %s",
                    self.client_id, attempt, _HANDSHAKE_RETRIES, exc,
                )
                if attempt < _HANDSHAKE_RETRIES:
                    time.sleep(_HANDSHAKE_BACKOFF)
            finally:
                tcp_sock.close()

        raise RuntimeError(
            f"Client {self.client_id}: all {_HANDSHAKE_RETRIES} handshake attempts failed."
        ) from last_exc

    # ── Telemetry stream ──────────────────────────────────────────────────────

    def stream_telemetry(self) -> None:
        """
        Continuously send encrypted UDP telemetry packets at ``self.rate`` packets/s.

        Each datagram is structured as::

            [ client_id (2 B, plaintext) ][ nonce (12 B) ][ ciphertext + auth-tag ]

        The unencrypted client-id prefix lets the server look up the session key
        for decryption without requiring per-datagram TLS overhead.

        Runs until ``self.duration`` seconds elapse (or forever if ``duration == 0``).
        """
        if self.session_key is None:
            raise RuntimeError("perform_handshake() must be called before stream_telemetry().")

        # UDP socket for the telemetry stream — same port as the TCP handshake
        udp_sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        interval = 1.0 / self.rate
        seq_no   = 0
        start    = time.time()
        dur_str  = "forever" if self.duration == 0 else f"{self.duration}s"

        log.info(
            "Client %d: streaming at %.1f pkt/s for %s → %s:%d",
            self.client_id, self.rate, dur_str, self.host, self.port,
        )

        try:
            while True:
                if self.duration > 0 and (time.time() - start) >= self.duration:
                    break

                # Simulate a temperature sensor reading (15–30 °C)
                sensor_type  = 1  # 1 = Temperature
                sensor_value = random.uniform(15.0, 30.0)

                plaintext       = create_packet(seq_no, self.client_id, sensor_type, sensor_value)
                encrypted_blob  = encrypt_udp_payload(self.session_key, plaintext)

                # Prepend plaintext client-id for server-side routing
                datagram = struct.pack("!H", self.client_id) + encrypted_blob
                udp_sock.sendto(datagram, (self.host, self.port))

                seq_no += 1
                time.sleep(interval)

        except KeyboardInterrupt:
            log.info("Client %d: interrupted by user.", self.client_id)
        finally:
            udp_sock.close()
            log.info("Client %d: sent %d packets total.", self.client_id, seq_no)


# ── Entry point ───────────────────────────────────────────────────────────────

if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Secure UDP Telemetry Client",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    parser.add_argument("--host",      default="127.0.0.1",  help="Server IP address")
    parser.add_argument("--port",      type=int, default=9000, help="Server port (TCP handshake + UDP stream)")
    parser.add_argument("--client-id", type=int, required=True, help="Unique 16-bit client identifier (1–65535)")
    parser.add_argument("--rate",      type=float, default=10.0, help="Packets per second to transmit")
    parser.add_argument("--duration",  type=int, default=0,    help="Run duration in seconds; 0 = run indefinitely")
    args = parser.parse_args()

    client = TelemetryClient(args.host, args.port, args.client_id, args.rate, args.duration)
    client.perform_handshake()
    client.stream_telemetry()
