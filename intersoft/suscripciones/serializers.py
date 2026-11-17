"""Serializers de Django REST Framework para planes y suscripciones."""
import math

from django.utils import timezone
from rest_framework import serializers

from .models import Plan, Suscripcion
from .services import uso_actual


class PlanSerializer(serializers.ModelSerializer):
    """Representación pública de un plan comercial."""

    class Meta:
        model = Plan
        fields = [
            "id",
            "codigo",
            "nombre",
            "precio_mensual",
            "precio_anual",
            "comision_porcentaje",
            "limites",
            "features",
            "orden",
        ]
        read_only_fields = fields


class SuscripcionDetalleSerializer(serializers.ModelSerializer):
    """Representación de la suscripción de la empresa con días restantes y uso frente a límites."""

    plan = PlanSerializer(read_only=True)
    empresa_id = serializers.UUIDField(source="empresa.id", read_only=True)
    empresa_nombre = serializers.CharField(source="empresa.nombre", read_only=True)
    dias_restantes = serializers.SerializerMethodField()
    uso_actual = serializers.SerializerMethodField()
    limites = serializers.SerializerMethodField()

    class Meta:
        model = Suscripcion
        fields = [
            "id",
            "empresa_id",
            "empresa_nombre",
            "plan",
            "estado",
            "ciclo",
            "inicia_en",
            "vence_en",
            "dias_restantes",
            "es_fundador",
            "descuento_porcentaje",
            "uso_actual",
            "limites",
            "creado_en",
            "actualizado_en",
        ]
        read_only_fields = fields

    def get_dias_restantes(self, obj: Suscripcion) -> int | None:
        """Calcula los días restantes hasta `vence_en`, o None si el plan no tiene vencimiento."""
        if obj.vence_en is None:
            return None
        segundos = (obj.vence_en - timezone.now()).total_seconds()
        if segundos <= 0:
            return 0
        return math.ceil(segundos / 86400)

    def get_uso_actual(self, obj: Suscripcion) -> dict:
        return uso_actual(obj.empresa)

    def get_limites(self, obj: Suscripcion) -> dict:
        return obj.plan.limites or {}


class CambiarPlanSerializer(serializers.Serializer):
    """Payload de entrada para solicitar un cambio de plan y ciclo."""

    plan = serializers.SlugField(
        max_length=40,
        help_text="Código del plan destino (ej. gratis, emprendedor, negocio, pro).",
    )
    ciclo = serializers.ChoiceField(
        choices=Suscripcion.Ciclo.choices,
        default=Suscripcion.Ciclo.MENSUAL,
        required=False,
    )
    motivo = serializers.CharField(
        max_length=255,
        required=False,
        allow_blank=True,
        default="",
    )
