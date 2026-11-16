import uuid
from decimal import Decimal

from django.conf import settings
from django.core.validators import MaxValueValidator, MinValueValidator
from django.db import models
from django.db.models import Q
from django.views.decorators.debug import sensitive_variables

from ..cifrado import cifrar, descifrar
from .base import ModeloTenant


class Pago(ModeloTenant):
    """Un intento de cobro de una factura a través de la pasarela."""

    class Estado(models.TextChoices):
        PENDIENTE = "pendiente", "Pendiente"
        APROBADO = "aprobado", "Aprobado"
        RECHAZADO = "rechazado", "Rechazado"
        ANULADO = "anulado", "Anulado"
        ERROR = "error", "Error"

    # Exactamente uno: el panel cobra facturas; el marketplace cobra pedidos.
    factura = models.ForeignKey("Factura", on_delete=models.PROTECT, related_name="pagos", null=True, blank=True)
    pedido = models.ForeignKey("Pedido", on_delete=models.PROTECT, related_name="pagos", null=True, blank=True)
    referencia = models.CharField(max_length=60, unique=True)
    monto_centavos = models.BigIntegerField()
    moneda = models.CharField(max_length=3, default="COP")
    estado = models.CharField(max_length=10, choices=Estado.choices, default=Estado.PENDIENTE)
    wompi_transaccion_id = models.CharField(max_length=60, blank=True)
    metodo_pago = models.CharField(max_length=30, blank=True)
    aprobado_en = models.DateTimeField(null=True, blank=True)
    # Última consulta a Wompi desde una página: evita consultar en cada recarga
    consultado_en = models.DateTimeField(null=True, blank=True)
    # Instantánea cifrada: permite conciliar incluso si el negocio cambia o borra sus llaves.
    credenciales_cifradas = models.TextField(blank=True)
    pasarela_propia = models.BooleanField(default=False)

    class Meta:
        ordering = ["-creado_en"]
        constraints = [
            models.CheckConstraint(condition=Q(monto_centavos__gt=0), name="ck_pago_monto_positivo"),
            models.UniqueConstraint(
                fields=["factura"],
                condition=Q(estado="aprobado"),
                name="uq_un_pago_aprobado_por_factura",
            ),
            models.UniqueConstraint(
                fields=["pedido"],
                condition=Q(estado="aprobado"),
                name="uq_un_pago_aprobado_por_pedido",
            ),
            models.CheckConstraint(
                condition=(Q(factura__isnull=False) & Q(pedido__isnull=True))
                | (Q(factura__isnull=True) & Q(pedido__isnull=False)),
                name="ck_pago_factura_o_pedido",
            ),
        ]

    def __str__(self):
        return f"{self.referencia} ({self.get_estado_display()})"

class ConfiguracionPagos(ModeloTenant):
    """Llaves de la pasarela propia de cada negocio. Los secretos se guardan cifrados
    y nunca se vuelven a mostrar: solo sus últimos 4 caracteres."""

    class Proveedor(models.TextChoices):
        WOMPI = "wompi", "Wompi"

    class Modo(models.TextChoices):
        PRUEBAS = "pruebas", "Pruebas (sandbox)"
        PRODUCCION = "produccion", "Producción"

    empresa = models.OneToOneField("Empresa", on_delete=models.PROTECT, related_name="pasarela")

    proveedor = models.CharField(max_length=20, choices=Proveedor.choices, default=Proveedor.WOMPI)
    modo = models.CharField(max_length=20, choices=Modo.choices)
    llave_publica = models.CharField(max_length=120)  # pública por diseño: va en el checkout
    llave_privada_cifrada = models.TextField(blank=True)
    secreto_integridad_cifrado = models.TextField()
    secreto_eventos_cifrado = models.TextField()
    llave_privada_final = models.CharField(max_length=4, blank=True)
    secreto_integridad_final = models.CharField(max_length=4)
    secreto_eventos_final = models.CharField(max_length=4)
    activa = models.BooleanField("Cobrar en línea con estas llaves", default=False)
    cobrar_tarifa_al_comprador = models.BooleanField(
        "Sumar la tarifa de la pasarela al precio", default=True,
        help_text="Si lo desactivas, tu negocio asume la tarifa de cada transacción.",
    )
    tarifa_porcentaje = models.DecimalField(
        "Tarifa de la pasarela (%)", max_digits=5, decimal_places=2, default=Decimal("2.65"),
        validators=[MinValueValidator(Decimal("0")), MaxValueValidator(Decimal("15"))],
    )
    tarifa_fija = models.DecimalField(
        "Tarifa fija por transacción ($)", max_digits=10, decimal_places=2, default=Decimal("700"),
        validators=[MinValueValidator(Decimal("0")), MaxValueValidator(Decimal("20000"))],
    )
    verificada_en = models.DateTimeField(null=True, blank=True)
    comercio_verificado = models.CharField(max_length=200, blank=True)
    ultimo_intento_verificacion = models.DateTimeField(null=True, blank=True)
    actualizada_por = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name="+",
    )
    revision = models.UUIDField(default=uuid.uuid4, editable=False)

    class Meta:
        verbose_name = "configuración de pagos"
        verbose_name_plural = "configuraciones de pagos"

    def __str__(self):
        return f"{self.get_proveedor_display()} · {self.get_modo_display()}"

    def __repr__(self):  # nunca imprimir secretos, ni cifrados
        return f"<ConfiguracionPagos empresa={self.empresa_id} modo={self.modo}>"

    @property
    def llave_privada(self) -> str:
        return descifrar(self.llave_privada_cifrada)

    @property
    def secreto_integridad(self) -> str:
        return descifrar(self.secreto_integridad_cifrado)

    @property
    def secreto_eventos(self) -> str:
        return descifrar(self.secreto_eventos_cifrado)

    @sensitive_variables()
    def poner_secreto(self, campo: str, valor: str) -> None:
        """campo: 'llave_privada', 'secreto_integridad' o 'secreto_eventos'."""
        if campo not in CAMPOS_SECRETOS:
            raise ValueError(f"Campo secreto desconocido: {campo}")
        setattr(self, CAMPOS_SECRETOS[campo], cifrar(valor))
        setattr(self, f"{campo}_final", valor[-4:] if valor else "")

    @property
    def lista_para_cobrar(self) -> bool:
        return self.activa and self.verificada_en is not None


CAMPOS_SECRETOS = {
    "llave_privada": "llave_privada_cifrada",
    "secreto_integridad": "secreto_integridad_cifrado",
    "secreto_eventos": "secreto_eventos_cifrado",
}


class AuditoriaPagos(ModeloTenant):
    """Solo metadatos del cambio; nunca valores de llaves ni cuerpos de peticiones."""
    usuario = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True)
    accion = models.CharField(max_length=30)
    campos = models.JSONField(default=list)

    class Meta:
        ordering = ["-creado_en"]
