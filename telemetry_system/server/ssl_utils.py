import ssl
import os
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

def create_server_ssl_context(certfile: str, keyfile: str) -> ssl.SSLContext:
    """
    Create an SSL context for the server side using the PROTOCOL_TLS_SERVER setting.
    """
    context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    context.load_cert_chain(certfile=certfile, keyfile=keyfile)
    return context

def create_client_ssl_context(certfile: str = None) -> ssl.SSLContext:
    """
    Create an SSL context for the client side using PROTOCOL_TLS_CLIENT.
    It ignores hostname checking and certificate validation for self-signed purposes.
    """
    context = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
    if certfile and os.path.exists(certfile):
        context.load_verify_locations(certfile)
    context.check_hostname = False
    context.verify_mode = ssl.CERT_NONE  # Explicitly allow self-signed testing certs
    return context

def generate_session_key() -> bytes:
    """
    Generate a random 32-byte session key for AES-256-GCM.
    """
    return AESGCM.generate_key(bit_length=256)

def encrypt_udp_payload(key: bytes, plaintext: bytes) -> bytes:
    """
    Encrypt the datagram payload using AES-GCM for strong integrity and confidentiality.
    A unique 12-byte nonce is prepended to the ciphertext.
    """
    aesgcm = AESGCM(key)
    nonce = os.urandom(12)
    ciphertext = aesgcm.encrypt(nonce, plaintext, None)
    return nonce + ciphertext

def decrypt_udp_payload(key: bytes, encrypted_payload: bytes) -> bytes:
    """
    Decrypt the AES-GCM encrypted UDP datagram using the shared key.
    """
    aesgcm = AESGCM(key)
    nonce = encrypted_payload[:12]
    ciphertext = encrypted_payload[12:]
    return aesgcm.decrypt(nonce, ciphertext, None)
