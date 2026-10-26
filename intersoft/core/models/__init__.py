"""
Paquete de modelos de Intersoft (app core).
 
Django solo busca modelos en core.models, así que aquí se importan todos.
Si creas un archivo nuevo en esta carpeta, agrégalo también a esta lista.
"""
from .base import ModeloBase, ModeloTenant, TenantQuerySet
from .empresas import Empresa
from .usuarios import Usuario, Permiso, Rol, Membresia
from .clientes import Cliente
from .inventario import Categoria, Producto, MovimientoInventario
from .ventas import Factura, DetalleFactura
 
__all__ = [
    "ModeloBase", "ModeloTenant", "TenantQuerySet",
    "Empresa",
    "Usuario", "Permiso", "Rol", "Membresia",
    "Cliente",
    "Categoria", "Producto", "MovimientoInventario",
    "Factura", "DetalleFactura",
]
 