"""Validadores de formato real para nombres, negocios, documentos, direcciones, códigos, guías, textos y correos."""
import re

from django.core.exceptions import ValidationError
from django.core.validators import URLValidator

# 1. Nombres y apellidos reales en español/latinoamericano e internacional
REGEX_NOMBRE_PERSONA = re.compile(
    r"^[A-Za-zÀ-ÖØ-öø-ÿ]+(?:(?:\.\s|[ '\u2019.-])[A-Za-zÀ-ÖØ-öø-ÿ]+)*\.?$"
)

# 2. Nombres comerciales reales (Colombia y global): letras, números, espacios, -, ., &, ', ,
REGEX_NOMBRE_NEGOCIO = re.compile(
    r"^[A-Za-zÀ-ÖØ-öø-ÿ0-9]+(?:(?:\s*&\s*|[.,]\s+|[ '\u2019.&,-])[A-Za-zÀ-ÖØ-öø-ÿ0-9]+)*\.?$"
)

# 3. NIT colombiano: solo dígitos, con separadores opcionales (puntos, espacios) y guion de DV
REGEX_NIT_COLOMBIA = re.compile(r"^[0-9]+(?:[.\s-][0-9]+)*$")

# 4. Documentos por tipo (tras quitar puntos y espacios)
REGEX_SOLO_DIGITOS = re.compile(r"^[0-9]{1,20}$")
REGEX_PASAPORTE = re.compile(r"^[0-9A-Za-z-]{1,20}$")

# 5. Códigos comerciales (SKU de producto y cupones: ej. SKU-001, TOR-3.5, PROMO_15)
REGEX_CODIGO_COMERCIAL = re.compile(r"^[A-Z0-9][A-Z0-9._-]{0,39}$")

# 6. Direcciones con nomenclatura real colombiana (Calle 10 # 20-30 Apto 402, Torre B)
REGEX_DIRECCION = re.compile(r"^[A-Za-zÀ-ÖØ-öø-ÿ0-9\s#.,°ºª/()'\u2019-]+$")

# 7. Número de guía de transportadora
REGEX_NUMERO_GUIA = re.compile(r"^[A-Za-z0-9][A-Za-z0-9-]{0,79}$")

# 8. Dominios con errores de escritura frecuentes y dominios reservados/locales
TYPOS_DOMINIO_CORREO = {
    "gmial.com": "gmail.com",
    "gmal.com": "gmail.com",
    "gamil.com": "gmail.com",
    "gnail.com": "gmail.com",
    "gmail.co": "gmail.com",
    "hotmial.com": "hotmail.com",
    "hotmal.com": "hotmail.com",
    "hotnail.com": "hotmail.com",
    "outlok.com": "outlook.com",
    "outllok.com": "outlook.com",
    "yaho.com": "yahoo.com",
    "yhoo.com": "yahoo.com",
}
DOMINIOS_BLOQUEADOS = {"localhost", "local", "invalid", "test"}
PREFIJOS_FORMULA = ("=", "+", "-", "@", "\t", "\r")


def validar_nombre_persona(valor):
    """Normaliza espacios y valida que un nombre o apellido use solo caracteres reales de persona."""
    limpio = " ".join((valor or "").strip().split())
    if not limpio:
        return limpio
    if not REGEX_NOMBRE_PERSONA.match(limpio):
        raise ValidationError(
            "Usa solo letras, espacios y signos válidos como guion, apóstrofe o punto "
            "(ej.: María José, Ana-María, O'Connor)."
        )
    return limpio


def validar_nombre_negocio(valor):
    """Normaliza espacios y valida que un nombre comercial use solo letras, números y signos permitidos."""
    limpio = " ".join((valor or "").strip().split())
    if not limpio:
        return limpio
    if not REGEX_NOMBRE_NEGOCIO.match(limpio):
        raise ValidationError(
            "Usa solo letras, números, espacios y signos comerciales válidos como guion, punto, apóstrofe o & "
            "(ej.: mi-empresa, Café & Pan S.A.S.)."
        )
    return limpio


def validar_nit_negocio(valor):
    """Valida el formato del NIT colombiano y lo normaliza quitando puntos y espacios."""
    crudo = (valor or "").strip()
    if not crudo:
        return crudo
    if not REGEX_NIT_COLOMBIA.match(crudo):
        raise ValidationError(
            "Escribe un NIT válido usando solo dígitos, puntos, espacios o guion para el dígito de verificación "
            "(ej.: 900.123.456-7)."
        )
    return crudo.replace(".", "").replace(" ", "")


