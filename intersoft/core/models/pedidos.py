"""Compras del marketplace: pedidos con datos de envío y opiniones de productos."""
import unicodedata
from datetime import timedelta
from decimal import Decimal
from urllib.parse import quote

from django.conf import settings
from django.core.validators import MaxValueValidator, MinValueValidator
from django.db import models
from django.db.models import Q
from django.utils import timezone

from .base import ModeloBase, ModeloTenant
from .ventas import Factura

# Enlaces oficiales de rastreo para transportadoras frecuentes en Colombia y envíos internacionales.
TRANSPORTADORAS_RASTREO = {
    "servientrega": "https://www.servientrega.com/wps/portal/rastreo-envio?guia={guia}",
    "coordinadora": "https://coordinadora.com/rastreo/rastreo-de-guia/detalle-de-rastreo-de-guia/?guia={guia}",
    "interrapidisimo": "https://www.interrapidisimo.com/sigue-tu-envio/?guia={guia}",
    "inter rapidisimo": "https://www.interrapidisimo.com/sigue-tu-envio/?guia={guia}",
    "envia": "https://envia.co/rastreo/?guia={guia}",
    "tcc": "https://tcc.com.co/logistica/servicios-on-line/rastrear-envios/?remesa={guia}",
    "deprisa": "https://www.deprisa.com/Tracking/?track={guia}",
    "4-72": "https://www.4-72.com.co/Publicaciones/informacion_de_interes/rastreo_de_envios?guia={guia}",
    "472": "https://www.4-72.com.co/Publicaciones/informacion_de_interes/rastreo_de_envios?guia={guia}",
    "fedex": "https://www.fedex.com/fedextrack/?trknbr={guia}",
    "dhl": "https://www.dhl.com/co-es/home/rastreo.html?tracking-id={guia}",
}


def _normalizar_transportadora(nombre: str) -> str:
    """Minúsculas sin tildes ni espacios repetidos para empatar nombres de transportadora."""
    sin_tildes = unicodedata.normalize("NFKD", (nombre or "").strip().lower())
    limpio = "".join(c for c in sin_tildes if not unicodedata.combining(c))
    return " ".join(limpio.split())


class Orden(ModeloBase):
    """Una compra del marketplace que reúne los pedidos de varios negocios.

    Cada negocio cobra con su propia cuenta de Wompi y Wompi no reparte un pago entre cuentas,
    así que la orden NO tiene pago propio: cada pedido se paga y se concilia por separado.
    No es de una empresa (cruza negocios a propósito); solo la ve su comprador."""

    comprador = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="ordenes")

    class Meta:
        verbose_name = "orden de compra del marketplace"
        verbose_name_plural = "órdenes de compra del marketplace"
        ordering = ["-creado_en"]

    def __str__(self):
        return f"Orden {str(self.pk)[:8]}"


