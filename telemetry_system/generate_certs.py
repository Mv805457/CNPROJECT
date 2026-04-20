"""
Certificate generation script for the Telemetry System.
Generates a self-signed RSA-4096 TLS certificate into the certs/ directory.
"""

import os
import datetime
from cryptography import x509
from cryptography.x509.oid import NameOID
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import rsa

# Ensure the certs directory exists
os.makedirs("certs", exist_ok=True)

print("Generating RSA-4096 private key...")
key = rsa.generate_private_key(
    public_exponent=65537,
    key_size=4096,
)

subject = issuer = x509.Name([
    x509.NameAttribute(NameOID.COMMON_NAME, u"localhost"),
])

# Use timezone-aware datetime (UTC) to avoid deprecation warnings
now = datetime.datetime.now(datetime.timezone.utc)

print("Building self-signed certificate...")
cert = (
    x509.CertificateBuilder()
    .subject_name(subject)
    .issuer_name(issuer)
    .public_key(key.public_key())
    .serial_number(x509.random_serial_number())
    .not_valid_before(now)
    .not_valid_after(now + datetime.timedelta(days=365))
    .add_extension(
        x509.SubjectAlternativeName([x509.DNSName(u"localhost")]),
        critical=False,
    )
    .sign(key, hashes.SHA256())
)

# Write private key
key_path = os.path.join("certs", "server.key")
with open(key_path, "wb") as f:
    f.write(key.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.TraditionalOpenSSL,
        encryption_algorithm=serialization.NoEncryption(),
    ))
print(f"Private key saved to: {key_path}")

# Write certificate
crt_path = os.path.join("certs", "server.crt")
with open(crt_path, "wb") as f:
    f.write(cert.public_bytes(serialization.Encoding.PEM))
print(f"Certificate saved to: {crt_path}")

print("\nDone! Certificates are ready in the certs/ folder.")
