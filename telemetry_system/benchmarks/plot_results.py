"""
telemetry_system/benchmarks/plot_results.py
=============================================
Visualise benchmark results produced by benchmark.py.

Reads the per-client-count CSVs and produces a two-panel figure:
  Left  — Throughput (packets/s) vs number of clients
  Right — Average packet-loss rate (%) vs number of clients

Usage:
    cd telemetry_system/benchmarks
    python plot_results.py
"""

import pandas as pd
import matplotlib.pyplot as plt
import os
import argparse
from pathlib import Path

BENCH_DIR = Path(__file__).resolve().parent


def plot_benchmarks(client_counts: list[int], output: str) -> None:
    throughputs = []
    loss_rates  = []

    for count in client_counts:
        file_path = BENCH_DIR / f"server_stats_{count}_clients.csv"
        if not file_path.exists():
            print(f"  Skipping {count} clients: {file_path.name} not found.")
            continue

        df = pd.read_csv(file_path)
        if df.empty:
            print(f"  Skipping {count} clients: CSV is empty.")
            continue

        # ── Throughput ──────────────────────────────────────────────────────
        # 'received' is a cumulative counter that grows across log intervals.
        # Using sum() would double-count every row except the first.
        # Correct approach: total packets = last value − first value per client,
        # divided by the elapsed time window.
        total_recv = 0
        for cid, group in df.groupby("client_id"):
            total_recv += group["received"].iloc[-1] - group["received"].iloc[0]

        time_span = df["timestamp_epoch"].max() - df["timestamp_epoch"].min()
        duration  = time_span if time_span > 0 else 10.0
        throughputs.append((count, total_recv / duration))

        # ── Loss rate ───────────────────────────────────────────────────────
        avg_loss = df["loss_pct"].mean()
        loss_rates.append((count, avg_loss))

    if not throughputs:
        print("No data found to plot.  Run benchmark.py first.")
        return

    x_t, y_t = zip(*throughputs)
    x_l, y_l = zip(*loss_rates)

    fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(11, 5))
    fig.suptitle("Telemetry Server Benchmark Results", fontsize=13, fontweight="bold")

    ax1.plot(x_t, y_t, marker="o", linewidth=2, color="#2196F3")
    ax1.set_title("Throughput vs Client Count")
    ax1.set_xlabel("Number of Clients")
    ax1.set_ylabel("Throughput (packets / s)")
    ax1.grid(True, alpha=0.3)
    ax1.set_xticks(x_t)

    ax2.plot(x_l, y_l, marker="x", linewidth=2, linestyle="--", color="#F44336")
    ax2.set_title("Packet-Loss Rate vs Client Count")
    ax2.set_xlabel("Number of Clients")
    ax2.set_ylabel("Avg Loss Rate (%)")
    ax2.grid(True, alpha=0.3)
    ax2.set_xticks(x_l)

    plt.tight_layout()
    out_path = BENCH_DIR / output
    plt.savefig(out_path, dpi=150)
    print(f"Saved plot to {out_path}")
    plt.show()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Plot telemetry benchmark results",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    parser.add_argument("--output", default="benchmark_results.png",
                        help="Output image filename")
    args = parser.parse_args()

    plot_benchmarks([1, 5, 10, 20, 50], args.output)
