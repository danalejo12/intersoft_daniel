"""Cálculo de días hábiles en Colombia y semáforo de vencimiento para PQRS."""
from datetime import date, datetime, timedelta

from django.utils import timezone

# Festivos nacionales de Colombia (fácil de actualizar año a año).
FESTIVOS_COLOMBIA = {
    # 2025
    date(2025, 1, 1),
    date(2025, 1, 6),
    date(2025, 3, 24),
    date(2025, 4, 17),
    date(2025, 4, 18),
    date(2025, 5, 1),
    date(2025, 6, 2),
    date(2025, 6, 23),
    date(2025, 6, 30),
    date(2025, 7, 20),
    date(2025, 8, 7),
    date(2025, 8, 18),
    date(2025, 10, 13),
    date(2025, 11, 3),
    date(2025, 11, 17),
    date(2025, 12, 8),
    date(2025, 12, 25),
    # 2026
    date(2026, 1, 1),
    date(2026, 1, 12),
    date(2026, 3, 23),
    date(2026, 4, 2),
    date(2026, 4, 3),
    date(2026, 5, 1),
    date(2026, 5, 18),
    date(2026, 6, 8),
    date(2026, 6, 15),
    date(2026, 6, 29),
    date(2026, 7, 20),
    date(2026, 8, 7),
    date(2026, 8, 17),
    date(2026, 10, 12),
    date(2026, 11, 2),
    date(2026, 11, 16),
    date(2026, 12, 8),
    date(2026, 12, 25),
    # 2027
    date(2027, 1, 1),
    date(2027, 1, 11),
    date(2027, 3, 22),
    date(2027, 3, 25),
    date(2027, 3, 26),
    date(2027, 5, 1),
    date(2027, 5, 10),
    date(2027, 5, 31),
    date(2027, 6, 7),
    date(2027, 7, 5),
    date(2027, 7, 20),
    date(2027, 8, 7),
    date(2027, 8, 16),
    date(2027, 10, 18),
    date(2027, 11, 1),
    date(2027, 11, 15),
    date(2027, 12, 8),
    date(2027, 12, 25),
}


def es_dia_habil(fecha: date, festivos=None) -> bool:
    """True si la fecha no es sábado, domingo ni festivo colombiano."""
    if isinstance(fecha, datetime):
        fecha = fecha.date()
    conjunto_festivos = FESTIVOS_COLOMBIA if festivos is None else festivos
    return fecha.weekday() < 5 and fecha not in conjunto_festivos


def sumar_dias_habiles(inicio: datetime, dias_habiles: int, festivos=None) -> datetime:
    """Suma `dias_habiles` días hábiles a partir de `inicio`."""
    if dias_habiles <= 0:
        return inicio
    actual = inicio
    restantes = dias_habiles
    while restantes > 0:
        actual += timedelta(days=1)
        if es_dia_habil(actual.date(), festivos=festivos):
            restantes -= 1
    return actual


def dias_habiles_restantes(fecha_limite: datetime, ahora: datetime | None = None, festivos=None) -> int:
    """Cuenta días hábiles restantes hasta `fecha_limite` (negativo si ya venció)."""
    ahora = ahora or timezone.now()
    if ahora > fecha_limite:
        return -1
    hoy = timezone.localdate(ahora)
    limite = timezone.localdate(fecha_limite)
    if hoy >= limite:
        return 0
    dias = 0
    cursor = hoy
    while cursor < limite:
        cursor += timedelta(days=1)
        if es_dia_habil(cursor, festivos=festivos):
            dias += 1
    return dias


def semaforo_pqrs(pqrs, ahora: datetime | None = None, festivos=None) -> str:
    """Devuelve 'verde', 'amarillo' (<=2 días hábiles) o 'rojo' (vencida)."""
    if pqrs.estado in ("respondida", "cerrada"):
        return "verde"
    ahora = ahora or timezone.now()
    if ahora > pqrs.fecha_limite:
        return "rojo"
    restantes = dias_habiles_restantes(pqrs.fecha_limite, ahora=ahora, festivos=festivos)
    if restantes <= 2:
        return "amarillo"
    return "verde"
