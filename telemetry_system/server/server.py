import socket
import threading
import time
import argparse
import logging
import struct
import csv
from concurrent.futures import ThreadPoolExecutor

from aggregator import ClientState
from ssl_utils import create_server_ssl_context, generate_session_key, decrypt_udp_payload
from packet import parse_packet

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")

class TelemetryServer:
    def __init__(self, host, port, cert, key, metrics_file=None, window_size=100):
        self.host = host
        self.port = port
        self.ssl_context = create_server_ssl_context(cert, key)
        self.client_states = {}
        self.client_keys = {}
        self.window_size = window_size
        self.lock = threading.Lock()
        self.running = threading.Event()
        self.running.set()
        self.executor = ThreadPoolExecutor(max_workers=20)
        
        self.metrics_file = metrics_file
        if self.metrics_file:
            # Initialize metrics CSV empty state
            with open(self.metrics_file, 'w', newline='') as f:
                writer = csv.writer(f)
                writer.writerow(["timestamp_epoch", "client_id", "received", "lost", "loss_pct", "avg_latency_ms"])

    def handle_tcp_handshake(self, tcp_conn, addr):
        try:
            secure_sock = self.ssl_context.wrap_socket(tcp_conn, server_side=True)
            client_id_bytes = secure_sock.recv(2)
            if len(client_id_bytes) != 2: return
                
            client_id = struct.unpack("!H", client_id_bytes)[0]
            session_key = generate_session_key()
            with self.lock:
                self.client_keys[client_id] = session_key
                if client_id not in self.client_states:
                    self.client_states[client_id] = ClientState(client_id, self.window_size)
                    
            secure_sock.sendall(session_key)
            secure_sock.close()
        except Exception as e:
            logging.error(f"Handshake error from {addr}: {e}")

    def tcp_listener_thread(self):
        tcp_server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        tcp_server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        tcp_server.bind((self.host, self.port))
        tcp_server.listen(50)
        tcp_server.settimeout(1.0)
        
        while self.running.is_set():
            try:
                conn, addr = tcp_server.accept()
                threading.Thread(target=self.handle_tcp_handshake, args=(conn, addr), daemon=True).start()
            except socket.timeout: continue
            except: pass
        tcp_server.close()

    def udp_listener_thread(self):
        udp_server = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        # Increase receive buffer to 2MB to handle burst traffic
        try:
            udp_server.setsockopt(socket.SOL_SOCKET, socket.SO_RCVBUF, 1024 * 1024 * 2)
        except:
            pass
        udp_server.bind((self.host, self.port))
        udp_server.settimeout(1.0)
        
        while self.running.is_set():
            try:
                data, addr = udp_server.recvfrom(4096)
                if len(data) < 2: continue
                # Dispatch packet processing to a worker thread
                self.executor.submit(self.process_udp_packet, data)
                
            except socket.timeout: continue
            except Exception as e: pass
        udp_server.close()

    def process_udp_packet(self, data):
        try:
            client_id = struct.unpack("!H", data[:2])[0]
            encrypted_payload = data[2:]
            
            # Briefly acquire lock to fetch key and state references
            with self.lock:
                key = self.client_keys.get(client_id)
                state = self.client_states.get(client_id)
                
            if not key or not state: return
            
            # Expensive decrypt and parse operations happen OUTSIDE the lock
            plaintext = decrypt_udp_payload(key, encrypted_payload)
            packet_data = parse_packet(plaintext)
            
            # Re-acquire lock briefly to update state metrics
            with self.lock:
                if client_id in self.client_states: # Ensure hasn't been pruned
                    self.client_states[client_id].update(packet_data['seq_no'], packet_data['sensor_value'], packet_data['timestamp'])
        except Exception:
            pass

    def summary_printer_thread(self):
        while self.running.is_set():
            time.sleep(10)
            now = time.time()
            with self.lock:
                to_remove = []
                for client_id, state in self.client_states.items():
                    if state.is_inactive(timeout=30):
                        to_remove.append(client_id)
                    else:
                        summary = state.get_summary()
                        logging.info(f"Client {client_id} | Recv: {summary['received']} | "
                                     f"Lost: {summary['loss_pct']:.2f}% | Latency: {summary['avg_latency_ms']:.2f} ms")
                                     
                        if self.metrics_file:
                            with open(self.metrics_file, 'a', newline='') as f:
                                w = csv.writer(f)
                                w.writerow([now, client_id, summary['received'], summary['lost'], summary['loss_pct'], summary['avg_latency_ms']])
                
                active_count = len(self.client_states) - len(to_remove)
                logging.info(f"SUMMARY | Active Clients: {active_count}")
                
                for cid in to_remove:
                    del self.client_states[cid]
                    self.client_keys.pop(cid, None)

    def start(self):
        t1 = threading.Thread(target=self.tcp_listener_thread, daemon=True)
        t2 = threading.Thread(target=self.udp_listener_thread, daemon=True)
        t3 = threading.Thread(target=self.summary_printer_thread, daemon=True)
        t1.start()
        t2.start()
        t3.start()
        
        try:
            while True: time.sleep(1)
        except KeyboardInterrupt:
            self.running.clear()
            self.executor.shutdown(wait=False)
            t1.join(); t2.join(); t3.join()

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--host", default="0.0.0.0")
    parser.add_argument("--port", type=int, default=9000)
    parser.add_argument("--cert", default="../certs/server.crt")
    parser.add_argument("--key", default="../certs/server.key")
    parser.add_argument("--metrics", default=None, help="Output csv for benchmark")
    args = parser.parse_args()
    
    TelemetryServer(args.host, args.port, args.cert, args.key, args.metrics).start()