class CuponTienda(ModeloTenant):
    """Cupón de descuento propio de un negocio para compras en el marketplace."""

    class Tipo(models.TextChoices):
        """Tipos de descuento admitidos para un cupón de tienda: porcentaje o valor fijo."""
        PORCENTAJE = "porcentaje", "Porcentaje (%)"
        FIJO = "fijo", "Valor fijo ($)"

    codigo = models.CharField("código", max_length=40)
    tipo = models.CharField("tipo de descuento", max_length=15, choices=Tipo.choices, default=Tipo.PORCENTAJE)
    valor = models.DecimalField(
        "valor",
        max_digits=12,
        decimal_places=2,
        validators=[MinValueValidator(Decimal("0.01"))],
    )
    monto_minimo = models.DecimalField(
        "compra mínima",
        max_digits=12,
        decimal_places=2,
        default=Decimal("0.00"),
        validators=[MinValueValidator(Decimal("0.00"))],
    )
    usos_maximos = models.PositiveIntegerField("usos máximos", null=True, blank=True)
    usos_actuales = models.PositiveIntegerField("usos actuales", default=0)
    inicia_en = models.DateTimeField("inicia en", default=timezone.now)
    vence_en = models.DateTimeField("vence en", null=True, blank=True)
    activo = models.BooleanField("activo", default=True)

    class Meta:
        verbose_name = "cupón de tienda"
        verbose_name_plural = "cupones de tienda"
        ordering = ["-creado_en"]
        constraints = [
            models.UniqueConstraint(fields=["empresa", "codigo"], name="uq_cupon_tienda_codigo_por_empresa"),
            models.CheckConstraint(condition=Q(valor__gt=0), name="ck_cupon_tienda_valor_positivo"),
            models.CheckConstraint(condition=Q(monto_minimo__gte=0), name="ck_cupon_tienda_monto_minimo"),
        ]

    def save(self, *args, **kwargs):
        self.codigo = (self.codigo or "").strip().upper()
        super().save(*args, **kwargs)

    def __str__(self):
        sufijo = f"{self.valor}%" if self.tipo == self.Tipo.PORCENTAJE else f"${self.valor}"
        return f"{self.codigo} ({sufijo})"

    @property
    def esta_vigente(self) -> bool:
        """Indica si el cupón está activo, dentro de fechas de vigencia y con usos disponibles."""
        ahora = timezone.now()
        if not self.activo:
            return False
        if self.inicia_en and ahora < self.inicia_en:
            return False
        if self.vence_en and ahora > self.vence_en:
            return False
        if self.usos_maximos is not None and self.usos_actuales >= self.usos_maximos:
            return False
        return True

    def validar_para(self, total_productos: Decimal, ahora=None) -> None:
        """Valida si el cupón puede aplicarse a una compra; lanza ValueError con motivo claro."""
        ahora = ahora or timezone.now()
        if not self.activo:
            raise ValueError("Este cupón no está activo.")
        if self.inicia_en and ahora < self.inicia_en:
            raise ValueError("Este cupón aún no está vigente.")
        if self.vence_en and ahora > self.vence_en:
            raise ValueError("Este cupón ya venció.")
        if self.usos_maximos is not None and self.usos_actuales >= self.usos_maximos:
            raise ValueError("Este cupón alcanzó el límite máximo de usos.")
        if self.monto_minimo and total_productos < self.monto_minimo:
            minimo_txt = f"$ {self.monto_minimo:,.0f}".replace(",", ".")
            raise ValueError(f"Este cupón requiere una compra mínima de {minimo_txt} en productos.")

    def calcular_descuento(self, total_productos: Decimal) -> Decimal:
        """Calcula el descuento en COP redondeado a centavos, nunca mayor al total de productos."""
        from core.impuestos import CENTAVOS

        if total_productos <= 0:
            return Decimal("0.00")
        if self.tipo == self.Tipo.PORCENTAJE:
            porcentaje = min(self.valor, Decimal("100"))
            bruto = (total_productos * porcentaje / Decimal("100")).quantize(CENTAVOS)
        else:
            bruto = self.valor.quantize(CENTAVOS)
        return min(bruto, total_productos).quantize(CENTAVOS)


