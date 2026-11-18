"""Endpoint HTTP de verificación de salud para Docker y balanceadores."""
from django.db import connections
from django.http import JsonResponse


def salud_view(request):
    """Responde 200 si la base de datos contesta; 503 en caso contrario."""
    try:
        with connections["default"].cursor() as cursor:
            cursor.execute("SELECT 1")
            cursor.fetchone()
    except Exception:
        return JsonResponse({"estado": "error", "bd": "no_disponible"}, status=503)
    return JsonResponse({"estado": "ok", "bd": "ok"}, status=200)
