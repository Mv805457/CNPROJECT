"""
Telemetry System — Streamlit Web Dashboard
============================================
A browser-based control panel for the Telemetry System.
Run:  streamlit run web_dashboard.py
Then tunnel publicly with Cloudflare or Tunnelmole.
"""

import streamlit as st
import subprocess
import threading
import queue
import sys
import time
import re
import os
import signal
from pathlib import Path
from collections import deque

# ─── Paths ──────────────────────────────────────────────────────────────────
BASE_DIR  = Path(__file__).resolve().parent
SERVER_PY = BASE_DIR / "server"  / "server.py"
CLIENT_PY = BASE_DIR / "client"  / "client.py"
GEN_CERTS = BASE_DIR / "generate_certs.py"
CERT_FILE = BASE_DIR / "certs"   / "server.crt"
KEY_FILE  = BASE_DIR / "certs"   / "server.key"
PYTHON    = sys.executable

# ─── Page config ────────────────────────────────────────────────────────────
st.set_page_config(
    page_title="Telemetry Dashboard",
    page_icon="📡",
    layout="wide",
    initial_sidebar_state="expanded",
)

# ─── Custom CSS ─────────────────────────────────────────────────────────────
st.markdown("""
<style>
@import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600&display=swap');

html, body, [class*="css"] { font-family: 'Inter', sans-serif; }

/* Dark background */
.stApp { background: #0d1117; color: #e6edf3; }

/* Metric cards */
[data-testid="metric-container"] {
    background: #161b22;
    border: 1px solid #30363d;
    border-radius: 10px;
    padding: 12px 16px;
}

/* Log box stylebase */
.log-box {
    background: #161b22;
    border: 1px solid #30363d;
    border-radius: 8px;
    padding: 14px;
    font-family: 'Consolas', monospace;
    font-size: 12px;
    height: 320px;
    overflow-y: auto;
    white-space: pre-wrap;
    color: #e6edf3;
    line-height: 1.6;
}
.log-info    { color: #8b949e; }
.log-ok      { color: #3fb950; }
.log-warn    { color: #d29922; }
.log-error   { color: #f85149; }
.log-accent  { color: #58a6ff; }

/* Buttons */
.stButton > button {
    border-radius: 8px;
    font-weight: 600;
    border: none;
    transition: opacity 0.2s;
}
.stButton > button:hover { opacity: 0.85; }

/* Sidebar */
[data-testid="stSidebar"] {
    background: #161b22;
    border-right: 1px solid #30363d;
}

/* Tabs */
[data-testid="stHorizontalBlock"] { gap: 8px !important; }

/* Section headers */
.section-head {
    color: #8b949e;
    font-size: 11px;
    font-weight: 600;
    letter-spacing: 0.08em;
    text-transform: uppercase;
    margin: 14px 0 6px 0;
}
</style>
""", unsafe_allow_html=True)

# ─── Shared State ────────────────────────────────────────────────────────────
# We keep processes and log buffers in session_state so they persist
# across Streamlit reruns (which happen on every widget interaction).

if "server_proc"   not in st.session_state: st.session_state.server_proc   = None
if "clients"       not in st.session_state: st.session_state.clients       = {}   # id -> proc
if "next_cid"      not in st.session_state: st.session_state.next_cid      = 1
if "log_lines"     not in st.session_state: st.session_state.log_lines     = deque(maxlen=250)
if "log_queue"     not in st.session_state: st.session_state.log_queue     = queue.Queue()
if "stats"         not in st.session_state: st.session_state.stats         = {}   # cid -> dict
if "server_active" not in st.session_state: st.session_state.server_active = 0

Q = st.session_state.log_queue

# ─── Helpers ─────────────────────────────────────────────────────────────────
SUMMARY_RE = re.compile(
    r"Client (\d+) \| Recv: (\d+) \| Lost: ([\d.]+)% \| Latency: ([\d.]+)"
)
ACTIVE_CLIENTS_RE = re.compile(
    r"SUMMARY \| Active Clients: (\d+)"
)

def classify(line: str) -> str:
    """
    Return the CSS class for a log line.

    Warns only on genuine loss (non-zero percentage), not on every stat line
    that happens to contain the word "lost".
    """
    l = line.lower()
    if "error" in l:
        return "log-error"
    # Only flag as warning if "warn" appears, or if there is a non-zero loss value.
    # Stat lines look like "Lost: 0.00%" — we should not warn those.
    if "warn" in l:
        return "log-warn"
    if "lost:" in l and "lost: 0.00%" not in l and "lost: 0%" not in l:
        return "log-warn"
    if "summary" in l or "done" in l:
        return "log-ok"
    if "started" in l:
        return "log-accent"
    return "log-info"

def html_log_line(line: str) -> str:
    ts = time.strftime("[%H:%M:%S]")
    cls = classify(line)
    safe = line.replace("&","&amp;").replace("<","&lt;").replace(">","&gt;")
    return f'<span class="{cls}">{ts} {safe}</span>'

