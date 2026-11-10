"""Esquema para que el pedido exista sin factura. Lo obligatorio se exige en la 0009, ya con datos."""
from decimal import Decimal

import django.core.validators
import django.db.models.deletion
import uuid
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('core', '0006_comentario_pedido'),
    ]

    operations = [
        migrations.AlterField(
            model_name='pedido',
            name='factura',
            field=models.OneToOneField(blank=True, null=True, on_delete=django.db.models.deletion.PROTECT, related_name='pedido', to='core.factura'),
        ),
        migrations.AddField(
            model_name='pedido',
            name='numero',
            field=models.PositiveIntegerField(null=True),
        ),
        migrations.AddField(
            model_name='pedido',
            name='estado',
            field=models.CharField(choices=[('pendiente', 'Pendiente de pago'), ('pagado', 'Pagado'), ('vencido', 'Vencido'), ('cancelado', 'Cancelado'), ('requiere_reembolso', 'Requiere reembolso')], default='pendiente', max_length=20),
        ),
        migrations.AddField(
            model_name='pedido',
            name='expira_en',
            field=models.DateTimeField(null=True),
        ),
        migrations.AddField(
            model_name='pedido',
            name='renovaciones',
            field=models.PositiveSmallIntegerField(default=0),
        ),
        migrations.AddField(
            model_name='pedido',
            name='subtotal',
            field=models.DecimalField(decimal_places=2, default=Decimal('0'), max_digits=14),
        ),
        migrations.AddField(
            model_name='pedido',
            name='iva',
            field=models.DecimalField(decimal_places=2, default=Decimal('0'), max_digits=14),
        ),
        migrations.AddField(
            model_name='pedido',
            name='total',
            field=models.DecimalField(decimal_places=2, default=Decimal('0'), max_digits=14),
        ),
        migrations.AddField(
            model_name='pedido',
            name='tipo_documento',
            field=models.CharField(default='', max_length=5),
            preserve_default=False,
        ),
        migrations.AddField(
            model_name='pedido',
            name='numero_documento',
            field=models.CharField(default='', max_length=20),
            preserve_default=False,
        ),
        migrations.CreateModel(
            name='DetallePedido',
            fields=[
                ('id', models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ('creado_en', models.DateTimeField(auto_now_add=True)),
                ('actualizado_en', models.DateTimeField(auto_now=True)),
                ('cantidad', models.PositiveIntegerField(validators=[django.core.validators.MinValueValidator(1)])),
                ('precio_unitario', models.DecimalField(decimal_places=2, max_digits=12)),
                ('iva_porcentaje', models.DecimalField(decimal_places=2, max_digits=5)),
                ('empresa', models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name='+', to='core.empresa')),
                ('pedido', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='lineas', to='core.pedido')),
                ('producto', models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name='lineas_pedido', to='core.producto')),
            ],
            options={
                'verbose_name': 'línea de pedido',
                'verbose_name_plural': 'líneas de pedido',
            },
        ),
        migrations.AlterField(
            model_name='pago',
            name='factura',
            field=models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.PROTECT, related_name='pagos', to='core.factura'),
        ),
        migrations.AddField(
            model_name='pago',
            name='pedido',
            field=models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.PROTECT, related_name='pagos', to='core.pedido'),
        ),
    ]
