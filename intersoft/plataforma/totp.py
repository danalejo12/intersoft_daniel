"""Implementación RFC 6238 (TOTP) sin dependencias externas para 2FA del equipo de /plataforma/."""
import base64
import hashlib
import hmac
import secrets
import struct
import time
from urllib.parse import quote


def generar_secreto_totp() -> str:
    """Genera un secreto Base32 de 160 bits compatible con Google Authenticator y Authy."""
    crudo = secrets.token_bytes(20)
    return base64.b32encode(crudo).decode("ascii").rstrip("=")


def _codigo_en_contador(secreto: str, contador: int, digitos: int = 6) -> str:
    limpio = secreto.strip().upper().replace(" ", "")
    relleno = (-len(limpio)) % 8
    clave = base64.b32decode(limpio + ("=" * relleno), casefold=True)
    msg = struct.pack(">Q", contador)
    digest = hmac.new(clave, msg, hashlib.sha1).digest()
    offset = digest[-1] & 0x0F
    codigo_int = struct.unpack(">I", digest[offset : offset + 4])[0] & 0x7FFFFFFF
    return str(codigo_int % (10**digitos)).zfill(digitos)


def codigo_totp_actual(secreto: str, timestamp: float | None = None, paso: int = 30) -> str:
    ts = time.time() if timestamp is None else timestamp
    return _codigo_en_contador(secreto, int(ts // paso))


def verificar_codigo_totp(
    secreto: str,
    codigo: str,
    *,
    timestamp: float | None = None,
    paso: int = 30,
    ventana: int = 1,
) -> bool:
    if not secreto or not codigo:
        return False
    limpio = str(codigo).strip().replace(" ", "")
    if not limpio.isdigit() or len(limpio) != 6:
        return False
    ts = time.time() if timestamp is None else timestamp
    contador_base = int(ts // paso)
    for delta in range(-ventana, ventana + 1):
        esperado = _codigo_en_contador(secreto, contador_base + delta)
        if hmac.compare_digest(limpio, esperado):
            return True
    return False


def uri_otpauth(secreto: str, email: str, emisor: str = "InterSoft Plataforma") -> str:
    etiqueta = quote(f"{emisor}:{email}")
    emisor_q = quote(emisor)
    return f"otpauth://totp/{etiqueta}?secret={secreto}&issuer={emisor_q}&digits=6&period=30"
