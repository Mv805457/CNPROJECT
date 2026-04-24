"""
telemetry_system/dashboard.py
===============================
Local Tkinter GUI Dashboard for the Telemetry System.

Provides a full desktop control panel:
  - Start / stop the server subprocess.
  - Launch / stop individual client subprocesses.
  - Live colour-coded log view.
  - Per-client stats table (parsed from server log output).
  - Certificate generation button.

All background-thread → widget interactions are routed through
``self.after(0, ...)`` to maintain Tkinter thread safety.
"""

import tkinter as tk
from tkinter import ttk, messagebox
import subprocess
import threading
import queue
import sys
import time
import re
from pathlib import Path

# ─── Paths ───────────────────────────────────────────────────────────────────
BASE_DIR  = Path(__file__).resolve().parent          # telemetry_system/
SERVER_PY = BASE_DIR / "server" / "server.py"
CLIENT_PY = BASE_DIR / "client" / "client.py"
CERT_FILE = BASE_DIR / "certs"  / "server.crt"
KEY_FILE  = BASE_DIR / "certs"  / "server.key"
GEN_CERTS = BASE_DIR / "generate_certs.py"

PYTHON = sys.executable

# ─── Colour Palette ───────────────────────────────────────────────────────────
BG        = "#0d1117"
PANEL     = "#161b22"
CARD      = "#21262d"
BORDER    = "#30363d"
ACCENT    = "#58a6ff"
GREEN     = "#3fb950"
RED       = "#f85149"
YELLOW    = "#d29922"
FG        = "#e6edf3"
FG_MUTED  = "#8b949e"
FONT_MONO = ("Consolas", 9)
FONT_UI   = ("Segoe UI", 10)
FONT_HEAD = ("Segoe UI Semibold", 11)


