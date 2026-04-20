# Telemetry Collection and Aggregation System

A high-performance Python application showcasing raw network socket utilization, hybrid cryptographic protocols, and multithreaded stream processing.

## Installation & Dependencies

Requires Python 3.8+.
```bash
pip install cryptography matplotlib psutil pandas
```

## Creating Self-Signed Certificates

Create testing keys securely by generating an X509 x.509 cert:
```bash
cd telemetry_system/certs
openssl req -x509 -newkey rsa:4096 -keyout server.key -out server.crt -days 365 -nodes
```
When prompted for certificate parameters, defaults are acceptable for local tests.

## Running Instructions

### 1. Launch Server
The server manages client connections over TCP TLS, then pivots to UDP for encrypted ingest.
```bash
cd telemetry_system/server
python server.py --host 127.0.0.1 --port 9000 --cert ../certs/server.crt --key ../certs/server.key
```

### 2. Launch Client
The client will begin streaming mocked temperature telemetry at the target rate (msgs/sec).
```bash
cd telemetry_system/client
python client.py --host 127.0.0.1 --port 9000 --client-id 1 --rate 15.0
```

### 3. Run Benchmarks
A multiprocessing benchmark execution spawns scaled tests (1 to 50 concurrent clients).
```bash
cd telemetry_system/benchmarks
python benchmark.py --duration 15
python plot_results.py
```

## Design Decisions

### Why UDP?
Telemetry datastreams are high-volume and continuously superseded. Missing a temperature reading from 3 milliseconds ago is irrelevant when a new reading arrives immediately after; TCP's retransmission and head-of-line blocking actively harm the real-time currency of the data. UDP guarantees raw minimal-overhead pipelines.

### Why Hybrid SSL/TLS?
UDP lacks built-in capability for stateful session establishment or standard TLS contexts. By using a brief TCP connect, we securely leverage battle-tested TLS handshakes to verify the server identity and distribute a high-entropy 256-bit AES-GCM session key. The TCP socket is then dropped. This decouples the heavy expensive PKI math from the fast-path critical UDP pumping line, gaining perfect confidentiality over a stateless protocol.

### Sequence Tracking
Each message carries an incrementing `seq_no`. By maintaining the `last_seen_seq` per client ID within the Server Aggregator dictionary, the server detects mathematical gaps between sequences. 
Gaps < 0 are dropped mathematically as stale/duplicate packets.
Gaps > 1 are added immediately to the client's `packets_lost` statistic to formulate real-time SLA degradation alerting.