def validar_documento_por_tipo(tipo_documento, valor):
    """Valida el número de documento según su tipo (CC, CE, NIT o PP) y lo devuelve normalizado."""
    crudo = (valor or "").strip()
    if not crudo:
        return crudo
    if tipo_documento == "NIT":
        return validar_nit_negocio(crudo)
    normalizado = crudo.replace(".", "").replace(" ", "")
    if tipo_documento in ("CC", "CE"):
        if not REGEX_SOLO_DIGITOS.match(normalizado):
            raise ValidationError("Para cédula (CC o CE) escribe solo números, sin letras ni símbolos.")
        return normalizado
    if tipo_documento == "PP":
        if not REGEX_PASAPORTE.match(normalizado):
            raise ValidationError("Para pasaporte escribe solo letras, números o guion.")
        return normalizado.upper()
    if not REGEX_PASAPORTE.match(normalizado):
        raise ValidationError("Escribe solo números, letras o guion en el número de documento.")
    return normalizado


def validar_codigo_comercial(valor, ejemplo="SKU-001"):
    """Normaliza a mayúsculas y valida un código SKU o cupón (solo A-Z, 0-9, guion y guion bajo)."""
    codigo = (valor or "").strip().upper()
    if not codigo:
        return codigo
    if not REGEX_CODIGO_COMERCIAL.match(codigo):
        raise ValidationError(
            f"Usa solo letras, números, punto (.), guion (-) o guion bajo (_) sin espacios (ej.: {ejemplo})."
        )
    return codigo


def validar_ciudad(valor):
    """Valida nombres reales de ciudad o municipio (ej.: Bogotá D.C., San José del Guaviare)."""
    limpio = " ".join((valor or "").strip().split())
    if not limpio:
        return limpio
    if not REGEX_NOMBRE_PERSONA.match(limpio):
        raise ValidationError("Escribe un nombre de ciudad válido usando solo letras, espacios, punto o guion.")
    return limpio


def validar_direccion(valor):
    """Valida una dirección física con nomenclatura colombiana y rechaza código o símbolos inválidos."""
    limpio = " ".join((valor or "").strip().split())
    if not limpio:
        return limpio
    if not REGEX_DIRECCION.match(limpio) or not any(c.isalnum() for c in limpio):
        raise ValidationError(
            "Escribe una dirección válida usando letras, números y signos de nomenclatura (#, -, ., ,)."
        )
    return limpio


def validar_numero_guia(valor):
    """Valida que el número de guía de envío solo contenga letras, números y guiones."""
    limpio = (valor or "").strip()
    if not limpio:
        return limpio
    if not REGEX_NUMERO_GUIA.match(limpio):
        raise ValidationError("Escribe un número de guía válido usando solo letras, números y guiones (sin espacios).")
    return limpio


def validar_url_segura(valor):
    """Valida que una URL use únicamente esquema http:// o https:// y dominio válido."""
    limpio = (valor or "").strip()
    if not limpio:
        return limpio
    URLValidator(schemes=["http", "https"])(limpio)
    return limpio


def validar_texto_util(valor, min_caracteres=3):
    """Rechaza mensajes de puro relleno, espacios o repetición absurda de un mismo carácter."""
    limpio = (valor or "").strip()
    if not limpio:
        return limpio
    alnum = [c for c in limpio if c.isalnum()]
    if len(alnum) < min_caracteres:
        raise ValidationError(f"Escribe un mensaje más claro (al menos {min_caracteres} caracteres con texto real).")
    if len(alnum) >= 6 and len({c.lower() for c in alnum}) == 1:
        raise ValidationError("El texto parece repetitivo; escribe una descripción real.")
    return limpio


def validar_correo_registro(correo):
    """Valida que el correo de registro no use dominios locales/inválidos ni typos obvios."""
    limpio = (correo or "").strip().lower()
    if not limpio or "@" not in limpio:
        return limpio
    dominio = limpio.rsplit("@", 1)[1]
    if dominio in TYPOS_DOMINIO_CORREO:
        sugerido = TYPOS_DOMINIO_CORREO[dominio]
        raise ValidationError(f"¿Quisiste escribir @{sugerido}? Revisa el dominio de tu correo.")
    partes = dominio.split(".")
    if (
        len(partes) < 2
        or dominio in DOMINIOS_BLOQUEADOS
        or partes[-1] in DOMINIOS_BLOQUEADOS
        or len(partes[-1]) < 2
    ):
        raise ValidationError("Usa un correo electrónico con un dominio real y válido.")
    return limpio


def sanitizar_celda_hoja(valor):
    """Neutraliza prefijos de fórmula (=, +, -, @) al exportar textos a CSV o Excel."""
    if isinstance(valor, str) and valor.lstrip().startswith(PREFIJOS_FORMULA):
        return "'" + valor
    return valor
