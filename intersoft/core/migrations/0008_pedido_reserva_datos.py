"""Adapta los pedidos que ya existen, creados cuando la factura nacía al confirmar el envío.

- Con pago aprobado: pasa a pagado y conserva su factura y sus pagos.
- Con factura anulada: pasa a cancelado (el stock ya se había devuelto).
- Sin pagar: se anula su factura, se devuelve el stock y pasa a cancelado.

Los pagos siguen en su factura, y las facturas sin pedido no se tocan.
"""
from django.db import migrations
from django.db.models import F
from django.utils import timezone


def adaptar_pedidos(apps, schema_editor):
    Pedido = apps.get_model("core", "Pedido")
    DetallePedido = apps.get_model("core", "DetallePedido")
    DetalleFactura = apps.get_model("core", "DetalleFactura")
    Pago = apps.get_model("core", "Pago")
    Producto = apps.get_model("core", "Producto")
    MovimientoInventario = apps.get_model("core", "MovimientoInventario")

    for pedido in Pedido.objects.select_related("factura__cliente"):
        factura = pedido.factura
        pedido.numero = factura.numero
        pedido.expira_en = pedido.creado_en
        pedido.subtotal = factura.subtotal
        pedido.iva = factura.iva
        pedido.total = factura.total
        pedido.tipo_documento = factura.cliente.tipo_documento
        pedido.numero_documento = factura.cliente.numero_documento

        detalles = list(DetalleFactura.objects.filter(factura=factura))
        DetallePedido.objects.bulk_create(
            DetallePedido(
                empresa_id=pedido.empresa_id,
                pedido=pedido,
                producto_id=detalle.producto_id,
                cantidad=detalle.cantidad,
                precio_unitario=detalle.precio_unitario,
                iva_porcentaje=detalle.iva_porcentaje,
            )
            for detalle in detalles
        )

        if factura.estado == "anulada":
            pedido.estado = "cancelado"
        elif Pago.objects.filter(factura=factura, estado="aprobado").exists():
            pedido.estado = "pagado"
        else:
            for detalle in detalles:
                Producto.objects.filter(pk=detalle.producto_id).update(stock=F("stock") + detalle.cantidad)
                MovimientoInventario.objects.create(
                    empresa_id=pedido.empresa_id,
                    producto_id=detalle.producto_id,
                    tipo="entrada",
                    cantidad=detalle.cantidad,
                    referencia=f"Liberación pedido {pedido.numero}",
                    usuario_id=pedido.comprador_id,
                )
            factura.estado = "anulada"
            factura.anulada_en = timezone.now()
            factura.save(update_fields=["estado", "anulada_en"])
            pedido.estado = "cancelado"

        pedido.save()


class Migration(migrations.Migration):

    dependencies = [
        ('core', '0007_pedido_reserva_esquema'),
    ]

    operations = [
        # Al revertir no se puede reconstruir la reserva: la copia de seguridad cubre ese caso
        migrations.RunPython(adaptar_pedidos, migrations.RunPython.noop),
    ]