class Pedido(ModeloTenant):
    """Lo que compró una persona en un negocio. Guarda sus líneas y su total: la factura nace al pagar."""

    class Estado(models.TextChoices):
        """Valores posibles de estado de pedido: «Pendiente de pago», «Pagado», «Vencido», «Cancelado», «Requiere
        reembolso», «Reembolsado».
        """
        PENDIENTE = "pendiente", "Pendiente de pago"
        PAGADO = "pagado", "Pagado"
        VENCIDO = "vencido", "Vencido"
        CANCELADO = "cancelado", "Cancelado"
        REQUIERE_REEMBOLSO = "requiere_reembolso", "Requiere reembolso"
        REEMBOLSADO = "reembolsado", "Reembolsado"

    class EstadoEnvio(models.TextChoices):
        """Valores posibles de estadoenvio de pedido: «Pendiente», «Preparando», «Enviado», «Entregado»."""
        PENDIENTE = "pendiente", "Pendiente"
        PREPARANDO = "preparando", "Preparando"
        ENVIADO = "enviado", "Enviado"
        ENTREGADO = "entregado", "Entregado"

    class EstadoDispersion(models.TextChoices):
        """Valores posibles de estadodispersion de pedido: «Pendiente de dispersión», «Programada», «Liquidada al
        comercio».
        """
        PENDIENTE = "pendiente", "Pendiente de dispersión"
        PROGRAMADA = "programada", "Programada"
        LIQUIDADA = "liquidada", "Liquidada al comercio"

    # Mientras el pedido está pendiente, el comprador ve el estado de su último intento.
    # Los demás estados usan la etiqueta de Estado: una sola fuente para cada texto.
    ETIQUETAS_DEL_INTENTO = {
        "por_pagar": "Por pagar",
        "procesando": "Confirmando pago",
        "rechazado": "Pago no aprobado",
    }

    comprador = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="pedidos")
    orden = models.ForeignKey(Orden, on_delete=models.PROTECT, related_name="pedidos", null=True, blank=True)
    # Bodega de la que se reservó el stock: al liberar o reembolsar, vuelve ahí
    bodega = models.ForeignKey("Bodega", on_delete=models.PROTECT, related_name="pedidos", null=True, blank=True)
    factura =models.OneToOneField(Factura, on_delete=models.PROTECT, related_name="pedido", null=True, blank=True)
    numero = models.PositiveIntegerField()  # Consecutivo por empresa, independiente del de facturas.
    estado = models.CharField(max_length=20, choices=Estado.choices, default=Estado.PENDIENTE)
    expira_en = models.DateTimeField()
    renovaciones = models.PositiveSmallIntegerField(default=0)
    pago_directo = models.BooleanField(default=False)  # False conserva el historial del antiguo recaudador.
    subtotal = models.DecimalField(max_digits=14, decimal_places=2, default=Decimal("0"))
    iva = models.DecimalField(max_digits=14, decimal_places=2, default=Decimal("0"))
    cupon = models.ForeignKey(
        CuponTienda,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="pedidos",
    )
    cupon_codigo = models.CharField(max_length=40, blank=True)
    descuento = models.DecimalField(max_digits=14, decimal_places=2, default=Decimal("0"))
    costo_envio = models.DecimalField(max_digits=14, decimal_places=2, default=Decimal("0"))
    # Comisión de Wompi que paga el comprador; Wompi la descuenta y no llega al negocio.
    cargo_pasarela = models.DecimalField(max_digits=14, decimal_places=2, default=Decimal("0"))
    total = models.DecimalField(max_digits=14, decimal_places=2, default=Decimal("0"))
    peso_total_gramos = models.PositiveIntegerField(default=0)
    comision_porcentaje = models.DecimalField(max_digits=5, decimal_places=2, default=Decimal("0"))
    comision_valor = models.DecimalField(max_digits=14, decimal_places=2, default=Decimal("0"))
    neto_vendedor = models.DecimalField(max_digits=14, decimal_places=2, default=Decimal("0"))
    estado_dispersion = models.CharField(
        max_length=15, choices=EstadoDispersion.choices, default=EstadoDispersion.PENDIENTE
    )
    dispersion_referencia = models.CharField(max_length=80, blank=True)
    dispersado_en = models.DateTimeField(null=True, blank=True)
    estado_envio = models.CharField(
        max_length=20, choices=EstadoEnvio.choices, default=EstadoEnvio.PENDIENTE
    )
    transportadora = models.CharField(max_length=80, blank=True)
    numero_guia = models.CharField(max_length=80, blank=True)
    url_rastreo = models.URLField(max_length=300, blank=True)
    enviado_en = models.DateTimeField(null=True, blank=True)
    entregado_en = models.DateTimeField(null=True, blank=True)
    reembolsado_en = models.DateTimeField(null=True, blank=True)
    reembolso_referencia = models.CharField(max_length=80, blank=True)
    reembolso_nota = models.CharField(max_length=250, blank=True)
    reembolsado_por = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="reembolsos_registrados",
        null=True,
        blank=True,
    )
    tipo_documento = models.CharField(max_length=5)
    numero_documento = models.CharField(max_length=20)
    nombre = models.CharField(max_length=150)
    email = models.EmailField()
    telefono = models.CharField(max_length=20)
    departamento = models.CharField(max_length=60)
    ciudad = models.CharField(max_length=80)
    direccion = models.CharField(max_length=200)
    indicaciones = models.CharField(max_length=200, blank=True)

    class Meta:
        verbose_name = "pedido"
        verbose_name_plural = "pedidos"
        ordering = ["-creado_en"]
        constraints = [
            models.UniqueConstraint(fields=["empresa", "numero"], name="uq_pedido_numero_por_empresa"),
            models.CheckConstraint(condition=Q(total__gte=0), name="ck_pedido_total_no_negativo"),
        ]
        indexes = [
            models.Index(fields=["comprador", "-creado_en"], name="ix_pedido_comprador_fecha"),
            models.Index(fields=["estado", "expira_en"], name="ix_pedido_estado_expira"),
        ]

    def __str__(self):
        return f"Pedido {self.numero} de {self.nombre}"

    @property
    def estado_compra(self):
        """Estado que ve el comprador: mientras está pendiente, depende de su último intento."""
        if self.estado != self.Estado.PENDIENTE:
            return self.estado
        estados = list(self.pagos.values_list("estado", flat=True))  # del más reciente al más viejo
        if not estados:
            return "por_pagar"
        return "procesando" if estados[0] == "pendiente" else "rechazado"

    @property
    def necesita_renovar(self):
        """Indica si a la reserva le queda menos del mínimo de minutos para pagar y conviene renovarla."""
        minimo = timedelta(minutes=settings.PEDIDO_MINUTOS_MINIMOS_PAGO)
        return self.estado == self.Estado.PENDIENTE and self.expira_en - timezone.now() < minimo

    @property
    def puede_renovar(self):
        return (
            self.pago_directo and self.estado in (self.Estado.PENDIENTE, self.Estado.VENCIDO)
            and self.renovaciones < settings.PEDIDO_MAX_RENOVACIONES
        )

    @property
    def primer_nombre(self):
        return self.nombre.split()[0]

    @property
    def estado_etiqueta(self):
        """Texto del estado que ve el comprador (incluye el del último intento de pago)."""
        estado = self.estado_compra
        return self.ETIQUETAS_DEL_INTENTO.get(estado) or self.Estado(estado).label

    @property
    def enlace_rastreo(self) -> str:
        """Enlace seguro (http/https) para rastrear el envío: personalizado o automático por transportadora."""
        personalizado = (self.url_rastreo or "").strip()
        if personalizado.startswith(("http://", "https://")):
            return personalizado
        guia = (self.numero_guia or "").strip()
        if not guia or not self.transportadora:
            return ""
        clave = _normalizar_transportadora(self.transportadora)
        plantilla = TRANSPORTADORAS_RASTREO.get(clave)
        if not plantilla:
            for nombre, url in TRANSPORTADORAS_RASTREO.items():
                if nombre in clave:
                    plantilla = url
                    break
        return plantilla.format(guia=quote(guia, safe="")) if plantilla else ""

    @property
    def enlace_whatsapp_envio(self) -> str:
        """Enlace wa.me prellenado para avisar al comprador por WhatsApp el estado y guía de su pedido."""
        from core.notificaciones import telefono_whatsapp

        destino = telefono_whatsapp(self.telefono)
        if not destino:
            return ""
        partes = [
            f"Hola {self.primer_nombre}, te escribimos de {self.empresa.nombre}.",
            f"Tu pedido #{self.numero} está en estado: {self.get_estado_envio_display()}.",
        ]
        if self.transportadora:
            partes.append(f"Transportadora: {self.transportadora}.")
        if self.numero_guia:
            partes.append(f"Número de guía: {self.numero_guia}.")
        if self.enlace_rastreo:
            partes.append(f"Rastrea tu envío aquí: {self.enlace_rastreo}")
        return f"https://wa.me/{destino}?text={quote(' '.join(partes))}"


