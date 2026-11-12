from django.contrib.auth import views as auth_views
from django.urls import include, path

from . import views, views_compra, views_equipo, views_erp, views_pedidos_panel, views_pos, views_tienda

# Todo lo que exige negocio vive bajo panel/. Los nombres de ruta no cambian.
panel_urlpatterns = [
    path("", views.DashboardView.as_view(), name="dashboard"),
    path("negocio/", views.DatosNegocioView.as_view(), name="negocio_datos"),
    path("negocio/cambiar/", views.CambiarNegocioView.as_view(), name="negocio_cambiar"),

    # Equipo y roles
    path("equipo/", views_equipo.EquipoView.as_view(), name="equipo_lista"),
    path("equipo/miembros/nuevo/", views_equipo.MiembroCreateView.as_view(), name="equipo_miembro_crear"),
    path("equipo/miembros/<uuid:pk>/editar/", views_equipo.MiembroUpdateView.as_view(), name="equipo_miembro_editar"),
    path("equipo/roles/nuevo/", views_equipo.RolCreateView.as_view(), name="equipo_rol_crear"),
    path("equipo/roles/<uuid:pk>/editar/", views_equipo.RolUpdateView.as_view(), name="equipo_rol_editar"),
    path("equipo/roles/<uuid:pk>/eliminar/", views_equipo.RolDeleteView.as_view(), name="equipo_rol_eliminar"),

    # Clientes
    path("clientes/", views.ClienteListView.as_view(), name="clientes_lista"),
    path("clientes/nuevo/", views.ClienteCreateView.as_view(), name="clientes_crear"),
    path("clientes/<uuid:pk>/editar/", views.ClienteUpdateView.as_view(), name="clientes_editar"),
    path("clientes/<uuid:pk>/eliminar/", views.ClienteDeleteView.as_view(), name="clientes_eliminar"),

    # Categorías y Productos
    path("categorias/", views.CategoriaListView.as_view(), name="categorias_lista"),
    path("categorias/nueva/", views.CategoriaCreateView.as_view(), name="categorias_crear"),
    path("categorias/<uuid:pk>/editar/", views.CategoriaUpdateView.as_view(), name="categorias_editar"),
    path("categorias/<uuid:pk>/eliminar/", views.CategoriaDeleteView.as_view(), name="categorias_eliminar"),
    path("productos/", views.ProductoListView.as_view(), name="productos_lista"),
    path("productos/nuevo/", views.ProductoCreateView.as_view(), name="productos_crear"),
    path("productos/<uuid:pk>/", views.ProductoKardexView.as_view(), name="productos_kardex"),
    path("productos/<uuid:pk>/editar/", views.ProductoUpdateView.as_view(), name="productos_editar"),
    path("productos/<uuid:pk>/movimiento/", views.MovimientoCreateView.as_view(), name="productos_movimiento"),
    path("productos/<uuid:pk>/eliminar/", views.ProductoDeleteView.as_view(), name="productos_eliminar"),

    # Facturas y pedidos del marketplace
    path("facturas/", views.FacturaListView.as_view(), name="facturas_lista"),
    path("facturas/nueva/", views.FacturaCreateView.as_view(), name="facturas_crear"),
    path("facturas/<uuid:pk>/", views.FacturaDetailView.as_view(), name="facturas_detalle"),
    path("facturas/<uuid:pk>/anular/", views.FacturaAnularView.as_view(), name="facturas_anular"),
    path("facturas/<uuid:pk>/emitir-dian/", views.FacturaEmitirDianView.as_view(), name="facturas_emitir_dian"),
    path("facturas/<uuid:pk>/contabilizar/", views.FacturaContabilizarView.as_view(), name="facturas_contabilizar"),
    path("facturas/<uuid:pk>/cobrar/", views.FacturaCobrarView.as_view(), name="facturas_cobrar"),
    path("pedidos/", views_pedidos_panel.PedidoPanelListView.as_view(), name="pedidos_panel_lista"),
    path("pedidos/<uuid:pk>/", views_pedidos_panel.PedidoPanelDetailView.as_view(), name="pedidos_panel_detalle"),

    # Punto de venta (mostrador)
    path("pos/", views_pos.PosView.as_view(), name="pos"),
    path("pos/abrir/", views_pos.AbrirTurnoView.as_view(), name="pos_abrir"),
    path("pos/productos/", views_pos.BuscarProductosView.as_view(), name="pos_productos"),
    path("pos/clientes/", views_pos.BuscarClientesView.as_view(), name="pos_clientes"),
    path("pos/vender/", views_pos.VenderView.as_view(), name="pos_vender"),
    path("pos/cerrar/", views_pos.CerrarTurnoView.as_view(), name="pos_cerrar"),
    path("pos/cajas/", views_pos.TurnosView.as_view(), name="pos_turnos"),
    path("pos/cajas/<uuid:pk>/", views_pos.TurnoView.as_view(), name="pos_turno"),
    path("pos/ticket/<uuid:pk>/", views_pos.TicketView.as_view(), name="pos_ticket"),

    # Pagos
    path("pagos/<uuid:pk>/resultado/", views.PagoResultadoView.as_view(), name="pagos_resultado"),
    path("pagos/<uuid:pk>/simulador/", views.PagoSimuladorView.as_view(), name="pagos_simulador"),

    # Módulos ERP y reportes
    path("erp/", views_erp.InicioERP.as_view(), name="erp_inicio"),
    path("erp/reportes/", views_erp.ReportesERP.as_view(), name="erp_reportes"),
    path("erp/cartera/factura/", views_erp.CarteraFacturaERP.as_view(), name="erp_cartera_factura"),
    path("erp/<slug:modulo>/", views_erp.ListaERP.as_view(), name="erp_lista"),
    path("erp/<slug:modulo>/nuevo/", views_erp.CrearERP.as_view(), name="erp_crear"),
    path("erp/<slug:modulo>/<uuid:pk>/", views_erp.DetalleERP.as_view(), name="erp_detalle"),
]

