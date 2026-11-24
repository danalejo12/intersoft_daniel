"""Diagnóstico técnico para la sección Operación de /plataforma/.

Cada revisión es independiente: si una falla, se muestra en rojo y las demás siguen. Nunca se devuelven
valores secretos (llaves, contraseñas, DSN): solo si están configurados.
"""
import platform
import time
from dataclasses import dataclass, field
from datetime import timedelta
from pathlib import Path

import django
from django.conf import settings
from django.core.cache import cache
from django.core.checks import run_checks
from django.db import DEFAULT_DB_ALIAS, connection, connections
from django.db.migrations.executor import MigrationExecutor
from django.utils import timezone

from core.models import EjecucionTarea
from core.tareas import TAREAS

OK, AVISO, FALLA = "ok", "aviso", "falla"


@dataclass
class Revision:
    """Resultado de una revisión del estado del sistema (ok, aviso o falla) con su resumen y detalle."""
    nombre: str
    estado: str
    resumen: str
    detalle: str = ""


@dataclass
class EstadoTarea:
    """Estado de una tarea periódica para la sección Operación: última ejecución, próxima y fallos."""
    nombre: str
    descripcion: str
    cada: timedelta
    ultima_ejecucion: object = None
    proxima: object = None
    ejecuciones: int = 0
    fallos_seguidos: int = 0
    ultimo_resultado: str = ""
    ultimo_error: str = ""
    atrasada: bool = False
    estado: str = OK
    cada_texto: str = field(default="")