class DetallePedido(ModeloTenant):
    """Línea de un pedido del marketplace con el precio y el IVA congelados al confirmar."""
    pedido = models.ForeignKey(Pedido, on_delete=models.CASCADE, related_name="lineas")
    producto = models.ForeignKey("Producto", on_delete=models.PROTECT, related_name="lineas_pedido")
    cantidad = models.PositiveIntegerField(validators=[MinValueValidator(1)])
    # Se CONGELAN al confirmar: si mañana cambia el precio, este pedido no cambia.
    precio_unitario = models.DecimalField(max_digits=12, decimal_places=2)
    iva_porcentaje = models.DecimalField(max_digits=5, decimal_places=2)

    class Meta:
        verbose_name = "línea de pedido"
        verbose_name_plural = "líneas de pedido"
        constraints = [
            models.CheckConstraint(condition=Q(cantidad__gt=0), name="ck_linea_pedido_cantidad_positiva"),
        ]

    def __str__(self):
        return f"{self.cantidad} × {self.producto}"


class Comentario(ModeloTenant):
    """Opinión de un comprador sobre un producto (una por persona; marca de compra verificada)."""
    producto = models.ForeignKey("Producto", on_delete=models.CASCADE, related_name="comentarios")
    autor = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="comentarios")
    calificacion = models.PositiveSmallIntegerField(validators=[MinValueValidator(1), MaxValueValidator(5)])
    texto = models.TextField(max_length=1000)
    compra_verificada = models.BooleanField(default=False)  # La calcula el servidor, nunca el navegador.

    class Meta:
        verbose_name = "comentario"
        verbose_name_plural = "comentarios"
        ordering = ["-creado_en"]
        constraints = [
            models.UniqueConstraint(fields=["producto", "autor"], name="uq_comentario_por_autor"),
            models.CheckConstraint(condition=Q(calificacion__gte=1) & Q(calificacion__lte=5), name="ck_comentario_calificacion"),
        ]

    def __str__(self):
        return f"{self.producto} · {self.calificacion}/5"

    @property
    def nombre_publico(self):
        """Nombre e inicial del apellido: el correo de una persona nunca se publica."""
        nombre = self.autor.first_name.strip()
        apellido = self.autor.last_name.strip()
        if not nombre:
            return "Cliente de Intersoft"
        return f"{nombre} {apellido[0]}." if apellido else nombre


