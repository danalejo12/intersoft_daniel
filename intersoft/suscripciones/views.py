"""Vistas API (DRF) para consulta de planes y gestión de la suscripción del tenant activo."""
from django.core.exceptions import ValidationError as DjangoValidationError
from rest_framework import generics, status
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from .models import Plan, Suscripcion
from .permissions import TieneEmpresaActiva, obtener_empresa_de_request
from .serializers import (
    CambiarPlanSerializer,
    PlanSerializer,
    SuscripcionDetalleSerializer,
)
from .services import (
    DowngradeNoPermitido,
    cambiar_plan,
    crear_suscripcion_inicial,
)


class PlanListAPIView(generics.ListAPIView):
    """GET /api/planes/ — Endpoint público con los planes activos ordenados."""

    permission_classes = [AllowAny]
    authentication_classes = []
    serializer_class = PlanSerializer

    def get_queryset(self):
        return Plan.objects.filter(activo=True).order_by("orden", "precio_mensual")


class SuscripcionDetalleAPIView(APIView):
    """GET /api/suscripcion/ — Devuelve la suscripción vigente de la empresa del usuario autenticado."""

    permission_classes = [IsAuthenticated, TieneEmpresaActiva]

    def get(self, request):
        # Aislamiento multi-tenant: la empresa siempre sale del usuario autenticado, nunca de parámetros externos
        empresa = obtener_empresa_de_request(request)
        suscripcion = crear_suscripcion_inicial(empresa)
        serializer = SuscripcionDetalleSerializer(suscripcion)
        return Response(serializer.data, status=status.HTTP_200_OK)


class CambiarPlanAPIView(APIView):
    """POST /api/suscripcion/cambiar-plan/ — Cambia el plan de la empresa activa."""

    permission_classes = [IsAuthenticated, TieneEmpresaActiva]

    def post(self, request):
        serializer = CambiarPlanSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        empresa = obtener_empresa_de_request(request)
        codigo_plan = serializer.validated_data["plan"]
        ciclo = serializer.validated_data.get("ciclo", Suscripcion.Ciclo.MENSUAL)
        motivo = serializer.validated_data.get("motivo", "")

        # TODO(pasarela-pagos): Cuando se integre la pasarela de cobro recurrente para suscripciones
        # SaaS, si el plan destino es pago, aquí se deberá generar la intención de cobro / link de
        # checkout y confirmar el cambio definitivo tras validar el webhook de pago aprobado.
        try:
            suscripcion = cambiar_plan(
                empresa=empresa,
                plan=codigo_plan,
                ciclo=ciclo,
                motivo=motivo,
            )
        except DowngradeNoPermitido as exc:
            return Response(
                {
                    "code": "downgrade_not_allowed",
                    "detail": exc.messages[0] if exc.messages else str(exc),
                    "excesos": exc.excesos,
                },
                status=status.HTTP_400_BAD_REQUEST,
            )
        except DjangoValidationError as exc:
            return Response(
                {
                    "code": "invalid_plan_change",
                    "detail": exc.messages[0] if exc.messages else str(exc),
                },
                status=status.HTTP_400_BAD_REQUEST,
            )

        salida = SuscripcionDetalleSerializer(suscripcion)
        return Response(salida.data, status=status.HTTP_200_OK)
