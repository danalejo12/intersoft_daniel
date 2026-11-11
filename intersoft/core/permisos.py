"""Catálogo central de permisos y plantillas de roles por defecto para cada negocio."""
from .models import Permiso, Rol

GRUPOS_PERMISOS = (
    (
        "Negocio y equipo",
        (
            ("negocio.editar", "Editar datos del negocio"),
            ("equipo.ver", "Ver miembros del equipo y roles"),
            ("equipo.gestionar", "Gestionar miembros del equipo y roles"),
        ),
    ),
    (
        "Clientes",
        (
            ("clientes.ver", "Ver clientes"),
            ("clientes.crear", "Crear clientes"),
            ("clientes.editar", "Editar clientes"),
            ("clientes.eliminar", "Desactivar clientes"),
        ),
    ),
    (
        "Inventario",
        (
            ("inventario.ver", "Ver productos y kardex"),
            ("inventario.crear", "Crear productos"),
            ("inventario.editar", "Editar productos"),
            ("inventario.movimientos", "Registrar entradas, salidas y ajustes de stock"),
            ("inventario.eliminar", "Desactivar productos"),
        ),
    ),
    (
        "Ventas, POS y facturación",
        (
            ("ventas.ver", "Ver facturas, turnos de caja y recibos"),
            ("ventas.crear", "Crear facturas y vender en el punto de venta (POS)"),
            ("ventas.cobrar", "Cobrar facturas con pasarela de pagos"),
            ("facturas.anular", "Anular facturas emitidas"),
        ),
    ),
    (
        "Módulos ERP y reportes",
        (
            ("compras.ver", "Ver proveedores y compras"),
            ("compras.gestionar", "Registrar y recibir compras y proveedores"),
            ("cartera.ver", "Ver cuentas por cobrar y por pagar"),
            ("cartera.gestionar", "Gestionar cuentas por cobrar y por pagar"),
            ("tesoreria.ver", "Ver cajas, bancos y movimientos de tesorería"),
            ("tesoreria.gestionar", "Registrar ingresos, egresos y conciliaciones"),
            ("contabilidad.ver", "Ver plan de cuentas y comprobantes contables"),
            ("contabilidad.gestionar", "Crear y confirmar comprobantes contables"),
            ("nomina.ver", "Ver empleados y liquidaciones de nómina"),
            ("nomina.gestionar", "Gestionar empleados y aprobar nómina"),
            ("produccion.ver", "Ver órdenes de producción"),
            ("produccion.gestionar", "Crear y completar órdenes de producción"),
            ("agenda.ver", "Ver catálogo de servicios y agenda de citas"),
            ("agenda.gestionar", "Agendar y atender citas de servicios"),
            ("reportes.ver", "Ver reportes operativos y financieros"),
        ),
    ),
)

CATALOGO_PERMISOS = tuple(
    permiso for _, permisos in GRUPOS_PERMISOS for permiso in permisos
)

ROLES_BASE = (
    {
        "nombre": "Cajero POS",
        "descripcion": "Atención en mostrador: abre y cierra caja, vende en POS y consulta o registra clientes.",
        "permisos": (
            "ventas.crear",
            "ventas.ver",
            "clientes.ver",
            "clientes.crear",
            "inventario.ver",
        ),
    },
    {
        "nombre": "Asesor comercial",
        "descripcion": "Gestión de clientes, facturación, cobros y agenda de servicios.",
        "permisos": (
            "clientes.ver",
            "clientes.crear",
            "clientes.editar",
            "ventas.ver",
            "ventas.crear",
            "ventas.cobrar",
            "inventario.ver",
            "agenda.ver",
            "agenda.gestionar",
        ),
    },
    {
        "nombre": "Bodega e inventario",
        "descripcion": "Control de catálogo de productos, movimientos de kardex, compras y producción.",
        "permisos": (
            "inventario.ver",
            "inventario.crear",
            "inventario.editar",
            "inventario.movimientos",
            "compras.ver",
            "compras.gestionar",
            "produccion.ver",
            "produccion.gestionar",
        ),
    },
    {
        "nombre": "Contador",
        "descripcion": "Consulta de facturación y gestión de cartera, tesorería, contabilidad, nómina y reportes.",
        "permisos": (
            "ventas.ver",
            "clientes.ver",
            "compras.ver",
            "cartera.ver",
            "cartera.gestionar",
            "tesoreria.ver",
            "tesoreria.gestionar",
            "contabilidad.ver",
            "contabilidad.gestionar",
            "nomina.ver",
            "reportes.ver",
        ),
    },
    {
        "nombre": "Empleado",
        "descripcion": "Consulta básica de catálogo, clientes y agenda de servicios.",
        "permisos": (
            "inventario.ver",
            "clientes.ver",
            "agenda.ver",
        ),
    },
)


def sincronizar_catalogo_permisos(modelo_permiso=Permiso):
    """Garantiza que todos los permisos del catálogo existan en la base de datos."""
    existentes = {p.codigo: p for p in modelo_permiso.objects.all()}
    for codigo, descripcion in CATALOGO_PERMISOS:
        permiso = existentes.get(codigo)
        if permiso is None:
            permiso = modelo_permiso.objects.create(codigo=codigo, descripcion=descripcion)
            existentes[codigo] = permiso
        elif permiso.descripcion != descripcion:
            permiso.descripcion = descripcion
            permiso.save(update_fields=["descripcion"])
    return existentes


def crear_roles_base(empresa):
    """Crea las plantillas de roles iniciales para una empresa sin alterar roles ya existentes."""
    permisos_por_codigo = sincronizar_catalogo_permisos()
    creados = []
    for plantilla in ROLES_BASE:
        rol, creado = Rol.objects.get_or_create(
            empresa=empresa,
            nombre=plantilla["nombre"],
            defaults={
                "descripcion": plantilla["descripcion"],
                "es_admin": False,
            },
        )
        if creado:
            rol.permisos.set([permisos_por_codigo[c] for c in plantilla["permisos"]])
            creados.append(rol)
    return creados
