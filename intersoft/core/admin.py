"""Intersoft — registro de modelos en el panel de administración de Django."""
from django.contrib import admin
from django.contrib.auth.admin import UserAdmin
 
from .models import (
    Categoria, Cliente, DetalleFactura, Empresa, Factura, Membresia,
    MovimientoInventario, Permiso, Producto, Rol, Usuario,
)
 
 
@admin.register(Usuario)
class UsuarioAdmin(UserAdmin):
    ordering = ["email"]
    list_display = ["email", "username", "first_name", "last_name", "is_staff", "is_active"]
    search_fields = ["email", "username", "first_name", "last_name"]
 
 
@admin.register(Empresa)
class EmpresaAdmin(admin.ModelAdmin):
    list_display = ["nombre", "nit", "plan", "activa", "creado_en"]
    list_filter = ["plan", "activa"]
    search_fields = ["nombre", "nit"]
    prepopulated_fields = {"slug": ["nombre"]}
 
 
@admin.register(Permiso)
class PermisoAdmin(admin.ModelAdmin):
    list_display = ["codigo", "descripcion"]
    search_fields = ["codigo"]
 
 
@admin.register(Rol)
class RolAdmin(admin.ModelAdmin):
    list_display = ["nombre", "empresa", "es_admin"]
    list_filter = ["empresa", "es_admin"]
    filter_horizontal = ["permisos"]
 
 
@admin.register(Membresia)
class MembresiaAdmin(admin.ModelAdmin):
    list_display = ["usuario", "empresa", "rol", "activa"]
    list_filter = ["empresa", "activa"]
    list_select_related = ["usuario", "empresa", "rol"]
 
 
@admin.register(Cliente)
class ClienteAdmin(admin.ModelAdmin):
    list_display = ["nombre", "tipo_documento", "numero_documento", "empresa", "activo"]
    list_filter = ["empresa", "tipo_documento", "activo"]
    search_fields = ["nombre", "numero_documento"]
 
 
@admin.register(Categoria)
class CategoriaAdmin(admin.ModelAdmin):
    list_display = ["nombre", "empresa", "activa"]
    list_filter = ["empresa"]
 
 
@admin.register(Producto)
class ProductoAdmin(admin.ModelAdmin):
    list_display = ["codigo", "nombre", "empresa", "precio", "stock", "activo"]
    list_filter = ["empresa", "categoria", "activo"]
    search_fields = ["codigo", "nombre"]
 
 
@admin.register(MovimientoInventario)
class MovimientoInventarioAdmin(admin.ModelAdmin):
    list_display = ["producto", "tipo", "cantidad", "referencia", "usuario", "creado_en"]
    list_filter = ["empresa", "tipo"]
 
 
class DetalleFacturaInline(admin.TabularInline):
    model = DetalleFactura
    extra = 0
    fields = ["producto", "cantidad", "precio_unitario", "iva_porcentaje"]
 
 
@admin.register(Factura)
class FacturaAdmin(admin.ModelAdmin):
    list_display = ["numero", "cliente", "empresa", "estado", "total", "creado_en"]
    list_filter = ["empresa", "estado"]
    search_fields = ["numero", "cliente__nombre"]
    inlines = [DetalleFacturaInline]
    
from django.contrib.auth.models import Group
admin.site.unregister(Group)