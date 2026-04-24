"""
p2p_messenger/app.py
======================
CustomTkinter GUI for the UDP P2P Messenger.

Presents a Launcher window that lets the user choose between:
  - Server mode (ServerApp)  — listens for client connections, shows live stats.
  - Client mode (ClientApp)  — connects to a server and sends/receives messages.
"""

import time
import threading
import socket

import customtkinter as ctk
import tkinter as tk
from tkinter import messagebox

from network import UDPServer, UDPClient

ctk.set_appearance_mode("Dark")
ctk.set_default_color_theme("blue")


def get_local_ip() -> str:
    """Return the machine's outbound IP address (best-effort)."""
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        ip = s.getsockname()[0]
        s.close()
        return ip
    except Exception:
        return "127.0.0.1"


# ═════════════════════════════════════════════════════════════════════════════
class Launcher(ctk.CTk):
    """Role-selection window shown at startup."""

    def __init__(self):
        super().__init__()
        self.title("UDP Messenger — Select Role")
        self.geometry("450x250")
        self.eval("tk::PlaceWindow . center")

        ctk.CTkLabel(self, text="UDP P2P Messenger",
                     font=ctk.CTkFont(size=24, weight="bold")).pack(pady=(30, 20))

        frame = ctk.CTkFrame(self, fg_color="transparent")
        frame.pack(fill="x", padx=40)
        frame.grid_columnconfigure((0, 1), weight=1)

        ctk.CTkButton(frame, text="Host UDP Server", height=50,
                      command=self._launch_server).grid(row=0, column=0, padx=10, sticky="ew")
        ctk.CTkButton(frame, text="Connect as Client", height=50,
                      command=self._launch_client).grid(row=0, column=1, padx=10, sticky="ew")

    def _launch_server(self):
        self.destroy()
        ServerApp().mainloop()

    def _launch_client(self):
        self.destroy()
        ClientApp().mainloop()


# ═════════════════════════════════════════════════════════════════════════════
class ServerApp(ctk.CTk):
    """UDP server dashboard — shows connected clients and received messages."""

    def __init__(self):
        super().__init__()
        self.title("UDP Server Dashboard")
        self.geometry("900x600")
        self.minsize(700, 400)

        self.grid_columnconfigure(1, weight=1)
        self.grid_rowconfigure(0, weight=1)

        self.local_ip   = get_local_ip()
        self.local_port = 5000
        self.client_labels: dict[str, ctk.CTkLabel] = {}

        self._setup_ui()

        self.server = UDPServer(host="0.0.0.0", port=self.local_port)
        self.server.on_client_connected = lambda ip, p: self.after(0, self._log_sys, f"Client {ip}:{p} connected.")
        self.server.on_message          = lambda ip, p, msg: self.after(0, self._log_msg, ip, p, msg)
        self.server.on_stats_update     = lambda ip, p, st: self.after(0, self._update_stats, ip, p, st)
        self.server.on_error            = lambda e: self.after(0, self._log_sys, f"ERROR: {e}")
        self.server.start()

        self._log_sys(f"UDP Server listening on {self.local_ip}:{self.local_port}")

    def _setup_ui(self):
        # Sidebar
        sidebar = ctk.CTkFrame(self, width=250, corner_radius=0)
        sidebar.grid(row=0, column=0, sticky="nsew")

        ctk.CTkLabel(sidebar, text="UDP SERVER",
                     font=ctk.CTkFont(size=20, weight="bold")).pack(pady=20)
        ctk.CTkLabel(sidebar,
                     text=f"Hosting on:\n{self.local_ip}:{self.local_port}",
                     font=ctk.CTkFont(size=14)).pack(pady=10)
        ctk.CTkLabel(sidebar, text="Connected Clients Stats:",
                     font=ctk.CTkFont(weight="bold")).pack(pady=(20, 5))

        self.stats_scroll = ctk.CTkScrollableFrame(sidebar, fg_color="transparent")
        self.stats_scroll.pack(fill="both", expand=True, padx=10, pady=10)

        # Main log
        main_frame = ctk.CTkFrame(self)
        main_frame.grid(row=0, column=1, padx=20, pady=20, sticky="nsew")
        main_frame.grid_rowconfigure(0, weight=1)
        main_frame.grid_columnconfigure(0, weight=1)

        self.log_box = ctk.CTkTextbox(main_frame, state="disabled",
                                      font=ctk.CTkFont(size=14))
        self.log_box.grid(row=0, column=0, sticky="nsew")

    def _log_sys(self, text: str):
        self.log_box.configure(state="normal")
        self.log_box.insert("end", f"[SYSTEM] {text}\n")
        self.log_box.configure(state="disabled")
        self.log_box.see("end")

    def _log_msg(self, ip: str, port: int, msg: str):
        self.log_box.configure(state="normal")
        self.log_box.insert("end", f"[{ip}:{port}] {msg}\n")
        self.log_box.configure(state="disabled")
        self.log_box.see("end")

    def _update_stats(self, ip: str, port: int, stats: dict):
        cid   = f"{ip}:{port}"
        total = stats["received"] + stats["lost"]
        loss  = (stats["lost"] / total * 100) if total > 0 else 0.0
        text  = f"{cid}\nRecv: {stats['received']} | Lost: {stats['lost']} ({loss:.1f}%)"

        if cid not in self.client_labels:
            frame = ctk.CTkFrame(self.stats_scroll, fg_color="#333333")
            frame.pack(fill="x", pady=5)
            lbl = ctk.CTkLabel(frame, text=text, justify="left", font=ctk.CTkFont(size=12))
            lbl.pack(padx=10, pady=10, anchor="w")
            self.client_labels[cid] = lbl
        else:
            self.client_labels[cid].configure(text=text)

    def destroy(self):
        self.server.stop()
        super().destroy()


