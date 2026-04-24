# Telemetry Collection and Aggregation System

A high-performance Python application showcasing raw network socket programming, hybrid cryptographic protocols, and multithreaded stream processing.

## Project Structure

```
telemetry_system/
├── common/              # Shared modules (imported by both server and client)
│   ├── packet.py        # Binary packet format, create/parse, checksum
│   └── ssl_utils.py     # TLS context factories + AES-256-GCM helpers
├── server/
│   ├── server.py        # Main server (TCP/TLS handshake + UDP ingestion)
│   └── aggregator.py    # Per-client state: sequence tracking, latency, stats
├── client/
│   └── client.py        # Telemetry client (handshake + UDP stream)
├── benchmarks/
│   ├── benchmark.py     # Automated scalability benchmark (1–50 clients)
│   └── plot_results.py  # Visualise benchmark CSV outputs
├── certs/               # Auto-generated TLS certificate (git-ignored)
├── dashboard.py         # Local Tkinter desktop dashboard
├── web_dashboard.py     # Streamlit browser-based dashboard
├── run_public.py        # Launch Streamlit + Cloudflare/Tunnelmole public tunnel
└── generate_certs.py    # Self-signed RSA-4096 certificate generator
```

## Installation

Requires **Python 3.10+**.

```bash
pip install cryptography matplotlib psutil pandas streamlit customtkinter
```

Or use the provided requirements file:

```bash
pip install -r telemetry_system/requirements.txt
```

## Step 0 — Generate Certificates

Run once before starting the server for the first time.  
The script always writes into `telemetry_system/certs/` regardless of your working directory:

```bash
python telemetry_system/generate_certs.py
```

## Running Instructions

### Option A — Tkinter Desktop Dashboard (recommended)

```bash
python telemetry_system/dashboard.py
```

The dashboard lets you start/stop the server and launch multiple clients all from one window, with a live colour-coded log and per-client stats table.

---

### Option B — Streamlit Web Dashboard

```bash
cd telemetry_system
streamlit run web_dashboard.py
```

Opens at `http://localhost:8501`.  
To share publicly over the internet (e.g. for demos):

```bash
python telemetry_system/run_public.py          # auto-tries cloudflared then tunnelmole
python telemetry_system/run_public.py --tunnel cf   # Cloudflare only
python telemetry_system/run_public.py --tunnel tm   # Tunnelmole only
```

---

### Option C — Command Line

#### 1. Start the server

```bash
cd telemetry_system/server
python server.py --host 127.0.0.1 --port 9000 \
                 --cert ../certs/server.crt --key ../certs/server.key
```

#### 2. Start one or more clients

```bash
cd telemetry_system/client
python client.py --host 127.0.0.1 --port 9000 --client-id 1 --rate 15.0
python client.py --host 127.0.0.1 --port 9000 --client-id 2 --rate 10.0
```

| Flag | Default | Description |
|------|---------|-------------|
| `--host` | `127.0.0.1` | Server address |
| `--port` | `9000` | Server port |
| `--client-id` | *(required)* | Unique 16-bit integer identifier |
| `--rate` | `10.0` | Packets per second |
| `--duration` | `0` (∞) | Stop after N seconds |

#### 3. Run benchmarks

```bash
cd telemetry_system/benchmarks
python benchmark.py --duration 15   # runs 1, 5, 10, 20, 50 client steps
python plot_results.py               # generates benchmark_results.png
```

---

## Design Decisions

### Why UDP for the telemetry stream?

Telemetry datastreams are high-volume and continuously superseded.  
Missing a temperature reading from 3 ms ago is irrelevant when a fresh reading arrives immediately after. TCP's retransmission and head-of-line blocking actively harm the real-time currency of the data. UDP provides a minimal-overhead, raw pipeline.

### Why Hybrid TCP/TLS + UDP?

UDP has no built-in mechanism for stateful session establishment or standard TLS contexts.  
By using a brief TCP+TLS connect, we securely leverage battle-tested PKI math to authenticate the server and distribute a high-entropy 256-bit AES-GCM session key. The TCP socket is then dropped. This completely decouples the expensive handshake from the fast-path UDP data plane.

### Sequence Tracking & Loss Detection

Each datagram carries an incrementing `seq_no`. The server's `ClientState` aggregator tracks the last seen sequence number per client and counts any gap `> 1` as lost packets in real-time. Out-of-order and duplicate arrivals (gap `≤ 0`) are detected and ignored to prevent false loss counts.

### Thread Safety

The server uses a single `threading.Lock` around the shared `client_states` / `client_keys` dictionaries. All I/O operations (decrypt, file write, logging) happen **outside** the lock to minimise contention under burst load. The thread pool executor is bounded to prevent runaway thread counts.
