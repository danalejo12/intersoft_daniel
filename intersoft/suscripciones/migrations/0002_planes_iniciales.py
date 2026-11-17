"""Migración de datos: siembra idempotente de los 4 planes iniciales de Intersoft.

Por qué una migración de datos con RunPython + update_or_create:
1. Garantiza que tanto en producción, desarrollo como en cada base de datos efímera
   de pruebas (TestCase) existan los 4 planes desde el momento en que corre `migrate`.
2. Usar `apps.get_model` en vez de importar el modelo directamente asegura que la
   migración use el estado histórico del modelo en ese punto del tiempo.
3. `update_or_create` por `codigo` la hace 100% idempotente.
"""
from decimal import Decimal

from django.db import migrations

FEATURES_NEGOCIO = [
    "marketplace",
    "marketplace_destacado",
    "pos",
    "inventario",
    "alertas_inventario",
    "roles",
    "reportes_basicos",
    "reportes_avanzados",
]

PLANES_INICIALES = [
    {
        "codigo": "gratis",
        "defaults": {
            "nombre": "Gratis",
            "precio_mensual": Decimal("0.00"),
            "precio_anual": Decimal("0.00"),
            "comision_porcentaje": Decimal("6.00"),
            "limites": {"productos": 20, "usuarios": 1},
            "features": ["marketplace"],
            "orden": 1,
            "activo": True,
        },
    },
    {
        "codigo": "emprendedor",
        "defaults": {
            "nombre": "Emprendedor",
            "precio_mensual": Decimal("29900.00"),
            "precio_anual": Decimal("299000.00"),
            "comision_porcentaje": Decimal("4.00"),
            "limites": {"productos": 200, "usuarios": 2},
            "features": ["marketplace", "pos", "inventario", "reportes_basicos"],
            "orden": 2,
            "activo": True,
        },
    },
    {
        "codigo": "negocio",
        "defaults": {
            "nombre": "Negocio",
            "precio_mensual": Decimal("69900.00"),
            "precio_anual": Decimal("699000.00"),
            "comision_porcentaje": Decimal("2.50"),
            "limites": {"productos": None, "usuarios": 5},
            "features": list(FEATURES_NEGOCIO),
            "orden": 3,
            "activo": True,
        },
    },
    {
        "codigo": "pro",
        "defaults": {
            "nombre": "Pro",
            "precio_mensual": Decimal("149900.00"),
            "precio_anual": Decimal("1499000.00"),
            "comision_porcentaje": Decimal("1.00"),
            "limites": {"productos": None, "usuarios": None},
            "features": FEATURES_NEGOCIO + [
                "multisede",
                "exportacion",
                "prioridad_busqueda",
                "asistente_ia",
            ],
            "orden": 4,
            "activo": True,
        },
    },
]


def sembrar_planes_iniciales(apps, schema_editor):
    Plan = apps.get_model("suscripciones", "Plan")
    db_alias = schema_editor.connection.alias
    for item in PLANES_INICIALES:
        Plan.objects.using(db_alias).update_or_create(
            codigo=item["codigo"],
            defaults=item["defaults"],
        )


class Migration(migrations.Migration):

    dependencies = [
        ("suscripciones", "0001_initial"),
    ]

    operations = [
        migrations.RunPython(
            code=sembrar_planes_iniciales,
            reverse_code=migrations.RunPython.noop,
        ),
    ]
