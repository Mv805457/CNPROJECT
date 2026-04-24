"""
telemetry_system/common/packet.py
===================================
Shared binary packet format used by both the server and client.

Packet wire format (network/big-endian byte order):
  [seq_no:     uint32  4 B]
  [client_id:  uint16  2 B]
  [timestamp:  float64 8 B]
  [payload_len:uint16  2 B]
  [sensor_type:uint8   1 B]
  [sensor_value:float32 4 B]
  [checksum:   uint16  2 B]   ← simple 16-bit additive checksum of all preceding bytes
"""

import struct
import time

# '!' = network byte order (big-endian)
# I=uint32, H=uint16, d=float64, B=uint8, f=float32
PACKET_FORMAT = "!IHdHBf"
PACKET_SIZE   = struct.calcsize(PACKET_FORMAT + "H")  # includes trailing checksum
PAYLOAD_LEN   = 5  # 1 byte sensor_type + 4 bytes sensor_value


def calculate_checksum(data: bytes) -> int:
    """Return a simple 16-bit additive checksum over *data*."""
    total = 0
    for byte in data:
        total = (total + byte) & 0xFFFF
    return total


def create_packet(seq_no: int, client_id: int, sensor_type: int, sensor_value: float) -> bytes:
    """
    Assemble a complete binary telemetry packet.

    The current wall-clock time is embedded as the packet timestamp so that the
    server can compute end-to-end transit latency on arrival.

    Returns the packed bytes including the trailing checksum.
    """
    timestamp   = time.time()
    packet_data = struct.pack(PACKET_FORMAT,
                              seq_no, client_id, timestamp,
                              PAYLOAD_LEN, sensor_type, sensor_value)
    checksum    = calculate_checksum(packet_data)
    return packet_data + struct.pack("!H", checksum)


def parse_packet(packet_bytes: bytes) -> dict:
    """
    Parse a raw telemetry packet and return its fields as a dictionary.

    Raises ``ValueError`` if the packet is too short or the checksum does not match.
    """
    if len(packet_bytes) < PACKET_SIZE:
        raise ValueError(
            f"Packet too short: got {len(packet_bytes)} bytes, expected {PACKET_SIZE}"
        )

    packet_data       = packet_bytes[:-2]
    expected_checksum = calculate_checksum(packet_data)

    unpacked                  = struct.unpack(PACKET_FORMAT + "H", packet_bytes[:PACKET_SIZE])
    *data_fields, recv_chksum = unpacked

    if expected_checksum != recv_chksum:
        raise ValueError(
            f"Checksum mismatch: expected {expected_checksum:#06x}, got {recv_chksum:#06x}"
        )

    return {
        "seq_no":       data_fields[0],
        "client_id":    data_fields[1],
        "timestamp":    data_fields[2],
        "payload_len":  data_fields[3],
        "sensor_type":  data_fields[4],
        "sensor_value": data_fields[5],
    }
