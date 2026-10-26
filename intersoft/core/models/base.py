"""Bases abstractas: UUID, fechas de auditoría y pertenencia a una empresa (tenant)."""
import uuid
 
from django.db import models
 
 
class ModeloBase(models.Model):
    """UUID como clave primaria (no revela cuántos registros hay ni es adivinable)
    y fechas de creación/actualización automáticas."""
 
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    creado_en = models.DateTimeField(auto_now_add=True)
    actualizado_en = models.DateTimeField(auto_now=True)
 
    class Meta:
        abstract = True  # No crea tabla; solo se hereda.
 
 
class TenantQuerySet(models.QuerySet):
    """Consultas reutilizables para modelos que pertenecen a una empresa."""
 
    def de_empresa(self, empresa):
        return self.filter(empresa=empresa)
 
 
class ModeloTenant(ModeloBase):
    """Base de TODO modelo de negocio: obliga a que cada fila tenga empresa."""
 
    empresa = models.ForeignKey(
        "Empresa",
        on_delete=models.PROTECT,  # Nunca borrar en cascada los datos de un cliente.
        related_name="+",          # Sin relación inversa automática (evita choques de nombres).
        db_index=True,
    )
 
    objects = TenantQuerySet.as_manager()
 
    class Meta:
        abstract = True
 