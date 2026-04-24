"""
telemetry_system/common/ssl_utils.py
======================================
Shared TLS / AES-GCM helpers used by both the server and client.

Provides:
  - SSL context factories for server and client sides.
  - AES-256-GCM session-key generation, encryption, and decryption helpers
    used as a lightweight DTLS substitute over UDP.
"""

import ssl
import os

from cryptography.hazmat.primitives.ciphers.aead import AESGCM


def create_server_ssl_context(certfile: str, keyfile: str) -> ssl.SSLContext:
    """
    Build a TLS server context loaded with the given certificate and private key.

    The returned context uses ``PROTOCOL_TLS_SERVER`` which automatically
    negotiates the highest mutually supported TLS version.
    """
    context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    context.load_cert_chain(certfile=certfile, keyfile=keyfile)
    return context


def create_client_ssl_context(certfile: str = None) -> ssl.SSLContext:
    """
    Build a TLS client context suitable for connecting to a self-signed server.

    Hostname verification and certificate validation are intentionally disabled
    so that the development self-signed certificate is accepted without needing
    it to be installed in the OS trust store.

    Args:
        certfile: Optional path to the server's PEM certificate for pinning.
                  If provided and the file exists, it is loaded as the sole
                  trusted CA.  Otherwise the context falls back to trusting nothing
                  (which is fine given ``CERT_NONE``).
    """
    context = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
    if certfile and os.path.exists(certfile):
        context.load_verify_locations(certfile)
    context.check_hostname = False
    context.verify_mode    = ssl.CERT_NONE  # Allow self-signed testing certs
    return context


def generate_session_key() -> bytes:
    """Generate a cryptographically random 32-byte key for AES-256-GCM."""
    return AESGCM.generate_key(bit_length=256)


def encrypt_udp_payload(key: bytes, plaintext: bytes) -> bytes:
    """
    Encrypt *plaintext* using AES-256-GCM with a fresh random nonce.

    Wire format of the returned bytes::

        [ nonce (12 B) ][ ciphertext + GCM auth tag (len(plaintext) + 16 B) ]

    The 12-byte nonce is prepended unencrypted so the receiver can use it for
    decryption.  A unique nonce is generated for every packet, preventing
    nonce reuse.
    """
    aesgcm    = AESGCM(key)
    nonce     = os.urandom(12)
    ciphertext = aesgcm.encrypt(nonce, plaintext, None)
    return nonce + ciphertext


def decrypt_udp_payload(key: bytes, encrypted_payload: bytes) -> bytes:
    """
    Decrypt an AES-256-GCM payload produced by :func:`encrypt_udp_payload`.

    Raises ``cryptography.exceptions.InvalidTag`` if authentication fails
    (tampered or corrupted data).
    """
    aesgcm     = AESGCM(key)
    nonce      = encrypted_payload[:12]
    ciphertext = encrypted_payload[12:]
    return aesgcm.decrypt(nonce, ciphertext, None)
