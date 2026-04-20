import socket
import threading
import json

class UDPServer:
    def __init__(self, host='0.0.0.0', port=5000):
        self.host = host
        self.port = port
        self.sock = None
        self.running = False
        
        # clients[(ip, port)] = {"expected_seq": 1, "lost": 0, "received": 0}
        self.clients = {}
        
        # Callbacks
        self.on_client_connected = None    # (ip, port)
        self.on_message = None             # (ip, port, msg)
        self.on_stats_update = None        # (ip, port, stats_dict)
        self.on_error = None

    def start(self):
        try:
            self.sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            self.sock.bind((self.host, self.port))
            self.running = True
            threading.Thread(target=self._listen_loop, daemon=True).start()
        except Exception as e:
            if self.on_error: self.on_error(f"Server start error: {e}")

    def _listen_loop(self):
        while self.running:
            try:
                data, addr = self.sock.recvfrom(65535)
                if not data: continue
                
                try:
                    packet = json.loads(data.decode('utf-8'))
                except json.JSONDecodeError:
                    continue
                
                ptype = packet.get("type")
                if ptype == "HELLO":
                    self.clients[addr] = {"expected_seq": 1, "lost": 0, "received": 0}
                    self._send(addr, {"type": "ACCEPT"})
                    if self.on_client_connected:
                        self.on_client_connected(addr[0], addr[1])
                
                elif ptype == "MESSAGE":
                    if addr not in self.clients:
                        self.clients[addr] = {"expected_seq": 1, "lost": 0, "received": 0}
                        if self.on_client_connected:
                            self.on_client_connected(addr[0], addr[1])
                    
                    c = self.clients[addr]
                    seq = packet.get("seq", 1)
                    
                    if seq > c["expected_seq"]:
                        # We skipped some packets -> lost
                        c["lost"] += (seq - c["expected_seq"])
                    
                    c["received"] += 1
                    c["expected_seq"] = max(c["expected_seq"], seq + 1)
                    
                    if self.on_message:
                        self.on_message(addr[0], addr[1], packet.get("content", ""))
                    if self.on_stats_update:
                        self.on_stats_update(addr[0], addr[1], dict(c)) # pass copy
                        
                    # ACK
                    self._send(addr, {
                        "type": "ACK",
                        "received": c["received"],
                        "lost": c["lost"]
                    })
                
                elif ptype == "DISCONNECT":
                    if addr in self.clients:
                        del self.clients[addr]
            except OSError:
                break # closed
            except Exception as e:
                pass

    def _send(self, addr, packet_dict):
        try:
            data = json.dumps(packet_dict).encode('utf-8')
            self.sock.sendto(data, addr)
        except Exception:
            pass

    def stop(self):
        self.running = False
        if self.sock:
            try: self.sock.close()
            except: pass


class UDPClient:
    def __init__(self):
        self.sock = None
        self.server_addr = None
        self.running = False
        self.seq = 1
        
        # Callbacks
        self.on_connected = None
        self.on_ack = None        # (received, lost)
        self.on_error = None
        
    def connect(self, ip, port):
        try:
            self.server_addr = (ip, int(port))
            self.sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            self.sock.settimeout(2.0)
            self.running = True
            
            self._send({"type": "HELLO"})
            
            data, addr = self.sock.recvfrom(4096)
            packet = json.loads(data.decode('utf-8'))
            if packet.get("type") == "ACCEPT":
                self.sock.settimeout(None)
                if self.on_connected: self.on_connected()
                threading.Thread(target=self._listen_loop, daemon=True).start()
            else:
                if self.on_error: self.on_error("Connection rejected or malformed data.")
        except socket.timeout:
            if self.on_error: self.on_error("Connection timed out. Server unreachable.")
        except Exception as e:
            if self.on_error: self.on_error(f"Connection error: {e}")

    def _listen_loop(self):
        while self.running:
            try:
                data, addr = self.sock.recvfrom(4096)
                packet = json.loads(data.decode('utf-8'))
                if packet.get("type") == "ACK":
                    if self.on_ack:
                        self.on_ack(packet.get("received", 0), packet.get("lost", 0))
            except OSError:
                break
            except Exception:
                pass

    def send_message(self, text):
        if not self.server_addr: return False
        success = self._send({"type": "MESSAGE", "seq": self.seq, "content": text})
        if success:
            self.seq += 1
        return success

    def _send(self, packet_dict):
        try:
            data = json.dumps(packet_dict).encode('utf-8')
            self.sock.sendto(data, self.server_addr)
            return True
        except:
            return False

    def disconnect(self):
        self.running = False
        if self.server_addr:
            try: self._send({"type": "DISCONNECT"})
            except: pass
        if self.sock:
            try: self.sock.close()
            except: pass
