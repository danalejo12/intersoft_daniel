"""Servicios de protección de datos: autorización, solicitudes del titular, exportación y supresión."""
import logging
import uuid

from django.conf import settings
from django.core.exceptions import ValidationError
from django.core.mail import send_mail
from django.db import transaction
from django.utils import timezone

from pqrs.dias_habiles import sumar_dias_habiles

from . import politica
from .models import AutorizacionDatos, SolicitudDatos, generar_radicado

logger = logging.getLogger(__name__)


# ---------- Autorización ----------
def autorizacion_vigente(usuario):
    """Autorización no revocada del titular para la versión actual de la política, o None."""
    if not getattr(usuario, "is_authenticated", False):
        return None
    return (AutorizacionDatos.objects
            .filter(usuario=usuario, version_politica=politica.VERSION_POLITICA, revocada_en__isnull=True)
            .first())


def registrar_autorizacion(usuario, *, medio, request=None, mayor_de_edad=True):
    """Guarda la prueba de la autorización (versión, finalidades, fecha, IP y navegador). Idempotente."""
    existente = autorizacion_vigente(usuario)
    if existente:
        return existente
    ip, navegador = None, ""
    if request is not None:
        from core.ratelimit import obtener_ip_cliente

        ip = obtener_ip_cliente(request)
        ip = None if ip in ("", "0.0.0.0") else ip
        navegador = (request.META.get("HTTP_USER_AGENT") or "")[:300]
    return AutorizacionDatos.objects.create(
        usuario=usuario, version_politica=politica.VERSION_POLITICA, finalidades=list(politica.FINALIDADES),
        medio=medio, ip=ip, navegador=navegador, mayor_de_edad=mayor_de_edad,
    )


def revocar_autorizaciones(usuario):
    """Marca como revocadas las autorizaciones vigentes del titular (quedan como prueba histórica)."""
    return AutorizacionDatos.objects.filter(usuario=usuario, revocada_en__isnull=True).update(revocada_en=timezone.now())


# ---------- Solicitudes del titular ----------
def _correo(asunto, mensaje, destinatarios):
    """Envía un correo sin interrumpir el trámite si el servidor de correo falla."""
    limpios = [d for d in dict.fromkeys(destinatarios) if d]
    if not limpios:
        return
    try:
        send_mail(asunto, mensaje, settings.DEFAULT_FROM_EMAIL, limpios, fail_silently=False)
    except Exception:  # noqa: BLE001 - el registro de la solicitud no depende del correo
        logger.warning("No se pudo enviar el correo de la solicitud de datos personales", exc_info=True)


def _correos_responsable():
    """Correo del responsable del tratamiento y de los administradores."""
    correos = [politica.responsable()["correo"]]
    correos += [correo for _, correo in getattr(settings, "ADMINS", [])]
    return correos


@transaction.atomic
def radicar_solicitud(*, titular, tipo, detalle=""):
    """Radica una consulta o un reclamo con su plazo legal en días hábiles y avisa al titular y al responsable."""
    if tipo not in SolicitudDatos.Tipo.values:
        raise ValidationError("Tipo de solicitud no válido.")
    dias = politica.PLAZO_CONSULTA_DIAS if tipo in SolicitudDatos.CONSULTAS else politica.PLAZO_RECLAMO_DIAS
    solicitud = SolicitudDatos.objects.create(
        radicado=generar_radicado(), titular=titular, tipo=tipo, detalle=(detalle or "").strip()[:2000],
        fecha_limite=sumar_dias_habiles(timezone.now(), dias),
    )
    plazo = timezone.localtime(solicitud.fecha_limite).strftime("%d/%m/%Y")
    _correo(
        f"Radicamos tu solicitud {solicitud.radicado} sobre tus datos personales",
        f"Hola,\n\nRecibimos tu solicitud «{solicitud.get_tipo_display()}» con el radicado {solicitud.radicado}.\n"
        f"Te responderemos a más tardar el {plazo} ({dias} días hábiles, según la Ley 1581 de 2012).\n",
        [titular.email],
    )
    _correo(f"Nueva solicitud de datos personales {solicitud.radicado}",
            f"Tipo: {solicitud.get_tipo_display()}\nTitular: {titular.email}\nPlazo: {plazo}\n\n{solicitud.detalle}",
            _correos_responsable())
    return solicitud


@transaction.atomic
def responder_solicitud(solicitud, *, respuesta, actor, rechazar=False):
    """Responde la solicitud, deja quién la atendió y le envía la respuesta al titular."""
    texto = (respuesta or "").strip()
    if not texto:
        raise ValidationError("Escribe la respuesta para el titular.")
    solicitud = SolicitudDatos.objects.select_for_update().get(pk=solicitud.pk)
    solicitud.respuesta = texto
    solicitud.estado = SolicitudDatos.Estado.RECHAZADA if rechazar else SolicitudDatos.Estado.RESPONDIDA
    solicitud.atendida_por = actor
    solicitud.respondida_en = timezone.now()
    solicitud.save()
    _correo(f"Respuesta a tu solicitud {solicitud.radicado}", texto, [solicitud.titular.email])
    return solicitud


