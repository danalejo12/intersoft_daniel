"""Registro de las tareas periódicas: cuándo corrió cada una y cómo terminó."""
from django.utils.translation import gettext_lazy
from django.db import models

from .base import ModeloBase


class EjecucionTarea(ModeloBase):
    """Una fila por tarea. Sirve para no repetirla antes de tiempo (aunque se reinicie el
    programador) y para que dos programadores a la vez no ejecuten la misma tarea."""

    nombre = models.CharField(max_length=60, unique=True)
    ultima_ejecucion = models.DateTimeField(null=True, blank=True)
    ultimo_resultado = models.CharField(max_length=500, blank=True)
    ultimo_error = models.CharField(max_length=500, blank=True)
    ejecuciones = models.PositiveIntegerField(default=0)
    fallos_seguidos = models.PositiveIntegerField(default=0)

    class Meta:
        verbose_name = gettext_lazy("ejecución de tarea periódica")
        verbose_name_plural = gettext_lazy("ejecuciones de tareas periódicas")
        ordering = ["nombre"]

    def __str__(self):
        return self.nombre
