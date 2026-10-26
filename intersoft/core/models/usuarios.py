"""Usuarios y control de acceso basado en roles (RBAC)."""
import uuid
from functools import cached_property
 
from django.conf import settings
from django.contrib.auth.models import AbstractUser
from django.core.exceptions import ValidationError
from django.db import models
 
from .base import ModeloBase, ModeloTenant
 
 
class Usuario(AbstractUser):
    """Usuario personalizado: inicia sesión con correo.
    IMPORTANTE: debe existir ANTES de la primera migración del proyecto."""
 
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    email = models.EmailField("correo electrónico", unique=True)
 
    USERNAME_FIELD = "email"
    REQUIRED_FIELDS = ["username"]  # Lo pide createsuperuser además de email y contraseña.
 
    class Meta:
        verbose_name = "usuario"
        verbose_name_plural = "usuarios"
 
    def __str__(self):
        return self.get_full_name() or self.email
 
 
class Permiso(ModeloBase):
    """Catálogo global de permisos. Convención: "<modulo>.<accion>", ej. "ventas.crear"."""
 
    codigo = models.CharField(max_length=60, unique=True)
    descripcion = models.CharField(max_length=200)
 
    class Meta:
        verbose_name = "permiso"
        verbose_name_plural = "permisos"
        ordering = ["codigo"]
 
    def __str__(self):
        return self.codigo
 
 
class Rol(ModeloTenant):
    """Cada empresa define sus propios roles a partir del catálogo de permisos."""
 
    nombre = models.CharField(max_length=60)
    descripcion = models.CharField(max_length=200, blank=True)
    es_admin = models.BooleanField(default=False)  # Acceso total dentro de su empresa.
    permisos = models.ManyToManyField(Permiso, blank=True, related_name="roles")
 
    class Meta:
        verbose_name = "rol"
        verbose_name_plural = "roles"
        ordering = ["nombre"]
        constraints = [
            models.UniqueConstraint(fields=["empresa", "nombre"], name="uq_rol_nombre_por_empresa"),
        ]
 
    def __str__(self):
        return self.nombre
 
 
class Membresia(ModeloBase):
    """Relación usuario-empresa con un rol. Un usuario puede estar en varias empresas
    con un rol distinto en cada una."""
 
    usuario = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="membresias"
    )
    empresa = models.ForeignKey("Empresa", on_delete=models.CASCADE, related_name="membresias")
    rol = models.ForeignKey(Rol, on_delete=models.PROTECT, related_name="membresias")
    activa = models.BooleanField(default=True)
 
    class Meta:
        verbose_name = "membresía"
        verbose_name_plural = "membresías"
        constraints = [
            models.UniqueConstraint(fields=["usuario", "empresa"], name="uq_membresia_usuario_empresa"),
        ]
 
    def __str__(self):
        return f"{self.usuario} · {self.empresa} ({self.rol})"
 
    def clean(self):
        # Regla de integridad: el rol debe pertenecer a la misma empresa de la membresía.
        if self.rol_id and self.empresa_id and self.rol.empresa_id != self.empresa_id:
            raise ValidationError({"rol": "El rol no pertenece a esta empresa."})
 
    @cached_property
    def codigos_permiso(self):
        # Una sola consulta por petición; después se resuelve en memoria.
        return set(self.rol.permisos.values_list("codigo", flat=True))
 
    def tiene_permiso(self, codigo):
        return self.rol.es_admin or codigo in self.codigos_permiso
 