"""Documentos operativos del ERP. Los efectos se aplican mediante erp_services."""
from decimal import Decimal

from django.conf import settings
from django.core.exceptions import ValidationError
from django.core.validators import MinValueValidator
from django.db import models
from django.db.models import Q
from django.utils import timezone

from .base import ModeloTenant


def importe(**kwargs):
    return models.DecimalField(max_digits=14, decimal_places=2, default=Decimal("0"),
                               validators=[MinValueValidator(0)], **kwargs)


class RegistroERP(ModeloTenant):
    """Base de los documentos del ERP: pertenecen a una empresa y se ordenan del más reciente al más antiguo."""
    class Meta:
        abstract = True
        ordering = ["-creado_en"]

    def clean(self):
        super().clean()
        for campo in self._meta.fields:
            if campo.is_relation and campo.name != "empresa" and getattr(self, campo.attname):
                relacionado = getattr(self, campo.name)
                if hasattr(relacionado, "empresa_id") and relacionado.empresa_id != self.empresa_id:
                    raise ValidationError({campo.name: "El registro no pertenece a esta empresa."})


class Proveedor(RegistroERP):
    """Proveedor al que el negocio le compra mercancía."""
    nombre = models.CharField(max_length=150)
    documento = models.CharField(max_length=30)
    email = models.EmailField(blank=True)
    telefono = models.CharField(max_length=30, blank=True)
    direccion = models.CharField(max_length=250, blank=True)
    activo = models.BooleanField(default=True)

    class Meta(RegistroERP.Meta):
        ordering = ["nombre"]
        constraints = [models.UniqueConstraint(fields=["empresa", "documento"], name="uq_proveedor_documento")]

    def __str__(self):
        return self.nombre


class Compra(RegistroERP):
    """Compra a un proveedor; al recibirla entra la mercancía al kardex y se genera la cuenta por pagar."""
    proveedor = models.ForeignKey(Proveedor, on_delete=models.PROTECT)
    referencia = models.CharField("Factura del proveedor", max_length=60)
    bodega = models.ForeignKey(
        "Bodega",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="compras",
        verbose_name="bodega destino",
    )
    fecha = models.DateField(default=timezone.localdate)
    vencimiento = models.DateField()
    recibida = models.BooleanField(default=False, editable=False)
    subtotal = importe(editable=False)
    iva = importe(editable=False)
    total = importe(editable=False)
    observaciones = models.TextField(blank=True)

    class Meta(RegistroERP.Meta):
        constraints = [models.UniqueConstraint(fields=["empresa", "proveedor", "referencia"], name="uq_compra_referencia")]

    def __str__(self):
        return f"Compra {self.referencia} · {self.proveedor}"


class LineaCompra(RegistroERP):
    """Línea de una compra: producto, cantidad, costo e IVA."""
    compra = models.ForeignKey(Compra, on_delete=models.PROTECT, related_name="lineas")
    producto = models.ForeignKey("Producto", on_delete=models.PROTECT)
    cantidad = models.PositiveIntegerField(validators=[MinValueValidator(1)])
    costo = importe()
    iva_porcentaje = models.DecimalField(max_digits=5, decimal_places=2, default=0)

    class Meta(RegistroERP.Meta):
        constraints = [models.CheckConstraint(condition=Q(cantidad__gt=0) & Q(costo__gte=0) & Q(iva_porcentaje__gte=0) & Q(iva_porcentaje__lte=100), name="ck_linea_compra_valores")]


class CuentaTesoreria(RegistroERP):
    """Caja o cuenta bancaria del negocio donde entra y sale dinero (tesorería)."""
    nombre = models.CharField(max_length=100)
    tipo = models.CharField(max_length=10, choices=[("caja", "Caja"), ("banco", "Banco")])
    activa = models.BooleanField(default=True)

    class Meta(RegistroERP.Meta):
        ordering = ["nombre"]
        constraints = [models.UniqueConstraint(fields=["empresa", "nombre"], name="uq_tesoreria_nombre")]

    def __str__(self):
        return self.nombre


class CuentaCartera(RegistroERP):
    """Cuenta por cobrar o por pagar (cartera) con su total, abonos y vencimiento."""
    tipo = models.CharField(max_length=10, choices=[("cobrar", "Por cobrar"), ("pagar", "Por pagar")])
    tercero = models.CharField(max_length=150)
    concepto = models.CharField(max_length=200)
    fecha = models.DateField(default=timezone.localdate)
    vencimiento = models.DateField()
    total = importe()
    abonado = importe(editable=False)
    compra = models.OneToOneField(Compra, on_delete=models.PROTECT, null=True, blank=True)
    factura = models.OneToOneField("Factura", on_delete=models.PROTECT, null=True, blank=True)

    class Meta(RegistroERP.Meta):
        constraints = [models.CheckConstraint(condition=Q(total__gt=0) & Q(abonado__gte=0) & Q(abonado__lte=models.F("total")), name="ck_cartera_saldo")]

    @property
    def saldo(self):
        return self.total - self.abonado

    @property
    def estado(self):
        """Estado de la cuenta de cartera: Pagada, Vencida o Pendiente."""
        if not self.saldo:
            return "Pagada"
        return "Vencida" if self.vencimiento < timezone.localdate() else "Pendiente"

    def __str__(self):
        return f"{self.tercero} · {self.concepto}"


