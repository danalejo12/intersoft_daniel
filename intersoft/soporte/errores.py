"""Captura automática de errores 500 agrupados por huella, sin datos sensibles."""
import hashlib
import logging
import os
import sys
import traceback

from django.conf import settings
from django.core.mail import mail_admins
from django.db import IntegrityError, transaction
from django.utils import timezone

from core.cifrado import FiltroSecretosPago

from .models import ErrorRegistrado

logger = logging.getLogger(__name__)
FILTRO_SECRETOS = FiltroSecretosPago()


def _es_trama_propia(filename: str) -> bool:
    """Indica si una trama de la traza es del proyecto (no de librerías)."""
    if not filename:
        return False
    ruta = os.path.abspath(filename)
    base = os.path.abspath(str(settings.BASE_DIR))
    return ruta.startswith(base) and "site-packages" not in ruta and ".venv" not in ruta


def _ubicacion_ultima_trama(exc_tb) -> tuple[str, int]:
    """Archivo y línea de la última trama propia del error (o de la última trama si no hay propias)."""
    tramas = traceback.extract_tb(exc_tb)
    if not tramas:
        return "", 0
    propias = [t for t in tramas if _es_trama_propia(t.filename)]
    elegida = propias[-1] if propias else tramas[-1]
    try:
        archivo = os.path.relpath(elegida.filename, str(settings.BASE_DIR))
    except ValueError:
        archivo = elegida.filename
    return archivo[:255], int(elegida.lineno or 0)


def _formatear_traza_sanitizada(request, exc_type, exc_value, exc_tb) -> str:
    """Formatea la traza aplicando FiltroSecretosPago sobre variables locales, sin cuerpo POST."""
    lineas = ["Traceback (most recent call last):"]
    nodo = exc_tb
    while nodo is not None:
        frame = nodo.tb_frame
        lineno = nodo.tb_lineno
        code = frame.f_code
        filename = code.co_filename
        try:
            filename_rel = os.path.relpath(filename, str(settings.BASE_DIR))
        except ValueError:
            filename_rel = filename
        lineas.append(f'  File "{filename_rel}", line {lineno}, in {code.co_name}')
        try:
            vars_limpias = FILTRO_SECRETOS.get_traceback_frame_variables(request, frame)
            if vars_limpias:
                resumen = ", ".join(f"{k}={repr(v)[:120]}" for k, v in vars_limpias[:12])
                lineas.append(f"    Locals: {resumen}")
        except Exception:
            pass
        nodo = nodo.tb_next

    lineas.extend(traceback.format_exception_only(exc_type, exc_value))
    return "\n".join(lineas).strip()


def _calcular_huella(tipo_excepcion: str, archivo: str, linea: int) -> str:
    """Huella del error (tipo + archivo + línea) para agrupar ocurrencias iguales."""
    clave = f"{tipo_excepcion}|{archivo}|{linea}"
    return hashlib.sha256(clave.encode("utf-8")).hexdigest()


def _notificar_admins_huella_nueva(error_obj: ErrorRegistrado) -> None:
    """Avisa por correo a ADMINS la primera vez que aparece un error; nunca lanza excepciones."""
    try:
        if not getattr(settings, "ADMINS", None):
            return
        asunto = f"[Intersoft 500] {error_obj.tipo_excepcion} en {error_obj.archivo}:{error_obj.linea}"
        cuerpo = (
            f"Se detectó un nuevo error 500 en Intersoft.\n\n"
            f"Tipo: {error_obj.tipo_excepcion}\n"
            f"Archivo: {error_obj.archivo}:{error_obj.linea}\n"
            f"URL: {error_obj.metodo} {error_obj.url}\n"
            f"Mensaje: {error_obj.mensaje[:300]}\n"
        )
        mail_admins(subject=asunto, message=cuerpo, fail_silently=True)
    except Exception:
        logger.warning("No se pudo enviar alerta a ADMINS por error 500.", exc_info=True)


def registrar_excepcion(request, exc_type=None, exc_value=None, exc_tb=None) -> ErrorRegistrado | None:
    """Registra o agrupa un error 500 por huella sin lanzar jamás una excepción secundaria."""
    try:
        if exc_type is None or exc_tb is None:
            exc_type, exc_value, exc_tb = sys.exc_info()
        if exc_type is None:
            return None

        tipo_excepcion = exc_type.__name__[:120]
        mensaje = str(exc_value or "")[:1000]
        archivo, linea = _ubicacion_ultima_trama(exc_tb)
        huella = _calcular_huella(tipo_excepcion, archivo, linea)
        traza = _formatear_traza_sanitizada(request, exc_type, exc_value, exc_tb)

        url = ""
        metodo = ""
        empresa = None
        usuario = None
        if request is not None:
            try:
                url = (request.get_full_path() or "")[:500]
                metodo = (getattr(request, "method", "") or "")[:12]
                empresa = getattr(request, "empresa", None)
                user = getattr(request, "user", None)
                if user is not None and getattr(user, "is_authenticated", False):
                    usuario = user
            except Exception:
                pass

        ahora = timezone.now()
        es_nuevo = False
        with transaction.atomic():
            obj = ErrorRegistrado.objects.select_for_update().filter(huella=huella).first()
            if obj is None:
                try:
                    with transaction.atomic():
                        obj = ErrorRegistrado.objects.create(
                            huella=huella,
                            tipo_excepcion=tipo_excepcion,
                            mensaje=mensaje,
                            archivo=archivo,
                            linea=linea,
                            traza=traza,
                            url=url,
                            metodo=metodo,
                            empresa=empresa,
                            usuario=usuario,
                            contador=1,
                            primera_vez=ahora,
                            ultima_vez=ahora,
                            estado=ErrorRegistrado.Estado.NUEVO,
                        )
                        es_nuevo = True
                except IntegrityError:
                    obj = ErrorRegistrado.objects.select_for_update().get(huella=huella)

            if not es_nuevo:
                obj.contador += 1
                obj.ultima_vez = ahora
                obj.mensaje = mensaje
                obj.traza = traza
                obj.url = url
                obj.metodo = metodo
                if empresa is not None:
                    obj.empresa = empresa
                if usuario is not None:
                    obj.usuario = usuario
                if obj.estado == ErrorRegistrado.Estado.RESUELTO:
                    obj.estado = ErrorRegistrado.Estado.NUEVO
                obj.save(
                    update_fields=[
                        "contador",
                        "ultima_vez",
                        "mensaje",
                        "traza",
                        "url",
                        "metodo",
                        "empresa",
                        "usuario",
                        "estado",
                        "actualizado_en",
                    ]
                )

        if es_nuevo:
            _notificar_admins_huella_nueva(obj)
        return obj
    except Exception:
        logger.exception("Fallo interno al registrar un error 500 en soporte.errores.")
        return None


def capturar_excepcion_request(sender, request=None, **kwargs):
    """Receptor de la señal got_request_exception de Django."""
    registrar_excepcion(request)
