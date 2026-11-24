"""Modelos de la consola interna de plataforma: roles internos, auditoría y llaves de cobro de Intersoft."""
from django.conf import settings
from django.db import OperationalError, ProgrammingError, models
from django.db.models import Q
from django.utils import timezone
from django.views.decorators.debug import sensitive_variables

from core.cifrado import cifrar, descifrar
from core.models.base import ModeloBase

PERMISOS_PLATAFORMA = (
    "inicio",
    "negocios",
    "finanzas",
    "llaves_wompi",
    "pqrs",
    "errores",
    "comentarios",
    "ideas",
    "operacion",
)

PERMISOS_POR_ROL = {
    "dueno": set(PERMISOS_PLATAFORMA),
    "finanzas": {"inicio", "finanzas"},
    "soporte": {"inicio", "negocios", "pqrs", "errores", "comentarios", "ideas"},
    "desarrollador": {"inicio", "errores", "ideas", "operacion"},
}


class RolPlataforma(ModeloBase):
    """Rol interno asignado a miembros del equipo dueño de Intersoft (is_staff)."""

    class Rol(models.TextChoices):
        DUENO = "dueno", "Dueño"
        FINANZAS = "finanzas", "Finanzas"
        SOPORTE = "soporte", "Soporte"
        DESARROLLADOR = "desarrollador", "Desarrollador"

    usuario = models.OneToOneField(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="rol_plataforma",
        verbose_name="usuario",
    )
    rol = models.CharField("rol interno", max_length=20, choices=Rol.choices)
    activo = models.BooleanField("activo", default=True)
    totp_secreto_cifrado = models.TextField(blank=True)
    totp_activo = models.BooleanField("2FA TOTP activado", default=False)

    @property
    def totp_secreto(self) -> str:
        return descifrar(self.totp_secreto_cifrado)

    def establecer_totp_secreto(self, secreto: str) -> None:
        self.totp_secreto_cifrado = cifrar(secreto) if secreto else ""

    class Meta:
        verbose_name = "rol de plataforma"
        verbose_name_plural = "roles de plataforma"
        ordering = ["usuario__email"]

    def __str__(self):
        return f"{self.usuario} · {self.get_rol_display()}"

    @property
    def permisos(self) -> set:
        """Secciones a las que entra este rol (para mostrar en el menú solo lo permitido)."""
        return set(PERMISOS_POR_ROL.get(self.rol, set())) if self.activo else set()

    def tiene_permiso(self, permiso: str) -> bool:
        if not self.activo:
            return False
        if not permiso:
            return True
        return permiso in PERMISOS_POR_ROL.get(self.rol, set())


class AuditoriaPlataforma(ModeloBase):
    """Bitácora de auditoría para todas las acciones de cambio ejecutadas en /plataforma/."""

    actor = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="+",
        verbose_name="actor",
    )
    accion = models.CharField("acción", max_length=80, db_index=True)
    objeto_tipo = models.CharField("tipo de objeto", max_length=60, blank=True)
    objeto_id = models.CharField("id de objeto", max_length=60, blank=True)
    detalle = models.JSONField("detalle (sin secretos)", default=dict, blank=True)
    ip = models.GenericIPAddressField("dirección IP", null=True, blank=True)
    fecha = models.DateTimeField("fecha", default=timezone.now, db_index=True)

    class Meta:
        verbose_name = "auditoría de plataforma"
        verbose_name_plural = "auditorías de plataforma"
        ordering = ["-fecha", "-creado_en"]

    def __str__(self):
        return f"{self.accion} · {self.actor or 'Sistema'} ({self.fecha:%d/%m/%Y %H:%M})"


CAMPOS_SECRETOS_PLATAFORMA = {
    "llave_privada": "llave_privada_cifrada",
    "secreto_integridad": "secreto_integridad_cifrado",
    "secreto_eventos": "secreto_eventos_cifrado",
}


