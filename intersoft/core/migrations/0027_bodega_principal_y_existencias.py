"""Cada negocio existente recibe su bodega Principal (que también vende en línea) con todo su stock actual.
Así Producto.stock == suma de existencias desde el primer momento."""
from django.db import migrations


def crear_principales(apps, schema_editor):
    Empresa = apps.get_model("core", "Empresa")
    Bodega = apps.get_model("core", "Bodega")
    Existencia = apps.get_model("core", "Existencia")
    Producto = apps.get_model("core", "Producto")
    for empresa in Empresa.objects.all().iterator():
        bodega, _ = Bodega.objects.get_or_create(
            empresa=empresa, es_principal=True,
            defaults={"nombre": "Principal", "vende_en_linea": True, "activa": True},
        )
        Existencia.objects.bulk_create(
            [
                Existencia(empresa=empresa, bodega=bodega, producto_id=pk, cantidad=stock)
                for pk, stock in Producto.objects.filter(empresa=empresa, stock__gt=0).values_list("pk", "stock")
            ],
            ignore_conflicts=True,
        )


class Migration(migrations.Migration):
    dependencies = [("core", "0026_bodegas")]
    operations = [migrations.RunPython(crear_principales, migrations.RunPython.noop)]
