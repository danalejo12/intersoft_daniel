"""Con los datos ya adaptados, exige lo obligatorio y agrega las restricciones."""
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('core', '0008_pedido_reserva_datos'),
    ]

    operations = [
        migrations.AlterField(
            model_name='pedido',
            name='numero',
            field=models.PositiveIntegerField(),
        ),
        migrations.AlterField(
            model_name='pedido',
            name='expira_en',
            field=models.DateTimeField(),
        ),
        migrations.AddIndex(
            model_name='pedido',
            index=models.Index(fields=['estado', 'expira_en'], name='ix_pedido_estado_expira'),
        ),
        migrations.AddConstraint(
            model_name='pedido',
            constraint=models.UniqueConstraint(fields=('empresa', 'numero'), name='uq_pedido_numero_por_empresa'),
        ),
        migrations.AddConstraint(
            model_name='pedido',
            constraint=models.CheckConstraint(condition=models.Q(('total__gte', 0)), name='ck_pedido_total_no_negativo'),
        ),
        migrations.AddConstraint(
            model_name='detallepedido',
            constraint=models.CheckConstraint(condition=models.Q(('cantidad__gt', 0)), name='ck_linea_pedido_cantidad_positiva'),
        ),
        migrations.AddConstraint(
            model_name='pago',
            constraint=models.UniqueConstraint(condition=models.Q(('estado', 'aprobado')), fields=('pedido',), name='uq_un_pago_aprobado_por_pedido'),
        ),
        migrations.AddConstraint(
            model_name='pago',
            constraint=models.CheckConstraint(condition=models.Q(models.Q(('factura__isnull', False), ('pedido__isnull', True)), models.Q(('factura__isnull', True), ('pedido__isnull', False)), _connector='OR'), name='ck_pago_factura_o_pedido'),
        ),
    ]
