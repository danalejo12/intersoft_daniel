"""Catálogo central de permisos y plantillas de roles por defecto para cada negocio."""
from django.utils.translation import gettext_noop
from .models import Permiso, Rol

GRUPOS_PERMISOS = (
    (
        gettext_noop("Negocio y equipo"),
        (
            ("negocio.editar", gettext_noop("Editar datos del negocio")),
            ("pagos.configurar", gettext_noop("Conectar y administrar la pasarela de pagos (llaves de Wompi)")),
            ("equipo.ver", gettext_noop("Ver miembros del equipo y roles")),
            ("equipo.gestionar", gettext_noop("Gestionar miembros del equipo y roles")),
        ),
    ),
    (
        gettext_noop("Clientes"),
        (
            ("clientes.ver", gettext_noop("Ver clientes")),
            ("clientes.crear", gettext_noop("Crear clientes")),
            ("clientes.editar", gettext_noop("Editar clientes")),
            ("clientes.eliminar", gettext_noop("Desactivar clientes")),
        ),
    ),
    (
        gettext_noop("Inventario"),
        (
            ("inventario.ver", gettext_noop("Ver productos y kardex")),
            ("inventario.crear", gettext_noop("Crear productos")),
            ("inventario.editar", gettext_noop("Editar productos")),
            ("inventario.movimientos", gettext_noop("Registrar entradas, salidas y ajustes de stock")),
            ("inventario.eliminar", gettext_noop("Desactivar productos")),
        ),
    ),
    (
        gettext_noop("Ventas, POS y facturación"),
        (
            ("ventas.ver", gettext_noop("Ver facturas, turnos de caja y recibos")),
            ("ventas.crear", gettext_noop("Crear facturas y vender en el punto de venta (POS)")),
            ("ventas.cobrar", gettext_noop("Cobrar facturas con pasarela de pagos")),
            ("facturas.anular", gettext_noop("Anular facturas emitidas")),
        ),
    ),
    (
        gettext_noop("Módulos ERP y reportes"),
        (
            ("compras.ver", gettext_noop("Ver proveedores y compras")),
            ("compras.gestionar", gettext_noop("Registrar y recibir compras y proveedores")),
            ("cartera.ver", gettext_noop("Ver cuentas por cobrar y por pagar")),
            ("cartera.gestionar", gettext_noop("Gestionar cuentas por cobrar y por pagar")),
            ("tesoreria.ver", gettext_noop("Ver cajas, bancos y movimientos de tesorería")),
            ("tesoreria.gestionar", gettext_noop("Registrar ingresos, egresos y conciliaciones")),
            ("contabilidad.ver", gettext_noop("Ver plan de cuentas y comprobantes contables")),
            ("contabilidad.gestionar", gettext_noop("Crear y confirmar comprobantes contables")),
            ("nomina.ver", gettext_noop("Ver empleados y liquidaciones de nómina")),
            ("nomina.gestionar", gettext_noop("Gestionar empleados y aprobar nómina")),
            ("produccion.ver", gettext_noop("Ver órdenes de producción")),
            ("produccion.gestionar", gettext_noop("Crear y completar órdenes de producción")),
            ("agenda.ver", gettext_noop("Ver catálogo de servicios y agenda de citas")),
            ("agenda.gestionar", gettext_noop("Agendar y atender citas de servicios")),
            ("reportes.ver", gettext_noop("Ver reportes operativos y financieros")),
        ),
    ),
    (
        gettext_noop("Atención al cliente (PQRS)"),
        (
            ("pqrs.gestionar", gettext_noop("Ver y responder PQRS de compradores y radicar a Intersoft")),
        ),
    ),
)

CATALOGO_PERMISOS = tuple(
    permiso for _, permisos in GRUPOS_PERMISOS for permiso in permisos
)

ROLES_BASE = (
    {
        "nombre": gettext_noop("Cajero POS"),
        "descripcion": gettext_noop("Atención en mostrador: abre y cierra caja, vende en POS y consulta o registra clientes."),
        "permisos": (
            "ventas.crear",
            "ventas.ver",
            "clientes.ver",
            "clientes.crear",
            "inventario.ver",
        ),
    },
    {
        "nombre": gettext_noop("Asesor comercial"),
        "descripcion": gettext_noop("Gestión de clientes, facturación, cobros y agenda de servicios."),
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
            "pqrs.gestionar",
        ),
    },
    {
        "nombre": gettext_noop("Bodega e inventario"),
        "descripcion": gettext_noop("Control de catálogo de productos, movimientos de kardex, compras y producción."),
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
        "nombre": gettext_noop("Contador"),
        "descripcion": gettext_noop("Consulta de facturación y gestión de cartera, tesorería, contabilidad, nómina y reportes."),
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
        "nombre": gettext_noop("Empleado"),
        "descripcion": gettext_noop("Consulta básica de catálogo, clientes y agenda de servicios."),
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
