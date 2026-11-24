"""Intersoft — registro de modelos en el panel de administración de Django."""
from django.contrib import admin
from django.contrib.auth.admin import UserAdmin

from .models import (
    Categoria, Cliente, DetalleFactura, Empresa, Factura, Membresia,
    MovimientoInventario, Permiso, Producto, Rol, Usuario, Pago, Pedido, Comentario, DetallePedido,
    PagoCaja, TurnoCaja, EjecucionTarea, Bodega,
)


@admin.register(Bodega)
class BodegaAdmin(admin.ModelAdmin):
    # Las marcas Principal / En línea y la desactivación se manejan en el panel (core.bodegas), que valida las reglas
    """Administración de bodegas en /admin/ (columnas, filtros y campos de solo lectura)."""
    list_display = ["nombre", "empresa", "es_principal", "vende_en_linea", "activa"]
    list_filter = ["empresa", "activa"]
    readonly_fields = ["es_principal", "vende_en_linea", "activa"]


@admin.register(EjecucionTarea)
class EjecucionTareaAdmin(admin.ModelAdmin):
    """Administración de ejecuciones de tareas periódicas en /admin/ (columnas, filtros y campos de solo lectura)."""
    list_display = ["nombre", "ultima_ejecucion", "ejecuciones", "fallos_seguidos", "ultimo_error"]
    readonly_fields = ["nombre", "ultima_ejecucion", "ultimo_resultado", "ultimo_error", "ejecuciones",
                       "fallos_seguidos"]

    def has_add_permission(self, request):
        return False


@admin.register(Usuario)
class UsuarioAdmin(UserAdmin):
    """Administración de usuarios en /admin/ (columnas, filtros y campos de solo lectura)."""
    ordering = ["email"]
    list_display = ["email", "username", "first_name", "last_name", "is_staff", "is_active"]
    search_fields = ["email", "username", "first_name", "last_name"]


@admin.register(Empresa)
class EmpresaAdmin(admin.ModelAdmin):
    """Administración de empresas en /admin/ (columnas, filtros y campos de solo lectura)."""
    list_display = ["nombre", "nit", "plan", "comision_porcentaje", "tarifa_envio_base", "activa", "creado_en"]
    list_filter = ["plan", "activa"]
    search_fields = ["nombre", "nit"]
    prepopulated_fields = {"slug": ["nombre"]}


@admin.register(Permiso)
class PermisoAdmin(admin.ModelAdmin):
    """Administración de permisos en /admin/ (columnas, filtros y campos de solo lectura)."""
    list_display = ["codigo", "descripcion"]
    search_fields = ["codigo"]


@admin.register(Rol)
class RolAdmin(admin.ModelAdmin):
    """Administración de roles en /admin/ (columnas, filtros y campos de solo lectura)."""
    list_display = ["nombre", "empresa", "es_admin"]
    list_filter = ["empresa", "es_admin"]
    filter_horizontal = ["permisos"]


@admin.register(Membresia)
class MembresiaAdmin(admin.ModelAdmin):
    """Administración de membresías en /admin/ (columnas, filtros y campos de solo lectura)."""
    list_display = ["usuario", "empresa", "rol", "activa"]
    list_filter = ["empresa", "activa"]
    list_select_related = ["usuario", "empresa", "rol"]


@admin.register(Cliente)
class ClienteAdmin(admin.ModelAdmin):
    """Administración de clientes en /admin/ (columnas, filtros y campos de solo lectura)."""
    list_display = ["nombre", "tipo_documento", "numero_documento", "empresa", "activo"]
    list_filter = ["empresa", "tipo_documento", "activo"]
    search_fields = ["nombre", "numero_documento"]


@admin.register(Categoria)
class CategoriaAdmin(admin.ModelAdmin):
    """Administración de categorías en /admin/ (columnas, filtros y campos de solo lectura)."""
    list_display = ["nombre", "empresa", "activa"]
    list_filter = ["empresa"]


@admin.register(Producto)
class ProductoAdmin(admin.ModelAdmin):
    """Administración de productos en /admin/ (columnas, filtros y campos de solo lectura)."""
    list_display = ["codigo", "nombre", "empresa", "precio", "stock", "activo"]
    list_filter = ["empresa", "categoria", "activo"]
    search_fields = ["codigo", "nombre"]