class MovimientoTesoreria(RegistroERP):
    """Ingreso o egreso de dinero en una cuenta de tesorería; idempotente por su clave de operación."""
    cuenta = models.ForeignKey(CuentaTesoreria, on_delete=models.PROTECT, related_name="movimientos")
    tipo = models.CharField(max_length=10, choices=[("ingreso", "Ingreso"), ("egreso", "Egreso")])
    fecha = models.DateField(default=timezone.localdate)
    concepto = models.CharField(max_length=200)
    monto = importe()
    cartera = models.ForeignKey(CuentaCartera, on_delete=models.PROTECT, null=True, blank=True, related_name="abonos")
    referencia = models.CharField(max_length=100, blank=True)
    conciliado = models.BooleanField(default=False)
    usuario = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT)
    operacion = models.UUIDField(unique=True, editable=False)

    class Meta(RegistroERP.Meta):
        constraints = [models.CheckConstraint(condition=Q(monto__gt=0), name="ck_tesoreria_monto")]


class CuentaContable(RegistroERP):
    """Cuenta del plan de cuentas contable (PUC) del negocio."""
    codigo = models.CharField(max_length=20)
    nombre = models.CharField(max_length=100)
    naturaleza = models.CharField(max_length=10, choices=[("debito", "Débito"), ("credito", "Crédito")])

    class Meta(RegistroERP.Meta):
        ordering = ["codigo"]
        constraints = [models.UniqueConstraint(fields=["empresa", "codigo"], name="uq_contable_codigo")]

    def __str__(self):
        return f"{self.codigo} · {self.nombre}"


class AsientoContable(RegistroERP):
    """Comprobante contable; al confirmarlo sus débitos y créditos deben cuadrar (partida doble)."""
    fecha = models.DateField(default=timezone.localdate)
    concepto = models.CharField(max_length=200)
    referencia = models.CharField(max_length=100, blank=True)
    confirmado = models.BooleanField(default=False, editable=False)
    usuario = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT)

    def __str__(self):
        return self.concepto


class LineaAsiento(RegistroERP):
    """Línea de un comprobante contable: cuenta y valor débito o crédito (solo uno de los dos)."""
    asiento = models.ForeignKey(AsientoContable, on_delete=models.PROTECT, related_name="lineas")
    cuenta = models.ForeignKey(CuentaContable, on_delete=models.PROTECT)
    debito = importe()
    credito = importe()

    class Meta(RegistroERP.Meta):
        constraints = [models.CheckConstraint(condition=(Q(debito__gt=0) & Q(credito=0)) | (Q(credito__gt=0) & Q(debito=0)), name="ck_asiento_un_lado")]

    def clean(self):
        super().clean()
        debito = self.debito or Decimal("0")
        credito = self.credito or Decimal("0")
        if (debito > 0 and credito > 0) or (debito <= 0 and credito <= 0):
            raise ValidationError("Cada línea debe tener un valor mayor que cero en débito o en crédito, pero no en ambos.")


class Empleado(RegistroERP):
    """Empleado o profesional del negocio (nómina y agenda de servicios)."""
    nombre = models.CharField(max_length=150)
    documento = models.CharField(max_length=30)
    cargo = models.CharField(max_length=100)
    salario_base = importe()
    fecha_ingreso = models.DateField(default=timezone.localdate)
    activo = models.BooleanField(default=True)

    class Meta(RegistroERP.Meta):
        ordering = ["nombre"]
        constraints = [models.UniqueConstraint(fields=["empresa", "documento"], name="uq_empleado_documento")]

    def __str__(self):
        return self.nombre


