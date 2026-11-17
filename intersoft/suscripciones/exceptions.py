"""Excepciones de dominio y manejador DRF para límites de plan."""
from rest_framework import status
from rest_framework.exceptions import APIException
from rest_framework.views import exception_handler

from core.models import Empresa

from .models import Plan
from .services import crear_suscripcion_inicial, uso_actual


class LimitePlanExcedido(APIException):
    """Excepción lanzada cuando una empresa alcanza o supera el tope de un recurso en su plan.

    Devuelve HTTP 403 Forbidden con la estructura JSON estándar:
    {
        "code": "plan_limit_reached",
        "recurso": ...,
        "limite": ...,
        "plan_actual": ...,
        "plan_sugerido": ...
    }
    """

    status_code = status.HTTP_403_FORBIDDEN
    default_code = "plan_limit_reached"

    def __init__(self, *, recurso: str, limite: int, plan_actual: str, plan_sugerido: str | None):
        self.recurso = recurso
        self.limite = limite
        self.plan_actual = plan_actual
        self.plan_sugerido = plan_sugerido
        detalle = {
            "code": "plan_limit_reached",
            "recurso": recurso,
            "limite": limite,
            "plan_actual": plan_actual,
            "plan_sugerido": plan_sugerido,
        }
        super().__init__(detail=detalle, code="plan_limit_reached")


def _buscar_plan_sugerido(plan_actual: Plan, recurso: str, cantidad_requerida: int) -> str | None:
    """Busca el siguiente plan activo de orden superior que soporte la cantidad requerida."""
    candidatos = Plan.objects.filter(activo=True, orden__gt=plan_actual.orden).order_by("orden")
    for candidato in candidatos:
        limite_cand = (candidato.limites or {}).get(recurso)
        if limite_cand is None or int(limite_cand) >= int(cantidad_requerida):
            return candidato.codigo
    return None


def verificar_limite(empresa: Empresa, recurso: str, incremento: int = 1) -> bool:
    """Verifica si la empresa puede consumir `incremento` unidades adicionales del `recurso`.

    - Si el plan tiene límite `null` (ilimitado) o `uso_actual + incremento <= limite`, devuelve True.
    - Si al sumar `incremento` (por defecto 1) se excede el límite del plan, lanza `LimitePlanExcedido`.
    """
    from .models import Suscripcion

    suscripcion = (
        Suscripcion.objects.select_related("plan").filter(empresa=empresa).first()
        or crear_suscripcion_inicial(empresa)
    )
    plan_actual = suscripcion.plan
    limite = (plan_actual.limites or {}).get(recurso)
    if limite is None:
        return True

    consumo = uso_actual(empresa)
    actual = int(consumo.get(recurso, 0))
    proyectado = actual + int(incremento)

    if not suscripcion.dentro_del_limite(recurso, proyectado):
        sugerido = _buscar_plan_sugerido(plan_actual, recurso, proyectado)
        raise LimitePlanExcedido(
            recurso=recurso,
            limite=int(limite),
            plan_actual=plan_actual.codigo,
            plan_sugerido=sugerido,
        )
    return True


def manejador_excepciones_suscripciones(exc, context):
    """Garantiza que LimitePlanExcedido conserve sus valores enteros/nulos exactos en el JSON 403."""
    if isinstance(exc, LimitePlanExcedido):
        from rest_framework.response import Response

        return Response(
            {
                "code": "plan_limit_reached",
                "recurso": exc.recurso,
                "limite": exc.limite,
                "plan_actual": exc.plan_actual,
                "plan_sugerido": exc.plan_sugerido,
            },
            status=status.HTTP_403_FORBIDDEN,
        )
    return exception_handler(exc, context)