@admin.register(MovimientoInventario)
class MovimientoInventarioAdmin(admin.ModelAdmin):
    """Administración de movimientos de inventario en /admin/ (columnas, filtros y campos de solo lectura)."""
    list_display = ["producto", "tipo", "cantidad", "referencia", "usuario", "creado_en"]
    list_filter = ["empresa", "tipo"]


class DetalleFacturaInline(admin.TabularInline):
    """Configuración del panel de administración de Django (/admin/)."""
    model = DetalleFactura
    extra = 0
    fields = ["producto", "cantidad", "precio_unitario", "iva_porcentaje"]


@admin.register(Factura)
class FacturaAdmin(admin.ModelAdmin):
    """Administración de facturas en /admin/ (columnas, filtros y campos de solo lectura)."""
    list_display = ["numero", "cliente", "empresa", "estado", "total", "creado_en"]
    list_filter = ["empresa", "estado"]
    search_fields = ["numero", "cliente__nombre"]
    inlines = [DetalleFacturaInline]

from django.contrib.auth.models import Group
admin.site.unregister(Group)

@admin.register(Pago)
class PagoAdmin(admin.ModelAdmin):
    """Administración de pagos en /admin/ (columnas, filtros y campos de solo lectura)."""
    list_display = ["referencia", "factura", "pedido", "empresa", "monto_centavos", "estado", "creado_en"]
    list_filter = ["empresa", "estado"]
    search_fields = ["referencia", "wompi_transaccion_id"]
    readonly_fields = ["referencia", "monto_centavos", "moneda", "wompi_transaccion_id"]


class DetallePedidoInline(admin.TabularInline):
    """Configuración del panel de administración de Django (/admin/)."""
    model = DetallePedido
    extra = 0
    can_delete = False
    fields = readonly_fields = ["producto", "cantidad", "precio_unitario", "iva_porcentaje"]


@admin.register(Pedido)
class PedidoAdmin(admin.ModelAdmin):
    """Administración de pedidos en /admin/ (columnas, filtros y campos de solo lectura)."""
    list_display = [
        "numero",
        "nombre",
        "estado",
        "estado_envio",
        "total",
        "comision_valor",
        "neto_vendedor",
        "empresa",
        "expira_en",
        "creado_en",
    ]
    # El filtro por estado permite encontrar los pedidos en requiere_reembolso
    list_filter = ["estado", "estado_envio", "empresa", "departamento"]
    list_select_related = ["empresa"]
    search_fields = ["nombre", "email", "numero_documento", "numero_guia", "reembolso_referencia"]
    inlines = [DetallePedidoInline]


@admin.register(Comentario)
class ComentarioAdmin(admin.ModelAdmin):
    """Administración de comentarios en /admin/ (columnas, filtros y campos de solo lectura)."""
    list_display = ["producto", "calificacion", "compra_verificada", "empresa", "creado_en"]
    list_filter = ["empresa", "calificacion", "compra_verificada"]


@admin.register(TurnoCaja)
class TurnoCajaAdmin(admin.ModelAdmin):
    """Administración de turnos de caja en /admin/ (columnas, filtros y campos de solo lectura)."""
    list_display = ["creado_en", "cajero", "empresa", "base_inicial", "cerrado_en", "diferencia"]
    list_filter = ["empresa"]
    list_select_related = ["cajero", "empresa"]
    # El arqueo no se edita a mano: queda como se cerró
    readonly_fields = ["base_inicial", "cerrado_en", "efectivo_esperado", "efectivo_contado", "diferencia"]


@admin.register(PagoCaja)
class PagoCajaAdmin(admin.ModelAdmin):
    """Administración de pagos de caja en /admin/ (columnas, filtros y campos de solo lectura)."""
    list_display = ["factura", "metodo", "monto", "recibido", "cambio", "empresa", "creado_en"]
    list_filter = ["empresa", "metodo"]
    readonly_fields = ["factura", "turno", "metodo", "monto", "recibido", "cambio"]
