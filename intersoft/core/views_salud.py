"""Endpoint HTTP de verificación de salud para Docker y balanceadores."""
from pathlib import Path

from django.conf import settings
from django.db import connections
from django.http import HttpResponse, JsonResponse


def salud_view(request):
    """Responde 200 si la base de datos contesta; 503 en caso contrario."""
    try:
        with connections["default"].cursor() as cursor:
            cursor.execute("SELECT 1")
            cursor.fetchone()
    except Exception:
        return JsonResponse({"estado": "error", "bd": "no_disponible"}, status=503)
    return JsonResponse({"estado": "ok", "bd": "ok"}, status=200)


def sw_view(request):
    """Sirve el Service Worker en la raíz (/) para habilitar la PWA en todo el sitio."""
    ruta = Path(settings.BASE_DIR) / "core" / "static" / "core" / "js" / "sw.js"
    return HttpResponse(ruta.read_text(encoding="utf-8"), content_type="application/javascript; charset=utf-8")
