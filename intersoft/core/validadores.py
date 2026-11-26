"""Validadores de formato real para nombres de personas, negocios y NIT."""
import re

from django.core.exceptions import ValidationError

# Nombres y apellidos reales en español/latinoamericano e internacional:
# letras (con tildes, ñ, ü, diacríticos), espacios, guion (Ana-María),
# apóstrofe (O'Connor / D’Angelo) y punto abreviativo (Ma. Fernanda, Jr.).
# Rechaza números, HTML/código (<, >, ;, $, @, !), guiones dobles o bordes.
REGEX_NOMBRE_PERSONA = re.compile(
    r"^[A-Za-zÀ-ÖØ-öø-ÿ]+(?:(?:\.\s|[ '\u2019.-])[A-Za-zÀ-ÖØ-öø-ÿ]+)*\.?$"
)

# Nombres comerciales reales (Colombia y global):
# letras con diacríticos, números (Ferretería 365, 7-Eleven, 3M), espacios,
# guion (mi-empresa), punto (S.A.S., Ltda., Dr. Mueble), & (Café & Pan, H&M),
# apóstrofe (McDonald's, D'Luxe) y coma (Gómez, Pérez & Cía.).
# Rechaza HTML/código (<, >, ;, $, @, !, _, =, /), dobles signos o bordes inválidos.
REGEX_NOMBRE_NEGOCIO = re.compile(
    r"^[A-Za-zÀ-ÖØ-öø-ÿ0-9]+(?:(?:\s*&\s*|[.,]\s+|[ '\u2019.&,-])[A-Za-zÀ-ÖØ-öø-ÿ0-9]+)*\.?$"
)

# NIT colombiano: solo dígitos, con separadores opcionales (puntos, espacios) y guion de DV.
REGEX_NIT_COLOMBIA = re.compile(r"^[0-9]+(?:[.\s-][0-9]+)*$")


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
    """Normaliza espacios y valida que el nombre del negocio use solo letras, números y signos comerciales válidos."""
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
