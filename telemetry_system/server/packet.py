import struct
import time

# Packet format structure:
# [seq_no: uint32][client_id: uint16][timestamp: float64][payload_len: uint16]
# [sensor_type: uint8][sensor_value: float32][checksum: uint16]
# '!' denotes network byte order (big-endian)
# 'I' = 4 bytes, uint32
# 'H' = 2 bytes, uint16
# 'd' = 8 bytes, float64
# 'B' = 1 byte, uint8
# 'f' = 4 bytes, float32
PACKET_FORMAT = "!IHdHBf"
PACKET_SIZE = struct.calcsize(PACKET_FORMAT + "H") # Includes the checksum 2-bytes
PAYLOAD_LEN = 5 # 1 byte sensor type + 4 bytes sensor value

def calculate_checksum(data: bytes) -> int:
    """
    Calculate a simple 16-bit checksum by summing the bytes.
    """
    checksum = 0
    for byte in data:
        checksum = (checksum + byte) & 0xFFFF
    return checksum

def create_packet(seq_no: int, client_id: int, sensor_type: int, sensor_value: float) -> bytes:
    """
    Produce a complete binary packet from the given fields, 
    calculating the timestamp and checksum automatically.
    """
    timestamp = time.time()
    packet_data = struct.pack(PACKET_FORMAT, seq_no, client_id, timestamp, PAYLOAD_LEN, sensor_type, sensor_value)
    checksum = calculate_checksum(packet_data)
    return packet_data + struct.pack("!H", checksum)

def parse_packet(packet_bytes: bytes) -> dict:
    """
    Parse a raw packet binary, perform checksum verification,
    and return a dictionary of the packet contents.
    Raises ValueError on length or checksum mismatch.
    """
    if len(packet_bytes) < PACKET_SIZE:
        raise ValueError(f"Packet too short: got {len(packet_bytes)} bytes, expected {PACKET_SIZE}")
    
    packet_data = packet_bytes[:-2]
    expected_checksum = calculate_checksum(packet_data)
    
    unpacked = struct.unpack(PACKET_FORMAT + "H", packet_bytes)
    *data_fields, received_checksum = unpacked
    
    if expected_checksum != received_checksum:
        raise ValueError(f"Checksum mismatch: expected {expected_checksum}, got {received_checksum}")
        
    return {
        "seq_no": data_fields[0],
        "client_id": data_fields[1],
        "timestamp": data_fields[2],
        "payload_len": data_fields[3],
        "sensor_type": data_fields[4],
        "sensor_value": data_fields[5]
    }