urlpatterns = [
    # Marketplace público
    path("", views_tienda.MarketplaceView.as_view(), name="marketplace"),
    path("tienda/producto/<uuid:pk>/", views_tienda.ProductoPublicoView.as_view(), name="tienda_producto"),
    path("tienda/<slug:slug>/", views_tienda.TiendaNegocioView.as_view(), name="tienda_negocio"),

    # Opiniones
    path("tienda/producto/<uuid:pk>/comentar/", views_compra.ComentarView.as_view(), name="comentar"),
    path("comentarios/<uuid:pk>/eliminar/", views_compra.EliminarComentarioView.as_view(), name="comentario_eliminar"),

    # Carrito y compra
    path("carrito/", views_compra.CarritoView.as_view(), name="carrito"),
    path("carrito/agregar/<uuid:pk>/", views_compra.AgregarAlCarritoView.as_view(), name="carrito_agregar"),
    path("carrito/actualizar/<uuid:pk>/", views_compra.ActualizarCarritoView.as_view(), name="carrito_actualizar"),
    path("carrito/quitar/<uuid:pk>/", views_compra.QuitarDelCarritoView.as_view(), name="carrito_quitar"),
    path("comprar/<slug:slug>/", views_compra.CheckoutView.as_view(), name="checkout"),

    # Pedidos de cada comprador
    path("pedidos/", views_compra.MisPedidosView.as_view(), name="mis_pedidos"),
    path("pedidos/<uuid:pk>/", views_compra.PedidoDetalleView.as_view(), name="pedido_detalle"),
    path("pedidos/<uuid:pk>/estado/", views_compra.EstadoPedidoView.as_view(), name="pedido_estado"),
    path("pedidos/<uuid:pk>/pagar/", views_compra.PagarPedidoView.as_view(), name="pedido_pagar"),
    path("pedidos/<uuid:pk>/cancelar/", views_compra.CancelarPedidoView.as_view(), name="pedido_cancelar"),
    path("pedidos/<uuid:pk>/renovar/", views_compra.RenovarReservaView.as_view(), name="pedido_renovar"),

    # Cuentas
    path("registro/", views_tienda.RegistroCompradorView.as_view(), name="registro"),
    path("negocio/registrar/", views_tienda.RegistrarNegocioView.as_view(), name="negocio_registrar"),
    path("login/", auth_views.LoginView.as_view(template_name="core/login.html"), name="login"),
    path("logout/", auth_views.LogoutView.as_view(), name="logout"),
    path("entrar/", views_tienda.despues_de_login, name="despues_login"),

    # Panel de cada negocio
    path("panel/", include(panel_urlpatterns)),

    # Wompi tiene esta dirección configurada: no se mueve
    path("webhooks/wompi/", views.WompiWebhookView.as_view(), name="wompi_webhook"),
]