# ═════════════════════════════════════════════════════════════════════════════
class ClientApp(ctk.CTk):
    """UDP client — connect to a server and exchange messages."""

    def __init__(self):
        super().__init__()
        self.title("UDP Client")
        self.geometry("800x600")
        self.minsize(600, 400)

        self.grid_columnconfigure(1, weight=1)
        self.grid_rowconfigure(0, weight=1)

        self._connected = False

        self.client = UDPClient()
        self.client.on_connected = lambda: self.after(0, self._handle_connected)
        self.client.on_ack       = lambda r, l: self.after(0, self._update_ack, r, l)
        self.client.on_error     = lambda e: self.after(0, self._on_error, e)

        self._setup_ui()

    def _setup_ui(self):
        # Sidebar
        self.sidebar = ctk.CTkFrame(self, width=220, corner_radius=0)
        self.sidebar.grid(row=0, column=0, sticky="nsew")
        self.sidebar.grid_rowconfigure(7, weight=1)

        ctk.CTkLabel(self.sidebar, text="UDP CLIENT",
                     font=ctk.CTkFont(size=20, weight="bold")).grid(row=0, column=0, pady=20)

        self.ip_entry = ctk.CTkEntry(self.sidebar, placeholder_text="Server IP")
        self.ip_entry.grid(row=1, column=0, padx=20, pady=5)
        self.ip_entry.insert(0, "127.0.0.1")

        self.port_entry = ctk.CTkEntry(self.sidebar, placeholder_text="Server Port")
        self.port_entry.grid(row=2, column=0, padx=20, pady=5)
        self.port_entry.insert(0, "5000")

        self.conn_btn = ctk.CTkButton(self.sidebar, text="Connect", command=self._do_connect)
        self.conn_btn.grid(row=3, column=0, padx=20, pady=20)

        self.spam_btn = ctk.CTkButton(
            self.sidebar, text="Spam 100 Packets", command=self._do_spam,
            fg_color="#E65100", hover_color="#BF360C",
        )

        self.stats_frame = ctk.CTkFrame(self.sidebar, fg_color="#2b2b2b")
        self.stats_lbl   = ctk.CTkLabel(self.stats_frame,
                                         text="Loss Stats\n\nRecv: 0\nLost: 0",
                                         font=ctk.CTkFont(size=14))
        self.stats_lbl.pack(padx=20, pady=20)

        # Main chat area
        main_frame = ctk.CTkFrame(self)
        main_frame.grid(row=0, column=1, padx=20, pady=20, sticky="nsew")
        main_frame.grid_rowconfigure(0, weight=1)
        main_frame.grid_columnconfigure(0, weight=1)

        self.chat_box = ctk.CTkTextbox(main_frame, state="disabled",
                                        font=ctk.CTkFont(size=14))
        self.chat_box.grid(row=0, column=0, sticky="nsew", pady=(0, 10))

        input_frame = ctk.CTkFrame(main_frame, fg_color="transparent")
        input_frame.grid(row=1, column=0, sticky="ew")
        input_frame.grid_columnconfigure(0, weight=1)

        self.msg_entry = ctk.CTkEntry(input_frame, placeholder_text="Type message…",
                                       state="disabled", font=ctk.CTkFont(size=14))
        self.msg_entry.grid(row=0, column=0, padx=(0, 10), sticky="ew")
        self.msg_entry.bind("<Return>", lambda _: self._do_send())

        self.send_btn = ctk.CTkButton(input_frame, text="Send", width=80,
                                       state="disabled", command=self._do_send)
        self.send_btn.grid(row=0, column=1)

    # ── Helpers ───────────────────────────────────────────────────────────────

    def _log_sys(self, text: str):
        self.chat_box.configure(state="normal")
        self.chat_box.insert("end", f"[SYSTEM] {text}\n")
        self.chat_box.configure(state="disabled")
        self.chat_box.see("end")

    def _on_error(self, message: str):
        self._log_sys(f"ERROR: {message}")
        # Only re-enable connect if we haven't successfully connected yet
        if not self._connected:
            self.conn_btn.configure(state="normal", text="Connect")

    # ── Event handlers ────────────────────────────────────────────────────────

    def _do_connect(self):
        ip   = self.ip_entry.get().strip()
        port = self.port_entry.get().strip()
        if not ip or not port:
            return
        self.conn_btn.configure(state="disabled", text="Connecting…")
        threading.Thread(target=self.client.connect, args=(ip, port),
                         daemon=True).start()

    def _handle_connected(self):
        self._connected = True
        self._log_sys("Connected to UDP Server!")
        self.conn_btn.grid_forget()
        self.ip_entry.configure(state="disabled")
        self.port_entry.configure(state="disabled")
        self.spam_btn.grid(row=3, column=0, padx=20, pady=20)
        self.stats_frame.grid(row=4, column=0, padx=20, pady=10, sticky="ew")
        self.msg_entry.configure(state="normal")
        self.send_btn.configure(state="normal")

    def _update_ack(self, received: int, lost: int):
        total    = received + lost
        loss_pct = (lost / total * 100) if total > 0 else 0.0
        self.stats_lbl.configure(
            text=f"Server Ack Stats\n\nRecv: {received}\nLost: {lost}\nLoss: {loss_pct:.1f}%"
        )

    def _do_send(self):
        msg = self.msg_entry.get()
        if msg:
            if self.client.send_message(msg):
                self.chat_box.configure(state="normal")
                self.chat_box.insert("end", f"You: {msg}\n")
                self.chat_box.configure(state="disabled")
                self.chat_box.see("end")
                self.msg_entry.delete(0, "end")
            else:
                self._log_sys("Failed to send — not connected?")

    def _do_spam(self):
        self._log_sys("Sending 100 packets quickly…")

        def _spam():
            for i in range(100):
                self.client.send_message(f"Spam #{i + 1}")
                time.sleep(0.001)
            self.after(0, self._log_sys, "Done — 100 spam packets sent.")

        threading.Thread(target=_spam, daemon=True).start()

    def destroy(self):
        self.client.disconnect()
        super().destroy()


# ── Entry point ───────────────────────────────────────────────────────────────
if __name__ == "__main__":
    Launcher().mainloop()
