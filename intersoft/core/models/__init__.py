"""
Paquete de modelos de Intersoft (app core).
 
Django solo busca modelos en core.models, así que aquí se importan todos.
Si creas un archivo nuevo en esta carpeta, agrégalo también a esta lista.
"""
from .base import ModeloBase, ModeloTenant, TenantQuerySet
from .empresas import Empresa
from .usuarios import Usuario, Permiso, Rol, Membresia
from .clientes import Cliente
from .inventario import (
    FOTOS_EXTRA_MAXIMO, Bodega, Categoria, Existencia, FotoProducto, MovimientoInventario, Producto,
)
from .ventas import Factura, DetalleFactura
from .pagos import AuditoriaPagos, ConfiguracionPagos, Pago
from .pedidos import Comentario, DetallePedido, Orden, Pedido
from .caja import PagoCaja, TurnoCaja
from .tareas import EjecucionTarea
from .erp import (
    Proveedor, Compra, LineaCompra, CuentaTesoreria, CuentaCartera,
    MovimientoTesoreria, CuentaContable, AsientoContable, LineaAsiento,
    Empleado, LiquidacionNomina, OrdenProduccion, InsumoProduccion, Servicio, Cita,
)
 
__all__ = [
    "ModeloBase", "ModeloTenant", "TenantQuerySet",
    "Empresa",
    "Usuario", "Permiso", "Rol", "Membresia",
    "Cliente",
    "Categoria", "Producto", "FotoProducto", "FOTOS_EXTRA_MAXIMO", "MovimientoInventario",
    "Factura", "DetalleFactura",
]