# ═════════════════════════════════════════════════════════════════════════════
class TelemetryDashboard(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("Telemetry Dashboard")
        self.geometry("1280x820")
        self.minsize(1100, 700)
        self.configure(bg=BG)

        self._server_proc:   subprocess.Popen | None = None
        self._clients:       dict[int, dict]         = {}  # cid → {proc}
        self._log_queue:     queue.Queue             = queue.Queue()
        self._next_cid:      int                     = 1
        self._server_active: int                     = 0

        self._setup_styles()
        self._build_ui()
        self._poll_logs()

    # ── Styles ────────────────────────────────────────────────────────────────
    def _setup_styles(self):
        s = ttk.Style(self)
        s.theme_use("clam")
        s.configure(".",                background=BG,    foreground=FG,    font=FONT_UI, borderwidth=0)
        s.configure("TFrame",           background=BG)
        s.configure("Card.TFrame",      background=CARD,  relief="flat")
        s.configure("Panel.TFrame",     background=PANEL, relief="flat")
        s.configure("TLabel",           background=BG,    foreground=FG,    font=FONT_UI)
        s.configure("Head.TLabel",      background=PANEL, foreground=FG,    font=FONT_HEAD)
        s.configure("Muted.TLabel",     background=CARD,  foreground=FG_MUTED, font=("Segoe UI", 9))
        s.configure("TEntry",           fieldbackground=CARD, foreground=FG, insertcolor=FG,
                    relief="flat", borderwidth=1)
        s.configure("TNotebook",        background=BG,    borderwidth=0)
        s.configure("TNotebook.Tab",    background=PANEL, foreground=FG_MUTED,
                    padding=[14, 6],    font=FONT_UI)
        s.map("TNotebook.Tab",
              background=[("selected", CARD)],
              foreground=[("selected", FG)])
        s.configure("Treeview",         background=CARD,  foreground=FG,
                    fieldbackground=CARD, rowheight=26,   borderwidth=0)
        s.configure("Treeview.Heading", background=PANEL, foreground=FG_MUTED, font=("Segoe UI", 9))
        s.map("Treeview", background=[("selected", ACCENT)])

        for name, bg, fg in [
            ("Green.TButton",   GREEN,  "#0d1117"),
            ("Red.TButton",     RED,    "#e6edf3"),
            ("Blue.TButton",    ACCENT, "#0d1117"),
            ("Neutral.TButton", CARD,   FG),
        ]:
            s.configure(name, background=bg, foreground=fg,
                        font=("Segoe UI Semibold", 9), relief="flat", padding=[10, 5])
            s.map(name, background=[("active", bg)])

    # ── UI Build ──────────────────────────────────────────────────────────────
    def _build_ui(self):
        hdr = tk.Frame(self, bg=PANEL, height=50)
        hdr.pack(fill="x", side="top")
        tk.Label(hdr, text="📡  Telemetry Dashboard",
                 bg=PANEL, fg=FG, font=("Segoe UI Semibold", 14)).pack(side="left", padx=18, pady=10)

        self._server_status_lbl = tk.Label(hdr, text="● Server Offline",
                                           bg=PANEL, fg=RED, font=("Segoe UI Semibold", 10))
        self._server_status_lbl.pack(side="right", padx=20)

        main = tk.PanedWindow(self, orient="horizontal", bg=BG, sashwidth=5, sashpad=0)
        main.pack(fill="both", expand=True)

        sidebar = tk.Frame(main, bg=PANEL, width=260)
        main.add(sidebar, minsize=240)
        self._build_sidebar(sidebar)

        nb_frame = tk.Frame(main, bg=BG)
        main.add(nb_frame, minsize=600)
        self._build_notebook(nb_frame)

    # ── Sidebar ───────────────────────────────────────────────────────────────
    def _build_sidebar(self, parent):
        def _section(text):
            tk.Label(parent, text=text, bg=PANEL, fg=FG_MUTED,
                     font=("Segoe UI", 8)).pack(anchor="w", padx=14, pady=(16, 4))

        def _sep():
            tk.Frame(parent, bg=BORDER, height=1).pack(fill="x", padx=10, pady=10)

        def _lbl_entry(frame, text, default, row):
            tk.Label(frame, text=text, bg=PANEL, fg=FG_MUTED,
                     font=("Segoe UI", 8)).grid(row=row, column=0, sticky="w", pady=3)
            v = tk.StringVar(value=default)
            e = tk.Entry(frame, textvariable=v,
                         bg=CARD, fg=FG, insertbackground=FG,
                         relief="flat", bd=1,
                         highlightbackground=BORDER, highlightthickness=1, width=18)
            e.grid(row=row, column=1, sticky="ew", padx=(6, 0), pady=3)
            frame.columnconfigure(1, weight=1)
            return v

        # ── Server config ─────────────────────────────────────────────────────
        _section("SERVER CONFIGURATION")
        cfg = tk.Frame(parent, bg=PANEL)
        cfg.pack(fill="x", padx=10)

        self._srv_host = _lbl_entry(cfg, "Host", "127.0.0.1",   0)
        self._srv_port = _lbl_entry(cfg, "Port", "9000",         1)
        self._srv_cert = _lbl_entry(cfg, "Cert", str(CERT_FILE), 2)
        self._srv_key  = _lbl_entry(cfg, "Key",  str(KEY_FILE),  3)

        _sep()

        btn_row = tk.Frame(parent, bg=PANEL)
        btn_row.pack(fill="x", padx=10)
        self._start_srv_btn = ttk.Button(btn_row, text="▶  Start Server",
                                         style="Green.TButton", command=self._start_server)
        self._start_srv_btn.pack(side="left", fill="x", expand=True, padx=(0, 4))
        self._stop_srv_btn = ttk.Button(btn_row, text="■  Stop",
                                        style="Red.TButton", command=self._stop_server,
                                        state="disabled")
        self._stop_srv_btn.pack(side="left")

        ttk.Button(parent, text="🔑  Generate Certificates",
                   style="Neutral.TButton", command=self._gen_certs).pack(fill="x", padx=10, pady=(10, 0))

        _sep()

        # ── Add Client ────────────────────────────────────────────────────────
        _section("ADD CLIENT")
        ccfg = tk.Frame(parent, bg=PANEL)
        ccfg.pack(fill="x", padx=10)

        defaults = ["127.0.0.1", "9000", "10", "0"]
        labels   = ["Host", "Port", "Rate/s", "Duration"]
        self._cli_vars = [_lbl_entry(ccfg, lbl, dflt, i)
                          for i, (lbl, dflt) in enumerate(zip(labels, defaults))]

        ttk.Button(parent, text="＋  Launch Client",
                   style="Blue.TButton", command=self._launch_client).pack(fill="x", padx=10, pady=(10, 0))

        self._active_lbl = tk.Label(parent, text="Server Clients: 0  |  Local: 0",
                                    bg=PANEL, fg=FG_MUTED, font=("Segoe UI", 9))
        self._active_lbl.pack(pady=(8, 0))

    # ── Notebook ──────────────────────────────────────────────────────────────
    def _build_notebook(self, parent):
        nb = ttk.Notebook(parent)
        nb.pack(fill="both", expand=True)

        for title, builder in [
            ("  📋 Live Log  ",  self._build_log_tab),
            ("  👥 Clients  ",   self._build_clients_tab),
            ("  📊 Stats  ",     self._build_stats_tab),
        ]:
            tab = tk.Frame(nb, bg=BG)
            nb.add(tab, text=title)
            builder(tab)

    # ── Log Tab ───────────────────────────────────────────────────────────────
    def _build_log_tab(self, parent):
        toolbar = tk.Frame(parent, bg=BG)
        toolbar.pack(fill="x", padx=10, pady=(8, 4))
        tk.Label(toolbar, text="Server output", bg=BG, fg=FG_MUTED,
                 font=("Segoe UI", 9)).pack(side="left")
        ttk.Button(toolbar, text="🗑  Clear", style="Neutral.TButton",
                   command=lambda: self._log_box.delete("1.0", "end")).pack(side="right")

        self._log_box = tk.Text(parent, bg=CARD, fg=FG, font=FONT_MONO,
                                relief="flat", wrap="word", state="disabled",
                                insertbackground=FG, selectbackground=ACCENT)
        self._log_box.pack(fill="both", expand=True, padx=10, pady=(0, 10))

        self._log_box.tag_config("INFO",    foreground=FG_MUTED)
        self._log_box.tag_config("WARNING", foreground=YELLOW)
        self._log_box.tag_config("ERROR",   foreground=RED)
        self._log_box.tag_config("OK",      foreground=GREEN)
        self._log_box.tag_config("ACCENT",  foreground=ACCENT)

    # ── Clients Tab ───────────────────────────────────────────────────────────
    def _build_clients_tab(self, parent):
        cols   = ("ID", "Host", "Port", "Rate", "Duration", "Status")
        widths = [60, 140, 70, 70, 80, 120]
        self._client_tree = ttk.Treeview(parent, columns=cols, show="headings", height=20)
        for col, w in zip(cols, widths):
            self._client_tree.heading(col, text=col)
            self._client_tree.column(col, width=w, anchor="center")
        self._client_tree.pack(fill="both", expand=True, padx=10, pady=10)

        btn_row = tk.Frame(parent, bg=BG)
        btn_row.pack(fill="x", padx=10, pady=(0, 10))
        ttk.Button(btn_row, text="⛔ Stop Selected",
                   style="Red.TButton", command=self._stop_selected_client).pack(side="left", padx=(0, 8))
        ttk.Button(btn_row, text="🔄 Stop All Clients",
                   style="Neutral.TButton", command=self._stop_all_clients).pack(side="left")

    # ── Stats Tab ─────────────────────────────────────────────────────────────
    def _build_stats_tab(self, parent):
        info = tk.Frame(parent, bg=BG)
        info.pack(fill="x", padx=12, pady=10)
        tk.Label(info, text="Parsed from live server log — refreshes every 5 s",
                 bg=BG, fg=FG_MUTED, font=("Segoe UI", 9)).pack(side="left")
        ttk.Button(info, text="↺  Refresh", style="Neutral.TButton",
                   command=self._refresh_stats).pack(side="right")

        cols   = ("Client", "Recv", "Lost%", "Latency ms")
        widths = [80, 100, 80, 120]
        self._stats_tree = ttk.Treeview(parent, columns=cols, show="headings", height=20)
        for col, w in zip(cols, widths):
            self._stats_tree.heading(col, text=col)
            self._stats_tree.column(col, width=w, anchor="center")
        self._stats_tree.pack(fill="both", expand=True, padx=10, pady=(0, 10))

        self._stats_data: dict = {}
        self.after(5000, self._auto_refresh_stats)

    # ═════════════════════════════════════════════════════════════════════════
    # Server control
    # ═════════════════════════════════════════════════════════════════════════
    def _start_server(self):
        if self._server_proc and self._server_proc.poll() is None:
            self._append_log("Server is already running.\n", "WARNING")
            return

        host = self._srv_host.get()
        port = self._srv_port.get()
        cert = self._srv_cert.get()
        key  = self._srv_key.get()

        if not Path(cert).exists() or not Path(key).exists():
            messagebox.showerror(
                "Missing Certificates",
                "server.crt / server.key not found.\n"
                "Click 'Generate Certificates' first."
            )
            return

        cmd = [PYTHON, str(SERVER_PY),
               "--host", host, "--port", port,
               "--cert", cert, "--key",  key]
        try:
            self._server_proc = subprocess.Popen(
                cmd,
                stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                text=True, cwd=str(BASE_DIR / "server"),
            )
        except Exception as exc:
            self._append_log(f"Failed to start server: {exc}\n", "ERROR")
            return

        self._start_srv_btn.config(state="disabled")
        self._stop_srv_btn.config(state="normal")
        self._server_status_lbl.config(text="● Server Online", fg=GREEN)
        self._append_log(f"Server started on {host}:{port}\n", "OK")

        threading.Thread(target=self._stream_proc,
                         args=(self._server_proc,), daemon=True).start()

    def _stop_server(self):
        if self._server_proc:
            self._server_proc.terminate()
            self._server_proc = None
        self._start_srv_btn.config(state="normal")
        self._stop_srv_btn.config(state="disabled")
        self._server_status_lbl.config(text="● Server Offline", fg=RED)
        self._append_log("Server stopped.\n", "WARNING")

    # ═════════════════════════════════════════════════════════════════════════
    # Client control
    # ═════════════════════════════════════════════════════════════════════════
    def _launch_client(self):
        host, port, rate, duration = (v.get() for v in self._cli_vars)
        cid           = self._next_cid
        self._next_cid += 1

        cmd = [PYTHON, str(CLIENT_PY),
               "--host", host, "--port", port,
               "--client-id", str(cid),
               "--rate", rate, "--duration", duration]
        try:
            proc = subprocess.Popen(
                cmd,
                stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                text=True, cwd=str(BASE_DIR / "client"),
            )
        except Exception as exc:
            self._append_log(f"Failed to start client {cid}: {exc}\n", "ERROR")
            return

        self._clients[cid] = {"proc": proc}
        self._client_tree.insert("", "end", iid=str(cid),
                                 values=(cid, host, port, rate,
                                         duration if duration != "0" else "∞",
                                         "🟢 Running"))
        self._update_active_count()
        self._append_log(f"Client {cid} started ({host}:{port} @ {rate}/s)\n", "ACCENT")

        threading.Thread(target=self._stream_client,
                         args=(proc, cid), daemon=True).start()

    def _stop_selected_client(self):
        for iid in self._client_tree.selection():
            cid   = int(iid)
            entry = self._clients.get(cid)
            if entry and entry["proc"].poll() is None:
                entry["proc"].terminate()
            self._client_tree.set(iid, "Status", "🔴 Stopped")
            self._append_log(f"Client {cid} stopped.\n", "WARNING")
        self._update_active_count()

    def _stop_all_clients(self):
        for cid, entry in list(self._clients.items()):
            if entry["proc"].poll() is None:
                entry["proc"].terminate()
            if self._client_tree.exists(str(cid)):
                self._client_tree.set(str(cid), "Status", "🔴 Stopped")
        self._append_log("All clients stopped.\n", "WARNING")
        self._update_active_count()

    def _update_active_count(self):
        count = sum(1 for e in self._clients.values() if e["proc"].poll() is None)
        self._active_lbl.config(
            text=f"Server Clients: {self._server_active}  |  Local: {count}"
        )

    # ═════════════════════════════════════════════════════════════════════════
    # Certificate generation
    # ═════════════════════════════════════════════════════════════════════════
    def _gen_certs(self):
        self._append_log("Generating self-signed certificates…\n", "ACCENT")

        def _run():
            try:
                result = subprocess.run(
                    [PYTHON, str(GEN_CERTS)],
                    cwd=str(BASE_DIR),
                    capture_output=True, text=True,
                )
                out = result.stdout + result.stderr
                tag = "OK" if result.returncode == 0 else "ERROR"
                self._log_queue.put((tag, out))
            except Exception as exc:
                self._log_queue.put(("ERROR", str(exc) + "\n"))

        threading.Thread(target=_run, daemon=True).start()

    # ═════════════════════════════════════════════════════════════════════════
    # Log streaming — all widget mutations happen on the main thread via after()
    # ═════════════════════════════════════════════════════════════════════════
    def _stream_proc(self, proc: subprocess.Popen):
        """Read process stdout line-by-line; push to queue (background thread OK)."""
        try:
            for line in proc.stdout:
                tag = "INFO"
                ll  = line.lower()
                if "error" in ll:              tag = "ERROR"
                elif "warn" in ll:             tag = "WARNING"
                elif "summary" in ll:          tag = "OK"
                self._log_queue.put((tag, line))
        except Exception:
            pass

    def _stream_client(self, proc: subprocess.Popen, cid: int):
        """Stream client stdout then schedule UI update back on the main thread."""
        self._stream_proc(proc)
        # Schedule tree/count updates on the Tk main thread
        self.after(0, self._on_client_finished, cid)

    def _on_client_finished(self, cid: int):
        """Called on the main thread when a client process has exited."""
        self._log_queue.put(("WARNING", f"Client {cid} process finished.\n"))
        if self._client_tree.exists(str(cid)):
            self._client_tree.set(str(cid), "Status", "✅ Done")
        self._update_active_count()

    def _poll_logs(self):
        """Drain the log queue and write to the text widget (main thread)."""
        try:
            while True:
                tag, line = self._log_queue.get_nowait()
                self._append_log(line, tag)
                self._parse_stats_line(line)
        except queue.Empty:
            pass
        self.after(80, self._poll_logs)

    def _append_log(self, text: str, tag: str = "INFO"):
        ts = time.strftime("[%H:%M:%S] ")
        self._log_box.config(state="normal")
        self._log_box.insert("end", ts + text, tag)
        self._log_box.see("end")
        self._log_box.config(state="disabled")

    # ═════════════════════════════════════════════════════════════════════════
    # Stats parsing
    # ═════════════════════════════════════════════════════════════════════════
    _SUMMARY_RE = re.compile(
        r"Client (\d+) \| Recv: (\d+) \| Lost: ([\d.]+)% \| Latency: ([\d.]+)"
    )
    _ACTIVE_CLIENTS_RE = re.compile(r"SUMMARY \| Active Clients: (\d+)")

    def _parse_stats_line(self, line: str):
        m = self._SUMMARY_RE.search(line)
        if m:
            cid, recv, loss, latency = m.groups()
            self._stats_data[cid] = {"recv": recv, "loss": loss, "latency": latency}

        m2 = self._ACTIVE_CLIENTS_RE.search(line)
        if m2:
            self._server_active = int(m2.group(1))
            self._update_active_count()

    def _refresh_stats(self):
        for row in self._stats_tree.get_children():
            self._stats_tree.delete(row)
        for cid, d in self._stats_data.items():
            self._stats_tree.insert("", "end",
                                    values=(cid, d["recv"],
                                            f"{d['loss']}%", f"{d['latency']} ms"))

    def _auto_refresh_stats(self):
        self._refresh_stats()
        self.after(5000, self._auto_refresh_stats)

    # ═════════════════════════════════════════════════════════════════════════
    def on_close(self):
        self._stop_server()
        self._stop_all_clients()
        self.destroy()


# ── Entry point ───────────────────────────────────────────────────────────────
if __name__ == "__main__":
    app = TelemetryDashboard()
    app.protocol("WM_DELETE_WINDOW", app.on_close)
    app.mainloop()
