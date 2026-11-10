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
    proveedor = models.ForeignKey(Proveedor, on_delete=models.PROTECT)
    referencia = models.CharField("Factura del proveedor", max_length=60)
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
    compra = models.ForeignKey(Compra, on_delete=models.PROTECT, related_name="lineas")
    producto = models.ForeignKey("Producto", on_delete=models.PROTECT)
    cantidad = models.PositiveIntegerField(validators=[MinValueValidator(1)])
    costo = importe()
    iva_porcentaje = models.DecimalField(max_digits=5, decimal_places=2, default=0)

    class Meta(RegistroERP.Meta):
        constraints = [models.CheckConstraint(condition=Q(cantidad__gt=0) & Q(costo__gte=0) & Q(iva_porcentaje__gte=0) & Q(iva_porcentaje__lte=100), name="ck_linea_compra_valores")]


class CuentaTesoreria(RegistroERP):
    nombre = models.CharField(max_length=100)
    tipo = models.CharField(max_length=10, choices=[("caja", "Caja"), ("banco", "Banco")])
    activa = models.BooleanField(default=True)

    class Meta(RegistroERP.Meta):
        ordering = ["nombre"]
        constraints = [models.UniqueConstraint(fields=["empresa", "nombre"], name="uq_tesoreria_nombre")]

    def __str__(self):
        return self.nombre


class CuentaCartera(RegistroERP):
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
        if not self.saldo:
            return "Pagada"
        return "Vencida" if self.vencimiento < timezone.localdate() else "Pendiente"

    def __str__(self):
        return f"{self.tercero} · {self.concepto}"


class MovimientoTesoreria(RegistroERP):
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
    codigo = models.CharField(max_length=20)
    nombre = models.CharField(max_length=100)
    naturaleza = models.CharField(max_length=10, choices=[("debito", "Débito"), ("credito", "Crédito")])

    class Meta(RegistroERP.Meta):
        ordering = ["codigo"]
        constraints = [models.UniqueConstraint(fields=["empresa", "codigo"], name="uq_contable_codigo")]

    def __str__(self):
        return f"{self.codigo} · {self.nombre}"


class AsientoContable(RegistroERP):
    fecha = models.DateField(default=timezone.localdate)
    concepto = models.CharField(max_length=200)
    referencia = models.CharField(max_length=100, blank=True)
    confirmado = models.BooleanField(default=False, editable=False)
    usuario = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT)

    def __str__(self):
        return self.concepto


class LineaAsiento(RegistroERP):
    asiento = models.ForeignKey(AsientoContable, on_delete=models.PROTECT, related_name="lineas")
    cuenta = models.ForeignKey(CuentaContable, on_delete=models.PROTECT)
    debito = importe()
    credito = importe()

    class Meta(RegistroERP.Meta):
        constraints = [models.CheckConstraint(condition=(Q(debito__gt=0) & Q(credito=0)) | (Q(credito__gt=0) & Q(debito=0)), name="ck_asiento_un_lado")]


class Empleado(RegistroERP):
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
    empleado = models.ForeignKey(Empleado, on_delete=models.PROTECT)
    desde = models.DateField()
    hasta = models.DateField()
    base = importe()
    adicionales = importe()
    deducciones = importe()
    neto = importe(editable=False)
    observaciones = models.TextField(blank=True)
    aprobada = models.BooleanField(default=False, editable=False)
    cartera = models.OneToOneField(CuentaCartera, on_delete=models.PROTECT, null=True, blank=True, editable=False)

    class Meta(RegistroERP.Meta):
        constraints = [models.CheckConstraint(condition=Q(hasta__gte=models.F("desde")) & Q(neto__gte=0), name="ck_nomina_periodo_neto")]

    def __str__(self):
        return f"{self.empleado} · {self.desde} / {self.hasta}"


class OrdenProduccion(RegistroERP):
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
    orden = models.ForeignKey(OrdenProduccion, on_delete=models.PROTECT, related_name="insumos")
    producto = models.ForeignKey("Producto", on_delete=models.PROTECT)
    cantidad = models.PositiveIntegerField("Cantidad total a consumir", validators=[MinValueValidator(1)])

    class Meta(RegistroERP.Meta):
        constraints = [models.UniqueConstraint(fields=["orden", "producto"], name="uq_produccion_insumo"), models.CheckConstraint(condition=Q(cantidad__gt=0), name="ck_insumo_cantidad")]


class Servicio(RegistroERP):
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