def _texto_intervalo(intervalo: timedelta) -> str:
    """Texto legible de un intervalo: «cada 5 min», «cada hora», «cada día»."""
    minutos = int(intervalo.total_seconds() // 60)
    if minutos < 60:
        return f"cada {minutos} min"
    horas = minutos // 60
    if horas < 24:
        return "cada hora" if horas == 1 else f"cada {horas} h"
    dias = horas // 24
    return "cada día" if dias == 1 else f"cada {dias} días"


def _seguro(nombre, funcion):
    """Ejecuta una revisión; si explota, la reporta como falla en vez de romper la página."""
    try:
        return funcion()
    except Exception as error:  # noqa: BLE001 - diagnóstico: cualquier fallo se muestra
        return Revision(nombre, FALLA, "No se pudo revisar", f"{type(error).__name__}: {error}"[:300])


# ---------- Revisiones ----------
def revisar_base_de_datos():
    """Revisa que la base de datos responda y mide su tiempo de respuesta."""
    inicio = time.perf_counter()
    with connection.cursor() as cursor:
        cursor.execute("SELECT 1")
        cursor.fetchone()
        version = ""
        if connection.vendor == "postgresql":
            cursor.execute("SHOW server_version")
            version = f"PostgreSQL {cursor.fetchone()[0]}"
    ms = (time.perf_counter() - inicio) * 1000
    estado = OK if ms < 200 else AVISO
    return Revision("Base de datos", estado, f"Responde en {ms:.0f} ms", version or connection.vendor)


def revisar_migraciones():
    """Revisa si hay migraciones sin aplicar."""
    ejecutor = MigrationExecutor(connections[DEFAULT_DB_ALIAS])
    pendientes = ejecutor.migration_plan(ejecutor.loader.graph.leaf_nodes())
    if not pendientes:
        return Revision("Migraciones", OK, "Todas aplicadas")
    nombres = ", ".join(f"{m.app_label}.{m.name}" for m, _ in pendientes[:6])
    return Revision("Migraciones", FALLA, f"{len(pendientes)} pendiente(s)",
                    f"Ejecuta «python manage.py migrate». {nombres}")


def revisar_cache():
    """Revisa que la caché guarde datos y avisa si no es compartida entre procesos."""
    backend = settings.CACHES["default"]["BACKEND"].rsplit(".", 1)[-1]
    clave = "plataforma:diagnostico"
    cache.set(clave, "ok", 10)
    if cache.get(clave) != "ok":
        return Revision("Caché", FALLA, f"{backend} no guarda datos")
    if "LocMem" in backend:
        return Revision("Caché", AVISO, "Memoria local del proceso",
                        "Funciona, pero no se comparte entre procesos. En producción define REDIS_URL.")
    return Revision("Caché", OK, backend)


def revisar_correo():
    """Revisa que el correo salga de verdad y que haya ADMINS para las alertas."""
    backend = settings.EMAIL_BACKEND.rsplit(".", 1)[-1]
    if "console" in settings.EMAIL_BACKEND or "locmem" in settings.EMAIL_BACKEND:
        return Revision("Correo", AVISO, "Solo se muestra en consola",
                        "Los correos (PQRS, alertas, recordatorios) no salen. Configura EMAIL_HOST.")
    destinatarios = len(getattr(settings, "ADMINS", []) or [])
    return Revision("Correo", OK if destinatarios else AVISO, backend,
                    f"{destinatarios} administrador(es) reciben alertas" if destinatarios
                    else "Nadie recibe las alertas CRITICAL: define ADMINS.")


def revisar_monitoreo():
    """Revisa si el monitoreo de errores con Sentry está configurado."""
    if getattr(settings, "SENTRY_DSN", ""):
        return Revision("Monitoreo", OK, "Sentry configurado")
    return Revision("Monitoreo", AVISO, "Sin Sentry", "Los errores solo quedan en la bitácora de Soporte.")


def revisar_cifrado():
    """Revisa que haya una clave propia para cifrar los secretos de pago."""
    if getattr(settings, "PAGOS_CLAVES_CIFRADO", ""):
        return Revision("Cifrado de pagos", OK, "Clave propia configurada")
    return Revision("Cifrado de pagos", AVISO, "Derivado de SECRET_KEY",
                    "Define PAGOS_CLAVES_CIFRADO: si cambia SECRET_KEY no se podrían leer las llaves guardadas.")


def revisar_modo():
    """Revisa si DEBUG está activo."""
    if settings.DEBUG:
        return Revision("Modo", AVISO, "DEBUG activo", "Correcto en desarrollo; nunca en producción.")
    return Revision("Modo", OK, "Producción (DEBUG apagado)")


def carpeta_respaldos() -> Path:
    return Path(getattr(settings, "RESPALDOS_DIR", "") or (Path(settings.BASE_DIR).parent / "backups" / "postgres"))


def revisar_respaldos():
    """Revisa la copia de seguridad más reciente (falla si tiene más de 26 horas)."""
    carpeta = carpeta_respaldos()
    archivos = sorted(carpeta.glob("*.dump"), key=lambda a: a.stat().st_mtime, reverse=True) if carpeta.is_dir() else []
    if not archivos:
        return Revision("Copias de seguridad", AVISO, "No se encontraron copias",
                        f"Programa deploy/backup_postgres.sh (busco en {carpeta}).")
    ultimo = archivos[0]
    edad = timezone.now().timestamp() - ultimo.stat().st_mtime
    horas = edad / 3600
    tamano = ultimo.stat().st_size / (1024 * 1024)
    resumen = f"Última hace {horas:.0f} h" if horas >= 1 else "Última hace menos de 1 h"
    detalle = f"{ultimo.name} · {tamano:.1f} MB · {len(archivos)} copia(s)"
    return Revision("Copias de seguridad", OK if horas <= 26 else FALLA, resumen, detalle)


def revisar_errores():
    """Revisa los errores 500 nuevos y los de las últimas 24 horas."""
    from soporte.models import ErrorRegistrado

    desde = timezone.now() - timedelta(hours=24)
    nuevos = ErrorRegistrado.objects.filter(estado=ErrorRegistrado.Estado.NUEVO).count()
    recientes = ErrorRegistrado.objects.filter(ultima_vez__gte=desde).count()
    if not nuevos and not recientes:
        return Revision("Errores", OK, "Sin errores en 24 h")
    return Revision("Errores", FALLA if nuevos else AVISO,
                    f"{recientes} en 24 h · {nuevos} sin revisar", "Revísalos en la sección Errores.")


# ---------- Tareas periódicas ----------
def estado_tareas(ahora=None):
    """Estado de cada tarea periódica: última y próxima ejecución, fallos y si está atrasada."""
    ahora = ahora or timezone.now()
    filas = {f.nombre: f for f in EjecucionTarea.objects.all()}
    resultado = []
    for tarea in TAREAS:
        fila = filas.get(tarea.nombre)
        estado = EstadoTarea(nombre=tarea.nombre, descripcion=tarea.descripcion, cada=tarea.cada,
                             cada_texto=_texto_intervalo(tarea.cada))
        if fila is None or fila.ultima_ejecucion is None:
            estado.estado = AVISO
            estado.atrasada = True
        else:
            estado.ultima_ejecucion = fila.ultima_ejecucion
            estado.proxima = fila.ultima_ejecucion + tarea.cada
            estado.ejecuciones = fila.ejecuciones
            estado.fallos_seguidos = fila.fallos_seguidos
            estado.ultimo_resultado = fila.ultimo_resultado
            estado.ultimo_error = fila.ultimo_error
            # Más del doble del intervalo sin correr: el programador probablemente está detenido
            estado.atrasada = ahora - fila.ultima_ejecucion > tarea.cada * 2 + timedelta(minutes=2)
            if fila.fallos_seguidos:
                estado.estado = FALLA
            elif estado.atrasada:
                estado.estado = AVISO
        resultado.append(estado)
    return resultado


def revisar_tareas(tareas=None):
    """Resumen de las tareas periódicas: falla si alguna tiene fallos, aviso si alguna está atrasada."""
    tareas = tareas if tareas is not None else estado_tareas()
    con_fallos = [t for t in tareas if t.fallos_seguidos]
    atrasadas = [t for t in tareas if t.atrasada]
    if con_fallos:
        return Revision("Tareas periódicas", FALLA, f"{len(con_fallos)} con fallos",
                        ", ".join(t.nombre for t in con_fallos))
    if atrasadas:
        return Revision("Tareas periódicas", AVISO, f"{len(atrasadas)} atrasada(s)",
                        "¿Está corriendo «tareas_periodicas»? Revisa el contenedor scheduler o el cron.")
    return Revision("Tareas periódicas", OK, f"{len(tareas)} al día")


# ---------- Resumen ----------
def diagnostico():
    """Todas las revisiones del sistema y el conteo de fallas y avisos."""
    tareas = estado_tareas()
    revisiones = [
        _seguro("Base de datos", revisar_base_de_datos),
        _seguro("Migraciones", revisar_migraciones),
        _seguro("Tareas periódicas", lambda: revisar_tareas(tareas)),
        _seguro("Errores", revisar_errores),
        _seguro("Copias de seguridad", revisar_respaldos),
        _seguro("Caché", revisar_cache),
        _seguro("Correo", revisar_correo),
        _seguro("Monitoreo", revisar_monitoreo),
        _seguro("Cifrado de pagos", revisar_cifrado),
        _seguro("Modo", revisar_modo),
    ]
    return {
        "revisiones": revisiones,
        "tareas": tareas,
        "fallas": sum(1 for r in revisiones if r.estado == FALLA),
        "avisos": sum(1 for r in revisiones if r.estado == AVISO),
    }


def revision_despliegue():
    """Lo mismo que «manage.py check --deploy», para ver qué falta antes de producción."""
    mensajes = run_checks(include_deployment_checks=True)
    return [
        {"id": m.id or "", "nivel": "error" if m.is_serious() else "aviso", "mensaje": str(m.msg), "ayuda": m.hint or ""}
        for m in mensajes
        if not m.is_silenced()
    ]


def entorno():
    """Datos del entorno: versiones, base de datos, zona horaria y hosts permitidos."""
    hosts = list(getattr(settings, "ALLOWED_HOSTS", []) or [])
    return [
        ("Versión de Intersoft", getattr(settings, "APP_VERSION", "") or settings.SPECTACULAR_SETTINGS.get("VERSION", "")),
        ("Python", platform.python_version()),
        ("Django", django.get_version()),
        ("Base de datos", connection.vendor),
        ("Zona horaria", settings.TIME_ZONE),
        ("Hosts permitidos", ", ".join(hosts) if hosts else "(ninguno)"),
        ("Servidor", platform.platform(terse=True)),
    ]
