"""
telemetry_system/generate_certs.py
=====================================
Generates a self-signed RSA-4096 TLS certificate into the ``certs/`` directory
that lives alongside this script, regardless of the working directory the script
is invoked from.

Usage:
    python telemetry_system/generate_certs.py
"""

import datetime
from pathlib import Path
from cryptography import x509
from cryptography.x509.oid import NameOID
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import rsa

# Always resolve paths relative to this file's location, not the CWD
SCRIPT_DIR = Path(__file__).resolve().parent
CERTS_DIR  = SCRIPT_DIR / "certs"
CERTS_DIR.mkdir(parents=True, exist_ok=True)

print("Generating RSA-4096 private key…")
key = rsa.generate_private_key(
    public_exponent=65537,
    key_size=4096,
)

subject = issuer = x509.Name([
    x509.NameAttribute(NameOID.COMMON_NAME, "localhost"),
])

# Use timezone-aware UTC datetime to avoid deprecation warnings in Python ≥ 3.12
now = datetime.datetime.now(datetime.timezone.utc)

print("Building self-signed certificate (valid 365 days)…")
cert = (
    x509.CertificateBuilder()
    .subject_name(subject)
    .issuer_name(issuer)
    .public_key(key.public_key())
    .serial_number(x509.random_serial_number())
    .not_valid_before(now)
    .not_valid_after(now + datetime.timedelta(days=365))
    .add_extension(
        x509.SubjectAlternativeName([
            x509.DNSName("localhost"),
            x509.IPAddress(__import__("ipaddress").IPv4Address("127.0.0.1")),
        ]),
        critical=False,
    )
    .sign(key, hashes.SHA256())
)

# Write private key (unencrypted — for local dev use only)
key_path = CERTS_DIR / "server.key"
key_path.write_bytes(
    key.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.TraditionalOpenSSL,
        encryption_algorithm=serialization.NoEncryption(),
    )
)
print(f"  Private key  → {key_path}")

# Write certificate
crt_path = CERTS_DIR / "server.crt"
crt_path.write_bytes(cert.public_bytes(serialization.Encoding.PEM))
print(f"  Certificate  → {crt_path}")

print("\nDone! Certificates ready in:", CERTS_DIR)