class Favorito(ModeloBase):
    """Producto guardado en favoritos por un comprador del marketplace."""

    usuario = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="favoritos"
    )
    producto = models.ForeignKey(
        "Producto", on_delete=models.CASCADE, related_name="favoritos"
    )

    class Meta:
        verbose_name = "favorito"
        verbose_name_plural = "favoritos"
        ordering = ["-creado_en"]
        constraints = [
            models.UniqueConstraint(fields=["usuario", "producto"], name="uq_favorito_usuario_producto"),
        ]

    def __str__(self):
        return f"{self.usuario} ♥ {self.producto}"


class ItemCarrito(ModeloBase):
    """Línea persistente del carrito para usuarios autenticados (sincronizada entre dispositivos)."""

    usuario = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="items_carrito"
    )
    producto = models.ForeignKey(
        "Producto", on_delete=models.CASCADE, related_name="items_carrito"
    )
    cantidad = models.PositiveIntegerField(validators=[MinValueValidator(1)])

    class Meta:
        verbose_name = "ítem de carrito"
        verbose_name_plural = "ítems de carrito"
        ordering = ["-actualizado_en"]
        constraints = [
            models.UniqueConstraint(fields=["usuario", "producto"], name="uq_item_carrito_usuario_producto"),
            models.CheckConstraint(condition=Q(cantidad__gt=0), name="ck_item_carrito_cantidad_positiva"),
        ]

    def __str__(self):
        return f"{self.usuario} · {self.cantidad} × {self.producto}"


class AvisoStock(ModeloBase):
    """Suscripción de un comprador para recibir aviso por correo cuando un producto vuelva a tener stock."""

    producto = models.ForeignKey(
        "Producto", on_delete=models.CASCADE, related_name="avisos_stock"
    )
    email = models.EmailField()
    usuario = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="avisos_stock",
    )
    notificado = models.BooleanField(default=False)
    notificado_en = models.DateTimeField(null=True, blank=True)

    class Meta:
        verbose_name = "aviso de stock"
        verbose_name_plural = "avisos de stock"
        ordering = ["-creado_en"]
        constraints = [
            models.UniqueConstraint(
                fields=["producto", "email"],
                condition=Q(notificado=False),
                name="uq_aviso_stock_pendiente_producto_email",
            ),
        ]

    def __str__(self):
        return f"Aviso stock {self.producto} → {self.email}"