class LiquidacionNomina(RegistroERP):
    """Liquidación de nómina de un período: base, adicionales salariales, auxilio de transporte y deducciones."""
    empleado = models.ForeignKey(Empleado, on_delete=models.PROTECT)
    desde = models.DateField()
    hasta = models.DateField()
    base = importe()
    # Salariales: horas extra, recargos, comisiones, bonificaciones. Aportan a salud y pensión (IBC).
    adicionales = importe(verbose_name="adicionales salariales",
                          help_text="Horas extra, recargos, comisiones o bonificaciones. Aportan a salud y pensión.")
    # No salarial por ley: se paga, pero no hace parte de la base de aportes (QA-03).
    auxilio_transporte = importe(verbose_name="auxilio de transporte", blank=True,
                                 help_text="Opcional. Se paga al empleado pero no aporta a salud ni pensión.")
    deducciones = importe()
    neto = importe(editable=False)
    observaciones = models.TextField(blank=True)
    aprobada = models.BooleanField(default=False, editable=False)
    cartera = models.OneToOneField(CuentaCartera, on_delete=models.PROTECT, null=True, blank=True, editable=False)

    class Meta(RegistroERP.Meta):
        constraints = [models.CheckConstraint(condition=Q(hasta__gte=models.F("desde")) & Q(neto__gte=0), name="ck_nomina_periodo_neto")]

    def clean(self):
        super().clean()
        if self.desde and self.hasta and self.hasta < self.desde:
            raise ValidationError({"hasta": "La fecha final del período no puede ser anterior a la inicial."})
        base = self.base if self.base is not None else Decimal("0")
        adicionales = self.adicionales if self.adicionales is not None else Decimal("0")
        if self.auxilio_transporte is None:          # campo opcional: vacío equivale a cero
            self.auxilio_transporte = Decimal("0")
        auxilio = self.auxilio_transporte
        deducciones = self.deducciones if self.deducciones is not None else Decimal("0")
        self.neto = base + adicionales + auxilio - deducciones
        if self.neto <= 0:
            raise ValidationError(
                "El neto a pagar (base + adicionales + auxilio de transporte − deducciones) debe ser mayor que cero.")

    def __str__(self):
        return f"{self.empleado} · {self.desde} / {self.hasta}"


class OrdenProduccion(RegistroERP):
    """Orden de producción: consume insumos del kardex y produce un producto terminado."""
    producto = models.ForeignKey("Producto", on_delete=models.PROTECT)
    cantidad = models.PositiveIntegerField(validators=[MinValueValidator(1)])
    fecha = models.DateField(default=timezone.localdate)
    completada = models.BooleanField(default=False, editable=False)
    observaciones = models.TextField(blank=True)

    class Meta(RegistroERP.Meta):
        constraints = [models.CheckConstraint(condition=Q(cantidad__gt=0), name="ck_produccion_cantidad")]

    def __str__(self):
        return f"{self.producto} × {self.cantidad}"


class InsumoProduccion(RegistroERP):
    """Insumo (producto y cantidad) que consume una orden de producción."""
    orden = models.ForeignKey(OrdenProduccion, on_delete=models.PROTECT, related_name="insumos")
    producto = models.ForeignKey("Producto", on_delete=models.PROTECT)
    cantidad = models.PositiveIntegerField("Cantidad total a consumir", validators=[MinValueValidator(1)])

    class Meta(RegistroERP.Meta):
        constraints = [models.UniqueConstraint(fields=["orden", "producto"], name="uq_produccion_insumo"), models.CheckConstraint(condition=Q(cantidad__gt=0), name="ck_insumo_cantidad")]

    def clean(self):
        super().clean()
        if self.orden_id and self.producto_id and self.orden.producto_id == self.producto_id:
            raise ValidationError("El producto terminado no puede ser su propio insumo.")


class Servicio(RegistroERP):
    """Servicio que ofrece el negocio, con precio, IVA y duración (para la agenda)."""
    nombre = models.CharField(max_length=150)
    precio = importe()
    iva_porcentaje = models.DecimalField(max_digits=5, decimal_places=2, default=0)
    duracion_minutos = models.PositiveIntegerField(default=30, validators=[MinValueValidator(1)])
    activo = models.BooleanField(default=True)

    class Meta(RegistroERP.Meta):
        constraints = [models.CheckConstraint(condition=Q(precio__gte=0) & Q(duracion_minutos__gt=0) & Q(iva_porcentaje__gte=0) & Q(iva_porcentaje__lte=100), name="ck_servicio_valores")]

    def __str__(self):
        return self.nombre


class Cita(RegistroERP):
    """Cita de un cliente con un profesional; al atenderla se genera la cuenta por cobrar."""
    cliente = models.ForeignKey("Cliente", on_delete=models.PROTECT)
    empleado = models.ForeignKey(Empleado, on_delete=models.PROTECT)
    servicio = models.ForeignKey(Servicio, on_delete=models.PROTECT)
    inicio = models.DateTimeField()
    fin = models.DateTimeField(editable=False)
    estado = models.CharField(max_length=12, choices=[("pendiente", "Pendiente"), ("atendida", "Atendida"), ("cancelada", "Cancelada")], default="pendiente", editable=False)
    total = importe(editable=False)
    cartera = models.OneToOneField(CuentaCartera, on_delete=models.PROTECT, null=True, blank=True, editable=False)
    observaciones = models.TextField(blank=True)

    class Meta(RegistroERP.Meta):
        ordering = ["inicio"]
        constraints = [models.CheckConstraint(condition=Q(fin__gt=models.F("inicio")), name="ck_cita_horario")]

    def __str__(self):
        return f"{self.cliente} · {self.servicio}"
