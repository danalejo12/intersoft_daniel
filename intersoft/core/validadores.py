"""Validadores de datos de entrada compartidos (corrigen CP-04, CP-08, CP-09, CP-12, CP-13 y CP-14 del informe
de pruebas de validación del 25 de noviembre de 2026).

Se usan en los modelos, así aplican en todos los formularios que crean o editan esos datos (registro, panel,
admin e importaciones), no solo en una pantalla."""
import re
import unicodedata

from django.core.exceptions import ValidationError
from django.core.validators import RegexValidator

LETRA_O_NUMERO = re.compile(r"[0-9A-Za-zÁÉÍÓÚÜÑáéíóúüñ]")
LETRA = re.compile(r"[A-Za-zÁÉÍÓÚÜÑáéíóúüñ]")
DIGITO = re.compile(r"\d")


def exigir_letra_o_numero(valor):
    """Rechaza textos hechos solo de símbolos («=@», «*», «=»): un nombre debe tener al menos una letra o número."""
    if not LETRA_O_NUMERO.search(valor or ""):
        raise ValidationError("Escribe al menos una letra o un número; no puede ser solo símbolos.",
                              code="solo_simbolos")


# Nombres y apellidos de personas: solo letras (con tildes, ñ y ü) separadas por espacios.
# Sin números ni caracteres especiales como @ = * - . ' (pedido del equipo tras el informe de pruebas)
validar_nombre_persona = RegexValidator(
    r"^[^\W\d_]+(?: +[^\W\d_]+)*$",
    "Escribe solo letras y espacios, sin números ni caracteres especiales.",
    code="nombre_persona_invalido",
)

def validar_usuario_del_correo(valor):
    """Máximo 64 caracteres antes de la @ (RFC 5321). El validador de correo de Django no lo revisa."""
    if "@" in (valor or "") and len(valor.rsplit("@", 1)[0]) > 64:
        raise ValidationError("La parte antes de la @ no puede tener más de 64 caracteres.", code="correo_usuario_largo")


# NIT: números, letras, guion, puntos y espacios, con al menos un número (p. ej. 900.123.456-7)
validar_nit = RegexValidator(
    r"^(?=.*\d)[0-9A-Za-z.\s-]{1,20}$",
    "El NIT solo puede tener números, letras, guion, puntos y espacios (por ejemplo 900123456-7).",
    code="nit_invalido",
)

# Código de producto: empieza por letra o número; luego letras, números, espacio, guion, guion bajo, punto o «/»
validar_codigo_producto = RegexValidator(
    r"^[0-9A-Za-zÁÉÍÓÚÜÑáéíóúüñ][0-9A-Za-zÁÉÍÓÚÜÑáéíóúüñ ._/-]*$",
    "El código solo puede tener letras, números, espacios y - _ . / (por ejemplo P-001).",
    code="codigo_invalido",
)


def validar_direccion(valor):
    """Dirección de notificaciones real: al menos 6 caracteres, con letras y un número (p. ej. «Calle 10 # 5-20»)."""
    texto = (valor or "").strip()
    if len(texto) < 6 or not LETRA.search(texto) or not DIGITO.search(texto):
        raise ValidationError("Escribe una dirección completa, con vía y número (por ejemplo Calle 10 # 5-20).",
                              code="direccion_incompleta")


# ---------- Contraseñas ----------
# Contraseñas comunes en español: la lista de Django es en inglés y no las detecta (CP-04)
CONTRASENAS_COMUNES_ES = {
    "contrasena", "contrasenas", "clave", "claves", "miclave", "micontrasena", "secreto", "acceso", "entrar",
    "ingresar", "usuario", "administrador", "admin", "colombia", "bogota", "medellin", "cali", "barranquilla",
    "intersoft", "tienda", "negocio", "empresa", "hola", "holamundo", "teamo", "tequiero", "amor", "amorcito",
    "princesa", "familia", "futbol", "millonarios", "nacional", "america", "junior", "dios", "diosesamor",
    "jesus", "maria", "mama", "papa", "bebe", "estrella", "mariposa", "corazon", "felicidad", "libertad",
    "qwerty", "asdfgh", "zxcvbn", "abcdef", "abc", "password", "pass", "welcome", "bienvenido", "cambiar",
    "cambiame", "nueva", "nuevaclave", "prueba", "pruebas", "test", "demo", "temporal",
}


def _normalizar(texto):
    """Minúsculas y sin tildes, para comparar «Contraseña» con «contrasena»."""
    sin_tildes = unicodedata.normalize("NFKD", texto).encode("ascii", "ignore").decode()
    return sin_tildes.lower()


class ContrasenaSeguraValidator:
    """Complementa los validadores de Django: rechaza contraseñas comunes en español (aunque lleven números o
    símbolos al final, como «Colombia2026!»), las de un mismo carácter repetido («@@@@@@@@») y las secuencias
    («abcdefgh», «12345678a»)."""

    SECUENCIAS = ("abcdefghijklmnopqrstuvwxyz", "0123456789", "qwertyuiop", "asdfghjkl", "zxcvbnm")

    def validate(self, password, user=None):
        """Lanza ValidationError si la contraseña es común en español, repetida o una secuencia."""
        texto = _normalizar(password or "")
        base = re.sub(r"[^a-z]", "", texto)
        if texto in CONTRASENAS_COMUNES_ES or (len(base) >= 3 and base in CONTRASENAS_COMUNES_ES):
            raise ValidationError("Esta contraseña es muy común. Usa una combinación que no sea una palabra conocida.",
                                  code="contrasena_comun_es")
        if len(set(texto)) <= 2:
            raise ValidationError("La contraseña no puede repetir el mismo carácter. Mezcla letras, números y "
                                  "símbolos.", code="contrasena_repetida")
        compacta = re.sub(r"[^a-z0-9]", "", texto)
        if len(compacta) >= 6 and any(compacta[:6] in sec or compacta[:6] in sec[::-1] for sec in self.SECUENCIAS):
            raise ValidationError("La contraseña no puede empezar con una secuencia como «abcdef» o «123456».",
                                  code="contrasena_secuencia")

    def get_help_text(self):
        return "No uses palabras comunes, caracteres repetidos ni secuencias como 123456."
