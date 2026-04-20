import socket
import ssl
import time
import argparse
import struct
import random

from packet import create_packet
from ssl_utils import create_client_ssl_context, encrypt_udp_payload

class TelemetryClient:
    def __init__(self, host, port, client_id, rate, duration):
        self.host = host
        self.port = port
        self.client_id = client_id
        self.rate = rate
        self.duration = duration
        self.session_key = None
        
    def perform_handshake(self):
        """Perform TCP+TLS handshake to retrieve AES-GCM symmetric session key."""
        context = create_client_ssl_context()
        tcp_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        
        try:
            # Wrap standard socket securely
            secure_sock = context.wrap_socket(tcp_socket, server_hostname=self.host)
            secure_sock.connect((self.host, self.port))
            
            # Provide unauthenticated Client ID block to identify ourselves
            secure_sock.sendall(struct.pack("!H", self.client_id))
            
            # Receive 32-byte key symmetric key for DTLS substitute
            self.session_key = secure_sock.recv(32)
            if len(self.session_key) != 32:
                raise ValueError("Did not receive complete session key.")
            print(f"Client {self.client_id} established secure session.")
            
        finally:
            secure_sock.close()

    def stream_telemetry(self):
        """Execute main telemetry feed synchronously blocking over standard intervals."""
        if not self.session_key:
            raise RuntimeError("Must perform handshake before streaming telemetry, missing Session Key.")
            
        udp_socket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        interval = 1.0 / self.rate
        
        seq_no = 0
        start_time = time.time()
        
        print(f"Client {self.client_id} starting packet transmission at {self.rate} msg/s.")
        print(f"Running for {'forever' if self.duration == 0 else f'{self.duration} seconds'}...")
        
        try:
            while True:
                if self.duration > 0 and (time.time() - start_time) > self.duration:
                    break
                    
                # Simulate valid temperature reading between 15.0 and 30.0 Celsius
                sensor_type = 1 # 1 = Temperature
                sensor_value = random.uniform(15.0, 30.0)
                
                # Pack datagram
                plaintext_packet = create_packet(seq_no, self.client_id, sensor_type, sensor_value)
                
                # Encrypt AES-GCM using symmetric state
                encrypted_blob = encrypt_udp_payload(self.session_key, plaintext_packet)
                
                # Prepend unencrypted Client ID manually purely for routing table ID correlation
                final_payload = struct.pack("!H", self.client_id) + encrypted_blob
                
                udp_socket.sendto(final_payload, (self.host, self.port))
                
                seq_no += 1
                time.sleep(interval)
        except KeyboardInterrupt:
            print("Shutting down client...")
        finally:
            udp_socket.close()

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Secure UDP Telemetry Client")
    parser.add_argument("--host", default="127.0.0.1", help="Target Server IP")
    parser.add_argument("--port", type=int, default=9000, help="Target Server Port")
    parser.add_argument("--client-id", type=int, required=True, help="16-bit integer client identifier")
    parser.add_argument("--rate", type=float, default=10.0, help="Packets per second rate")
    parser.add_argument("--duration", type=int, default=0, help="Duration in seconds. 0 = Indefinite runs.")
    
    args = parser.parse_args()
    
    client = TelemetryClient(args.host, args.port, args.client_id, args.rate, args.duration)
    client.perform_handshake()
    client.stream_telemetry()
