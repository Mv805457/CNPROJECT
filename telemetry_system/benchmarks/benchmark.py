"""
telemetry_system/benchmarks/benchmark.py
==========================================
Automated scalability benchmark for the Telemetry Server.

Spawns the server once per test run, ramps up the given number of clients,
monitors server resource usage in real-time, then tears everything down cleanly.

Usage:
    cd telemetry_system/benchmarks
    python benchmark.py --duration 15
"""

import subprocess
import time
import psutil
import csv
import sys
import os
import threading
import argparse
from pathlib import Path

# Resolve sibling directories regardless of where the script is invoked from
BENCH_DIR  = Path(__file__).resolve().parent
SERVER_PY  = BENCH_DIR.parent / "server"  / "server.py"
CLIENT_PY  = BENCH_DIR.parent / "client"  / "client.py"
CERT_FILE  = BENCH_DIR.parent / "certs"   / "server.crt"
KEY_FILE   = BENCH_DIR.parent / "certs"   / "server.key"


def measure_server_resources(server_proc: subprocess.Popen,
                              stop_event:  threading.Event,
                              output_csv:  str) -> None:
    """Sample CPU % and RSS memory of *server_proc* once per second into *output_csv*."""
    try:
        p = psutil.Process(server_proc.pid)
    except psutil.NoSuchProcess:
        return

    with open(output_csv, "w", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(["time", "cpu_percent", "mem_mb"])

        while not stop_event.is_set():
            try:
                cpu = p.cpu_percent(interval=1.0)
                mem = p.memory_info().rss / (1024 * 1024)
                writer.writerow([time.time(), cpu, mem])
                f.flush()  # Ensure data is on disk even if killed mid-run
            except psutil.NoSuchProcess:
                break
            except Exception:
                break


def run_benchmark(num_clients: int, rate: float, duration: int) -> None:
    print(f"\n{'─'*60}")
    print(f"  Benchmark: {num_clients} client(s) @ {rate} pkt/s for {duration}s")
    print(f"{'─'*60}")

    server_metrics = str(BENCH_DIR / f"server_stats_{num_clients}_clients.csv")
    sys_metrics    = str(BENCH_DIR / f"sys_usage_{num_clients}_clients.csv")

    # Start server with certificate paths and metrics output
    server_cmd = [
        sys.executable, str(SERVER_PY),
        "--cert",    str(CERT_FILE),
        "--key",     str(KEY_FILE),
        "--metrics", server_metrics,
    ]
    server_proc = subprocess.Popen(
        server_cmd,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
    )
    time.sleep(2)  # Allow the server to bind before clients connect

    # Start resource monitor thread
    stop_event     = threading.Event()
    monitor_thread = threading.Thread(
        target=measure_server_resources,
        args=(server_proc, stop_event, sys_metrics),
        daemon=True,
    )
    monitor_thread.start()

    # Launch clients with a small stagger to avoid TLS handshake thundering-herd
    clients = []
    for i in range(1, num_clients + 1):
        log_file = open(BENCH_DIR / f"client_{num_clients}_{i}.log", "w")
        c_cmd = [
            sys.executable, str(CLIENT_PY),
            "--client-id", str(i),
            "--rate",      str(rate),
            "--duration",  str(duration),
        ]
        clients.append(
            subprocess.Popen(c_cmd, stdout=log_file, stderr=log_file)
        )
        time.sleep(0.05)  # Stagger to prevent TLS accept backlog spikes

    # Wait for all clients to finish their run
    for c in clients:
        c.wait()

    print(f"  All {num_clients} client(s) finished. Stopping server…")
    stop_event.set()
    monitor_thread.join(timeout=5)

    server_proc.terminate()
    server_proc.wait(timeout=5)
    print("  Done.\n")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Telemetry server scalability benchmark",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    parser.add_argument("--duration", type=int, default=15,
                        help="Test duration in seconds per client-count step")
    parser.add_argument("--rate",     type=float, default=50.0,
                        help="Packets per second per client")
    args = parser.parse_args()

    if not CERT_FILE.exists() or not KEY_FILE.exists():
        print("ERROR: Certificates not found.")
        print(f"  Expected: {CERT_FILE}")
        print("  Run:  python telemetry_system/generate_certs.py  first.")
        sys.exit(1)

    client_counts = [1, 5, 10, 20, 50]
    for count in client_counts:
        run_benchmark(count, rate=args.rate, duration=args.duration)

    print("All benchmarks complete.  Run plot_results.py to visualize.")