def drain_queue():
    """Pull all pending lines from the shared queue into session_state.log_lines."""
    q = st.session_state.log_queue
    while True:
        try:
            line = q.get_nowait()
            st.session_state.log_lines.append(line)
            m = SUMMARY_RE.search(line)
            if m:
                cid, recv, loss, lat = m.groups()
                st.session_state.stats[cid] = {
                    "recv": int(recv), "loss": float(loss), "lat": float(lat)
                }
            m2 = ACTIVE_CLIENTS_RE.search(line)
            if m2:
                st.session_state.server_active = int(m2.group(1))
        except queue.Empty:
            break

def stream_proc(proc, prefix=""):
    """Background thread: read proc stdout and push to the shared queue."""
    try:
        for line in proc.stdout:
            Q.put(f"{prefix}{line.rstrip()}\n")
    except Exception:
        pass

def is_alive(proc) -> bool:
    return proc is not None and proc.poll() is None

# ─── Sidebar ─────────────────────────────────────────────────────────────────
with st.sidebar:
    st.markdown("## 📡 Telemetry Dashboard")
    st.divider()

    # ── Server config ────────────────────────────────────────────────────────
    st.markdown('<p class="section-head">Server Configuration</p>', unsafe_allow_html=True)
    srv_host = st.text_input("Host",      "127.0.0.1", key="srv_host")
    srv_port = st.text_input("Port",      "9000",       key="srv_port")
    srv_cert = st.text_input("Cert path", str(CERT_FILE), key="srv_cert")
    srv_key  = st.text_input("Key path",  str(KEY_FILE),  key="srv_key")

    col1, col2 = st.columns(2)
    with col1:
        if st.button("▶ Start Server", use_container_width=True,
                     disabled=is_alive(st.session_state.server_proc)):
            if not (Path(srv_cert).exists() and Path(srv_key).exists()):
                st.error("Certificates not found. Click 'Generate Certificates'.")
            else:
                cmd = [PYTHON, str(SERVER_PY),
                       "--host", srv_host, "--port", srv_port,
                       "--cert", srv_cert, "--key", srv_key]
                proc = subprocess.Popen(cmd, stdout=subprocess.PIPE,
                                        stderr=subprocess.STDOUT, text=True,
                                        cwd=str(BASE_DIR / "server"))
                st.session_state.server_proc = proc
                threading.Thread(target=stream_proc, args=(proc, "[SRV] "),
                                 daemon=True).start()
                Q.put(f"[SRV] Server started on {srv_host}:{srv_port}\n")
                st.rerun()
    with col2:
        if st.button("■ Stop", use_container_width=True,
                     disabled=not is_alive(st.session_state.server_proc)):
            st.session_state.server_proc.terminate()
            st.session_state.server_proc = None
            Q.put("[SRV] Server stopped.\n")
            st.rerun()

    st.divider()

    # ── Certificates ─────────────────────────────────────────────────────────
    st.markdown('<p class="section-head">Certificates</p>', unsafe_allow_html=True)
    certs_exist = CERT_FILE.exists() and KEY_FILE.exists()
    if certs_exist:
        st.success("✓ Certificates found")
    else:
        st.warning("No certificates found")

    if st.button("🔑 Generate Self-Signed Cert", use_container_width=True):
        with st.spinner("Generating RSA-4096 certificate…"):
            result = subprocess.run([PYTHON, str(GEN_CERTS)],
                                    cwd=str(BASE_DIR),
                                    capture_output=True, text=True)
            if result.returncode == 0:
                st.success("Certificates generated!")
                Q.put("[SYS] Certificates generated successfully.\n")
            else:
                st.error(result.stderr or result.stdout)
        st.rerun()

    st.divider()

    # ── Add Client ───────────────────────────────────────────────────────────
    st.markdown('<p class="section-head">Launch a Client</p>', unsafe_allow_html=True)
    cli_host = st.text_input("Client → Host",     "127.0.0.1", key="cli_host")
    cli_port = st.text_input("Client → Port",     "9000",       key="cli_port")
    cli_rate = st.slider("Rate (packets/s)",  1, 200, 10,       key="cli_rate")
    cli_dur  = st.number_input("Duration (0=∞)",  0, 3600, 0,  key="cli_dur")

    if st.button("＋ Launch Client", use_container_width=True, type="primary"):
        cid = st.session_state.next_cid
        st.session_state.next_cid += 1
        cmd = [PYTHON, str(CLIENT_PY),
               "--host", cli_host,
               "--port", cli_port,
               "--client-id", str(cid),
               "--rate", str(cli_rate),
               "--duration", str(cli_dur)]
        proc = subprocess.Popen(cmd, stdout=subprocess.PIPE,
                                 stderr=subprocess.STDOUT, text=True,
                                 cwd=str(BASE_DIR / "client"))
        st.session_state.clients[cid] = proc
        threading.Thread(target=stream_proc, args=(proc, f"[C{cid}] "),
                         daemon=True).start()
        Q.put(f"[SYS] Client {cid} launched → {cli_host}:{cli_port} @ {cli_rate}/s\n")
        st.rerun()

    active_local = sum(1 for p in st.session_state.clients.values() if is_alive(p))
    st.caption(f"Local clients launched: **{active_local}** / {len(st.session_state.clients)} total")

    if st.button("⛔ Stop All Clients", use_container_width=True):
        for cid, p in st.session_state.clients.items():
            if is_alive(p): p.terminate()
        Q.put("[SYS] All clients stopped.\n")
        st.rerun()