# ---------- Derecho a conocer: exportación ----------
def exportar_datos(usuario) -> dict:
    """Todos los datos personales que InterSoft tiene del titular, en un formato legible (JSON)."""
    from core.models import Comentario, Membresia, Pedido
    from pqrs.models import PQRS

    def fecha(valor):
        return timezone.localtime(valor).isoformat() if valor else None

    return {
        "generado_en": fecha(timezone.now()),
        "politica_vigente": politica.VERSION_POLITICA,
        "cuenta": {
            "nombres": usuario.first_name, "apellidos": usuario.last_name, "correo": usuario.email,
            "telefono": usuario.telefono, "cargo": usuario.cargo, "descripcion": usuario.descripcion,
            "fecha_registro": fecha(usuario.date_joined), "ultimo_ingreso": fecha(usuario.last_login),
        },
        "autorizaciones": [
            {"version": a.version_politica, "aceptada_en": fecha(a.aceptada_en), "medio": a.medio,
             "ip": a.ip, "finalidades": a.finalidades, "revocada_en": fecha(a.revocada_en)}
            for a in usuario.autorizaciones_datos.all()
        ],
        "negocios": [
            {"negocio": m.empresa.nombre, "rol": m.rol.nombre, "activa": m.activa}
            for m in Membresia.objects.filter(usuario=usuario).select_related("empresa", "rol")
        ],
        "pedidos": [
            {"negocio": p.empresa.nombre, "numero": p.numero, "fecha": fecha(p.creado_en), "estado": p.get_estado_display(),
             "total": str(p.total), "nombre": p.nombre, "documento": f"{p.tipo_documento} {p.numero_documento}",
             "correo": p.email, "telefono": p.telefono,
             "direccion": f"{p.direccion}, {p.ciudad}, {p.departamento}", "indicaciones": p.indicaciones}
            for p in Pedido.objects.filter(comprador=usuario).select_related("empresa")
        ],
        "opiniones": [
            {"producto": c.producto.nombre, "calificacion": c.calificacion, "texto": c.texto, "fecha": fecha(c.creado_en)}
            for c in Comentario.objects.filter(autor=usuario).select_related("producto")
        ],
        "pqrs": [
            {"radicado": q.radicado, "asunto": q.asunto, "estado": q.get_estado_display(), "fecha": fecha(q.creado_en)}
            for q in PQRS.objects.filter(autor=usuario)
        ],
        "solicitudes_de_datos": [
            {"radicado": s.radicado, "tipo": s.get_tipo_display(), "estado": s.get_estado_display(),
             "fecha": fecha(s.creado_en), "respuesta": s.respuesta}
            for s in usuario.solicitudes_datos.all()
        ],
    }


# ---------- Derecho a la supresión ----------
class SupresionNoPermitida(ValidationError):
    """La supresión no se puede ejecutar todavía (el mensaje explica qué hacer)."""


@transaction.atomic
def suprimir_datos_titular(usuario, *, actor=None):
    """Suprime los datos personales del titular anonimizándolos y cierra su cuenta.

    Se conservan, anonimizados, los registros que la ley obliga a guardar (facturas, pedidos y PQRS, por
    obligaciones contables y tributarias), sin datos que identifiquen a la persona. Las opiniones, los
    favoritos, las encuestas y los comentarios de soporte se eliminan. No se ejecuta si el titular es el único
    administrador activo de un negocio activo: primero debe entregar la administración a otra persona."""
    from core.models import Comentario, Favorito, Membresia, Pedido

    unico_admin = [
        m.empresa.nombre for m in Membresia.objects.filter(usuario=usuario, activa=True, rol__es_admin=True,
                                                           empresa__activa=True).select_related("empresa")
        if not Membresia.objects.filter(empresa=m.empresa, activa=True, rol__es_admin=True)
        .exclude(usuario=usuario).exists()
    ]
    if unico_admin:
        raise SupresionNoPermitida(
            "El titular es el único administrador de: " + ", ".join(unico_admin)
            + ". Debe asignar otro administrador antes de suprimir sus datos."
        )

    anonimo = f"suprimido-{uuid.uuid4().hex[:12]}@anonimo.invalid"
    Pedido.objects.filter(comprador=usuario).update(
        nombre="Titular suprimido", email=anonimo, telefono="", numero_documento="SUPRIMIDO",
        direccion="Dirección suprimida", indicaciones="",
    )
    Comentario.objects.filter(autor=usuario).delete()
    Favorito.objects.filter(usuario=usuario).delete()
    try:
        from soporte.models import ComentarioWidget, EncuestaNPS, ErrorRegistrado, ReporteProblema

        ComentarioWidget.objects.filter(usuario=usuario).delete()
        EncuestaNPS.objects.filter(usuario=usuario).delete()
        ReporteProblema.objects.filter(usuario=usuario).delete()
        ErrorRegistrado.objects.filter(usuario=usuario).update(usuario=None)
    except ImportError:  # la app de soporte es opcional
        pass
    Membresia.objects.filter(usuario=usuario).update(activa=False)
    revocar_autorizaciones(usuario)

    if usuario.foto:
        usuario.foto.delete(save=False)
    usuario.first_name, usuario.last_name = "Titular", "suprimido"
    usuario.email = usuario.username = anonimo
    usuario.telefono = usuario.cargo = usuario.descripcion = ""
    usuario.foto = None
    usuario.is_active = False
    usuario.set_unusable_password()
    usuario.save()
    logger.info("Datos del titular %s suprimidos por %s", usuario.pk, getattr(actor, "pk", "el sistema"))
    return usuario


@transaction.atomic
def atender_supresion(solicitud, *, respuesta, actor):
    """Responde la solicitud de supresión o revocatoria y luego anonimiza al titular.

    Primero se envía la respuesta al correo real del titular, porque después de suprimir ese correo ya no existe."""
    if solicitud.tipo not in (SolicitudDatos.Tipo.SUPRIMIR, SolicitudDatos.Tipo.REVOCAR):
        raise ValidationError("Solo las solicitudes de supresión o revocatoria eliminan datos.")
    solicitud = responder_solicitud(solicitud, respuesta=respuesta, actor=actor)
    suprimir_datos_titular(solicitud.titular, actor=actor)
    solicitud.datos_suprimidos_en = timezone.now()
    solicitud.save(update_fields=["datos_suprimidos_en", "actualizado_en"])
    return solicitud
