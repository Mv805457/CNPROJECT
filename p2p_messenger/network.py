"""
p2p_messenger/network.py
==========================
UDP networking layer for the P2P Messenger.

Provides:
  - ``UDPServer`` — listens for HELLO / MESSAGE / DISCONNECT datagrams,
    tracks per-client sequence numbers, and fires callbacks on the caller's
    behalf.
  - ``UDPClient`` — sends HELLO to connect, sends MESSAGE datagrams with
    incrementing sequence numbers, and listens for ACK responses.

Both classes use a simple JSON-over-UDP protocol:

  HELLO      → {type: "HELLO"}
  ACCEPT     ← {type: "ACCEPT"}
  MESSAGE    → {type: "MESSAGE", seq: int, content: str}
  ACK        ← {type: "ACK", received: int, lost: int}
  DISCONNECT → {type: "DISCONNECT"}
"""

import socket
import threading
import json
import logging

log = logging.getLogger(__name__)

_RECV_BUF  = 65535
_RECV_DGRAM = 4096
_ACK_TIMEOUT = 5.0   # seconds; client waits this long for ACCEPT / ACK


class UDPServer:
    """
    UDP server that tracks connected peers and dispatches callbacks.

    Callbacks (all optional, set before calling ``start()``):
      - ``on_client_connected(ip: str, port: int)``
      - ``on_message(ip: str, port: int, content: str)``
      - ``on_stats_update(ip: str, port: int, stats: dict)``
      - ``on_error(message: str)``
    """

    def __init__(self, host: str = "0.0.0.0", port: int = 5000):
        self.host = host
        self.port = port
        self.sock: socket.socket | None = None
        self.running = False

        # clients[(ip, port)] = {"expected_seq": 1, "lost": 0, "received": 0}
        self.clients: dict[tuple, dict] = {}

        self.on_client_connected = None
        self.on_message          = None
        self.on_stats_update     = None
        self.on_error            = None

    def start(self) -> None:
        try:
            self.sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            self.sock.bind((self.host, self.port))
            self.running = True
            threading.Thread(target=self._listen_loop, daemon=True, name="udp-server").start()
        except Exception as exc:
            msg = f"Server start error: {exc}"
            log.error(msg)
            if self.on_error:
                self.on_error(msg)

    def _listen_loop(self) -> None:
        while self.running:
            try:
                data, addr = self.sock.recvfrom(_RECV_BUF)
                if not data:
                    continue
                try:
                    packet = json.loads(data.decode("utf-8"))
                except json.JSONDecodeError:
                    log.debug("Received malformed JSON from %s — ignored.", addr)
                    continue

                self._handle_packet(addr, packet)

            except OSError:
                break  # Socket was closed; exit cleanly
            except Exception as exc:
                log.warning("UDP server loop error: %s", exc)

    def _handle_packet(self, addr: tuple, packet: dict) -> None:
        ptype = packet.get("type")

        if ptype == "HELLO":
            self.clients[addr] = {"expected_seq": 1, "lost": 0, "received": 0}
            self._send(addr, {"type": "ACCEPT"})
            if self.on_client_connected:
                self.on_client_connected(addr[0], addr[1])

        elif ptype == "MESSAGE":
            if addr not in self.clients:
                self.clients[addr] = {"expected_seq": 1, "lost": 0, "received": 0}
                if self.on_client_connected:
                    self.on_client_connected(addr[0], addr[1])

            c   = self.clients[addr]
            seq = packet.get("seq", 1)

            if seq > c["expected_seq"]:
                c["lost"] += seq - c["expected_seq"]

            c["received"]    += 1
            c["expected_seq"] = max(c["expected_seq"], seq + 1)

            if self.on_message:
                self.on_message(addr[0], addr[1], packet.get("content", ""))
            if self.on_stats_update:
                self.on_stats_update(addr[0], addr[1], dict(c))

            self._send(addr, {"type": "ACK", "received": c["received"], "lost": c["lost"]})

        elif ptype == "DISCONNECT":
            self.clients.pop(addr, None)
            log.info("Client %s disconnected.", addr)

        else:
            log.debug("Unknown packet type %r from %s — ignored.", ptype, addr)

    def _send(self, addr: tuple, packet_dict: dict) -> None:
        try:
            self.sock.sendto(json.dumps(packet_dict).encode("utf-8"), addr)
        except Exception as exc:
            log.warning("Failed to send to %s: %s", addr, exc)

    def stop(self) -> None:
        self.running = False
        if self.sock:
            try:
                self.sock.close()
            except Exception:
                pass


class UDPClient:
    """
    UDP client that connects to a ``UDPServer`` and sends sequenced messages.

    Callbacks (all optional):
      - ``on_connected()``
      - ``on_ack(received: int, lost: int)``
      - ``on_error(message: str)``
    """

    def __init__(self):
        self.sock:        socket.socket | None = None
        self.server_addr: tuple | None         = None
        self.running      = False
        self.seq          = 1

        self.on_connected = None
        self.on_ack       = None
        self.on_error     = None

    def connect(self, ip: str, port: int | str) -> None:
        try:
            self.server_addr = (ip, int(port))
            self.sock        = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            self.sock.settimeout(_ACK_TIMEOUT)
            self.running     = True

            self._send({"type": "HELLO"})

            data, _ = self.sock.recvfrom(_RECV_DGRAM)
            resp     = json.loads(data.decode("utf-8"))

            if resp.get("type") == "ACCEPT":
                # Switch to a short non-blocking timeout for the listen loop
                self.sock.settimeout(5.0)
                if self.on_connected:
                    self.on_connected()
                threading.Thread(target=self._listen_loop, daemon=True, name="udp-client").start()
            else:
                if self.on_error:
                    self.on_error("Connection rejected or unexpected response.")

        except socket.timeout:
            if self.on_error:
                self.on_error("Connection timed out — server unreachable.")
        except Exception as exc:
            if self.on_error:
                self.on_error(f"Connection error: {exc}")

    def _listen_loop(self) -> None:
        while self.running:
            try:
                data, _ = self.sock.recvfrom(_RECV_DGRAM)
                packet  = json.loads(data.decode("utf-8"))
                if packet.get("type") == "ACK" and self.on_ack:
                    self.on_ack(packet.get("received", 0), packet.get("lost", 0))
            except socket.timeout:
                continue  # Normal — keep looping
            except OSError:
                break     # Socket closed
            except Exception as exc:
                log.debug("Client listen error: %s", exc)

    def send_message(self, text: str) -> bool:
        if not self.server_addr:
            return False
        ok = self._send({"type": "MESSAGE", "seq": self.seq, "content": text})
        if ok:
            self.seq += 1
        return ok

    def _send(self, packet_dict: dict) -> bool:
        try:
            self.sock.sendto(json.dumps(packet_dict).encode("utf-8"), self.server_addr)
            return True
        except Exception as exc:
            log.warning("Client send error: %s", exc)
            return False

    def disconnect(self) -> None:
        self.running = False
        if self.server_addr:
            try:
                self._send({"type": "DISCONNECT"})
            except Exception:
                pass
        if self.sock:
            try:
                self.sock.close()
            except Exception:
                pass