# ─── Main Content ─────────────────────────────────────────────────────────────
drain_queue()  # Pull latest log lines on every rerun

# Header row with server status pill
srv_alive  = is_alive(st.session_state.server_proc)
status_col, _, auto_col = st.columns([3, 5, 2])
with status_col:
    if srv_alive:
        st.markdown(
            '<span style="background:#1a3b2a;color:#3fb950;'
            'padding:4px 12px;border-radius:20px;font-size:13px;font-weight:600;">'
            '● Server Online</span>', unsafe_allow_html=True)
    else:
        st.markdown(
            '<span style="background:#3b1a1a;color:#f85149;'
            'padding:4px 12px;border-radius:20px;font-size:13px;font-weight:600;">'
            '● Server Offline</span>', unsafe_allow_html=True)

with auto_col:
    auto_refresh = st.checkbox("Auto-refresh (3s)", value=True)

# ── Metrics row ───────────────────────────────────────────────────────────────
m1, m2, m3, m4 = st.columns(4)
m1.metric("Server", "Online ✅" if srv_alive else "Offline ❌")
m2.metric("Active Server Clients", st.session_state.server_active if srv_alive else 0)
m3.metric("Local Process Count", sum(1 for p in st.session_state.clients.values() if is_alive(p)))

if st.session_state.stats:
    avg_loss = sum(s["loss"] for s in st.session_state.stats.values()) / len(st.session_state.stats)
    m4.metric("Avg Loss %", f"{avg_loss:.2f}%")
else:
    m4.metric("Avg Loss %", "—")

st.divider()

# ── Tabs ──────────────────────────────────────────────────────────────────────
tab_log, tab_clients, tab_stats = st.tabs(
    ["📋  Live Log", "👥  Connected Clients", "📊  Aggregated Stats"])

# ─ Tab 1: Live Log ───────────────────────────────────────────────────────────
with tab_log:
    col_head, col_clear = st.columns([8, 1])
    with col_clear:
        if st.button("🗑 Clear"):
            st.session_state.log_lines.clear()
            st.rerun()

    lines_html = "\n".join(html_log_line(l) for l in st.session_state.log_lines)
    st.markdown(f'<div class="log-box">{lines_html}</div>',
                unsafe_allow_html=True)

# ─ Tab 2: Clients ────────────────────────────────────────────────────────────
with tab_clients:
    if not st.session_state.clients:
        st.info("No clients launched yet. Use the sidebar to add one.")
    else:
        import pandas as pd
        rows = []
        for cid, proc in st.session_state.clients.items():
            alive = is_alive(proc)
            rows.append({
                "Client ID": cid,
                "Status": "🟢 Running" if alive else "🔴 Done/Stopped",
                "PID": proc.pid if proc else "—",
            })
        df = pd.DataFrame(rows)
        st.dataframe(df, use_container_width=True, hide_index=True)

        sel_id = st.number_input("Stop client by ID", min_value=1,
                                  max_value=st.session_state.next_cid - 1,
                                  step=1, key="stop_cid")
        if st.button("Stop Client"):
            proc = st.session_state.clients.get(sel_id)
            if proc and is_alive(proc):
                proc.terminate()
                Q.put(f"[SYS] Client {sel_id} stopped manually.\n")
                st.success(f"Client {sel_id} stopped.")
                st.rerun()

# ─ Tab 3: Stats ──────────────────────────────────────────────────────────────
with tab_stats:
    if not st.session_state.stats:
        st.info("Stats appear once the server starts printing summaries (every 10s).")
    else:
        import pandas as pd
        rows = []
        for cid, d in st.session_state.stats.items():
            rows.append({
                "Client": cid,
                "Packets Recv": d["recv"],
                "Loss %": f"{d['loss']:.2f}",
                "Avg Latency ms": f"{d['lat']:.2f}",
            })
        st.dataframe(pd.DataFrame(rows), use_container_width=True, hide_index=True)

        if st.button("↺ Refresh Stats"):
            st.rerun()

# ─── Auto-refresh ─────────────────────────────────────────────────────────────
if auto_refresh:
    time.sleep(3)
    st.rerun()
