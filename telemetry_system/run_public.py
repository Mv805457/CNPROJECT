"""
run_public.py — Launches the Streamlit dashboard AND a public tunnel simultaneously.
Supports Cloudflare Tunnel (cloudflared) or Tunnelmole.

Usage:
    python run_public.py               # auto-tries cloudflared, then tunnelmole
    python run_public.py --tunnel cf   # Cloudflare only
    python run_public.py --tunnel tm   # Tunnelmole only
"""

import subprocess
import sys
import time
import argparse
import threading
import re
import signal
import os

STREAMLIT_PORT = 8501


def stream_output(proc, label):
    """Stream a subprocess's output to stdout with a label prefix."""
    for line in proc.stdout:
        print(f"[{label}] {line}", end="")


def start_streamlit():
    """Start the Streamlit dashboard in a subprocess."""
    print("Starting Streamlit dashboard on port", STREAMLIT_PORT)
    proc = subprocess.Popen(
        [sys.executable, "-m", "streamlit", "run", "web_dashboard.py",
         "--server.port", str(STREAMLIT_PORT),
         "--server.headless", "true",
         "--browser.gatherUsageStats", "false"],
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        cwd=str(__import__("pathlib").Path(__file__).parent),
    )
    return proc


def try_cloudflare():
    """Attempt to launch cloudflared quick tunnel and return (proc, url)."""
    try:
        proc = subprocess.Popen(
            ["cloudflared", "tunnel", "--url", f"http://localhost:{STREAMLIT_PORT}"],
            stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True,
        )
        url = None
        for line in proc.stdout:
            print("[cloudflared]", line, end="")
            # Cloudflare prints the public URL in the logs
            m = re.search(r"https://[\w-]+\.trycloudflare\.com", line)
            if m:
                url = m.group(0)
                print(f"\n{'='*60}")
                print(f"  🌐 PUBLIC URL : {url}")
                print(f"{'='*60}\n")
                # Keep streaming remaining output in background
                threading.Thread(target=stream_output, args=(proc, "CF"), daemon=True).start()
                return proc, url
        return proc, None
    except FileNotFoundError:
        return None, None


def try_tunnelmole():
    """Attempt to launch tunnelmole and return (proc, url)."""
    try:
        proc = subprocess.Popen(
            ["npx", "tunnelmole", str(STREAMLIT_PORT)],
            stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True,
            shell=True,
        )
        url = None
        for line in proc.stdout:
            print("[tunnelmole]", line, end="")
            m = re.search(r"https?://[^\s]+\.tunnelmole\.net", line)
            if m:
                url = m.group(0)
                print(f"\n{'='*60}")
                print(f"  🌐 PUBLIC URL : {url}")
                print(f"{'='*60}\n")
                threading.Thread(target=stream_output, args=(proc, "TM"), daemon=True).start()
                return proc, url
        return proc, None
    except FileNotFoundError:
        return None, None


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--tunnel", choices=["cf", "tm", "auto"], default="auto",
                        help="cf=cloudflared, tm=tunnelmole, auto=try both")
    args = parser.parse_args()

    # Start Streamlit
    st_proc = start_streamlit()
    st_thread = threading.Thread(target=stream_output, args=(st_proc, "Streamlit"), daemon=True)
    st_thread.start()

    print("Waiting for Streamlit to boot...")
    time.sleep(4)

    # Start tunnel
    tunnel_proc = None
    if args.tunnel in ("cf", "auto"):
        print("Trying Cloudflare Tunnel (cloudflared)...")
        tunnel_proc, url = try_cloudflare()
        if url:
            print(f"✅ Cloudflare tunnel active: {url}")
        elif args.tunnel == "cf":
            print("❌ cloudflared not found. Install from https://developers.cloudflare.com/cloudflare-one/connections/connect-networks/downloads/")

    if not tunnel_proc and args.tunnel in ("tm", "auto"):
        print("Trying Tunnelmole...")
        tunnel_proc, url = try_tunnelmole()
        if url:
            print(f"✅ Tunnelmole tunnel active: {url}")
        else:
            print("❌ Tunnelmole not found. Run:  npm install -g tunnelmole")

    if not tunnel_proc:
        print("\n⚠  No tunnel started. Dashboard is available locally at:")
        print(f"   http://localhost:{STREAMLIT_PORT}")
        print("\nInstall one of the tunnel tools and retry.")

    print("\nPress Ctrl+C to stop everything.\n")

    try:
        st_proc.wait()
    except KeyboardInterrupt:
        print("\nShutting down...")
        st_proc.terminate()
        if tunnel_proc:
            tunnel_proc.terminate()


if __name__ == "__main__":
    main()
