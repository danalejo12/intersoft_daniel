"""Datos de la política de tratamiento (Decreto 1377 de 2013, art. 13): versión, responsable y finalidades.

Los datos del responsable (razón social, NIT, dirección, correo y teléfono) se configuran en el .env
(DATOS_RESPONSABLE_*). Mientras falten, la política lo indica en rojo: no se inventan datos de la empresa.
"""
from django.conf import settings

# Cambiar la versión cuando cambie el texto de la política: a cada titular se le vuelve a pedir autorización.
VERSION_POLITICA = "1.0 · 24 de noviembre de 2026"

FINALIDADES = (
    "Crear y administrar tu cuenta y autenticarte de forma segura.",
    "Gestionar tus compras en el marketplace: pedidos, pagos con Wompi, facturación y envío por el negocio vendedor.",
    "Atender peticiones, quejas, reclamos, sugerencias y solicitudes sobre tus datos personales.",
    "Enviarte notificaciones del servicio (estado de pedidos, pagos, PQRS, vencimientos del plan).",
    "Prevenir fraude y garantizar la seguridad de la plataforma (registros de acceso y auditoría).",
    "Cumplir obligaciones legales, contables y tributarias.",
)

# Terceros que reciben datos para prestar el servicio (transmisión a encargados, Decreto 1377 art. 25)
ENCARGADOS = (
    ("Wompi (Bancolombia)", "Procesar pagos. InterSoft nunca recibe ni guarda los datos completos de tu tarjeta."),
    ("Proveedor de correo electrónico", "Enviar notificaciones transaccionales."),
    ("Proveedor de alojamiento en la nube", "Guardar la base de datos y los archivos de forma cifrada y segura."),
    ("El negocio vendedor", "Despachar tu pedido y facturarlo: recibe tu nombre, documento, contacto y dirección."),
)

PLAZO_CONSULTA_DIAS = 10   # Ley 1581 art. 14 (prorrogable 5 días hábiles)
PLAZO_RECLAMO_DIAS = 15    # Ley 1581 art. 15 (prorrogable 8 días hábiles)


def responsable() -> dict:
    """Identificación del responsable del tratamiento según el .env; marca lo que falta por configurar."""
    datos = {
        "razon_social": getattr(settings, "DATOS_RESPONSABLE_RAZON_SOCIAL", ""),
        "nit": getattr(settings, "DATOS_RESPONSABLE_NIT", ""),
        "direccion": getattr(settings, "DATOS_RESPONSABLE_DIRECCION", ""),
        "correo": getattr(settings, "DATOS_RESPONSABLE_CORREO", ""),
        "telefono": getattr(settings, "DATOS_RESPONSABLE_TELEFONO", ""),
    }
    datos["faltantes"] = [campo for campo, valor in datos.items() if not valor]
    return datos
