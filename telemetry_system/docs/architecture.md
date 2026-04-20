# System Architecture & Protocol Spec

## Architecture Diagram

```ascii
+-------------------+                          +--------------------+
|                   |   TCP TLS Handshake      |                    |
| Telemetry Client  |------------------------->| Telemetry Server   |
|                   |  Sends unencrypted ID    | (Port 9000 config) |
| (Generates mocked |<-------------------------|                    |
|  sensor data)     |  Returns 32B AES Key     | - TCP Thread       |
|                   |                          | - UDP Thread       |
|                   |   UDP Stream (AES-GCM)   | - Aggregator Thread|
+---------+---------+------------------------->|                    |
          |           Prepends unencrypted ID  +---------+----------+
          |           Encrypted payload                  |
          |                                              |
          v                                              v
+-------------------+                          +--------------------+
| 10 iterations/sec |                          | Validates Sequence |
| Default config    |                          | Cleans inactive    |
+-------------------+                          +--------------------+
```

## Binary Packet Format

All multi-byte numeric fields are packed using network byte order (Big-Endian).

| Field Name     | Type    | Size (Bytes) | Description                                  |
|----------------|---------|--------------|----------------------------------------------|
| `seq_no`       | uint32  | 4            | Incremental sequence tracker for lost gaps   |
| `client_id`    | uint16  | 2            | Numerical ID of the telemetry producer       |
| `timestamp`    | float64 | 8            | Epoch timestamp of packet creation           |
| `payload_len`  | uint16  | 2            | Fixed at 5 (Sensor type + Float value)       |
| `sensor_type`  | uint8   | 1            | 1=Temp, 2=Pres, 3=Hum etc.                   |
| `sensor_value` | float32 | 4            | Numerical reading output                     |
| `checksum`     | uint16  | 2            | Simple modulo-65536 summation of prior fields|

*Total Unencrypted Packet Length: 23 Bytes*

When transmitted via UDP, the payload is wrapped iteratively:
**Wire Payload (`wrapped_payload`)**:
`[Client ID: 2 Bytes Unencrypted] + [AES-GCM Nonce: 12 Bytes] + [AES-GCM Ciphertext of 23-byte Packet: 39 bytes]`