class ConfiguracionCobroPlataforma(ModeloBase):
    """Configuración singleton con las llaves cifradas de Wompi de Intersoft para cobrar planes."""

    class Modo(models.TextChoices):
        PRUEBAS = "pruebas", "Pruebas (sandbox)"
        PRODUCCION = "produccion", "Producción"

    clave_unica = models.PositiveSmallIntegerField(default=1, unique=True, editable=False)
    modo = models.CharField("modo", max_length=20, choices=Modo.choices, default=Modo.PRUEBAS)
    llave_publica = models.CharField("llave pública", max_length=120, blank=True)
    llave_privada_cifrada = models.TextField(blank=True)
    secreto_integridad_cifrado = models.TextField(blank=True)
    secreto_eventos_cifrado = models.TextField(blank=True)
    llave_privada_final = models.CharField(max_length=4, blank=True)
    secreto_integridad_final = models.CharField(max_length=4, blank=True)
    secreto_eventos_final = models.CharField(max_length=4, blank=True)
    activa = models.BooleanField("usar estas llaves para cobrar planes", default=False)
    verificada_en = models.DateTimeField(null=True, blank=True)
    comercio_verificado = models.CharField(max_length=200, blank=True)
    ultimo_intento_verificacion = models.DateTimeField(null=True, blank=True)
    actualizada_por = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="+",
        verbose_name="actualizada por",
    )

    class Meta:
        verbose_name = "configuración de cobro de plataforma"
        verbose_name_plural = "configuraciones de cobro de plataforma"

    def __str__(self):
        return f"Wompi Intersoft · {self.get_modo_display()}"

    def __repr__(self):
        return f"<ConfiguracionCobroPlataforma modo={self.modo} activa={self.activa}>"

    @classmethod
    def obtener(cls):
        obj, _ = cls.objects.get_or_create(clave_unica=1)
        return obj

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
        """Cifra un secreto y guarda únicamente los últimos 4 caracteres visibles."""
        if campo not in CAMPOS_SECRETOS_PLATAFORMA:
            raise ValueError(f"Campo secreto desconocido: {campo}")
        limpio = (valor or "").strip()
        setattr(self, CAMPOS_SECRETOS_PLATAFORMA[campo], cifrar(limpio) if limpio else "")
        setattr(self, f"{campo}_final", limpio[-4:] if limpio else "")


class AnuncioGlobal(ModeloBase):
    """Anuncio global publicado desde /plataforma/ visible como aviso en el /panel/ de los negocios."""

    class Tipo(models.TextChoices):
        INFO = "info", "Información"
        ADVERTENCIA = "advertencia", "Advertencia"
        MANTENIMIENTO = "mantenimiento", "Mantenimiento"

    titulo = models.CharField("título", max_length=140)
    mensaje = models.TextField("mensaje")
    tipo = models.CharField("tipo", max_length=20, choices=Tipo.choices, default=Tipo.INFO)
    inicia_en = models.DateTimeField("vigente desde", default=timezone.now)
    vence_en = models.DateTimeField("vigente hasta", null=True, blank=True)
    activo = models.BooleanField("activo", default=True)
    creado_por = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="+",
        verbose_name="creado por",
    )

    class Meta:
        verbose_name = "anuncio global"
        verbose_name_plural = "anuncios globales"
        ordering = ["-inicia_en", "-creado_en"]

    def __str__(self):
        return f"{self.titulo} ({self.get_tipo_display()})"

    @classmethod
    def vigentes(cls, ahora=None) -> list:
        ahora = ahora or timezone.now()
        try:
            return list(
                cls.objects.filter(activo=True, inicia_en__lte=ahora)
                .filter(Q(vence_en__isnull=True) | Q(vence_en__gte=ahora))
                .order_by("-inicia_en")[:5]
            )
        except (OperationalError, ProgrammingError):
            return []


class FeatureFlag(ModeloBase):
    """Interruptor de funcionalidad por negocio (sobrescribe las features del plan)."""

    empresa = models.ForeignKey(
        "core.Empresa",
        on_delete=models.CASCADE,
        related_name="feature_flags",
        verbose_name="negocio",
    )
    codigo = models.CharField("código de función", max_length=60)
    habilitado = models.BooleanField("habilitado", default=True)

    class Meta:
        verbose_name = "interruptor de función"
        verbose_name_plural = "interruptores de función"
        ordering = ["empresa__nombre", "codigo"]
        constraints = [
            models.UniqueConstraint(fields=["empresa", "codigo"], name="uq_feature_flag_empresa_codigo"),
        ]

    def __str__(self):
        estado = "ON" if self.habilitado else "OFF"
        return f"{self.empresa} · {self.codigo} ({estado})"


