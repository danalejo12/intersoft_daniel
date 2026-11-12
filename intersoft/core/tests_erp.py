import uuid
from datetime import timedelta
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from core import caja, erp_services, pagos, services
from core.erp_forms import CarteraFacturaForm
from core.models import (
    AsientoContable,
    Cita,
    Cliente,
    Compra,
    CuentaCartera,
    CuentaContable,
    CuentaTesoreria,
    Empleado,
    Factura,
    LiquidacionNomina,
    Membresia,
    MovimientoInventario,
    MovimientoTesoreria,
    OrdenProduccion,
    Pago,
    Permiso,
    Producto,
    Proveedor,
    Rol,
    Servicio,
)
from core.negocios import registrar_negocio

User = get_user_model()


def _crear_empresa_con_admin(email, nombre):
    usuario = User.objects.create_user(
        username=email,
        email=email,
        password="PasswordSegura123!",
        first_name="Admin",
    )
    empresa = registrar_negocio(
        usuario=usuario,
        datos={
            "nombre": nombre,
            "nit": f"NIT-{email}"[:20],
            "direccion": "Calle 10 # 20-30",
            "telefono": "6012345678",
        },
    )
    return usuario, empresa


class IntegracionCarteraPagosTests(TestCase):
    def setUp(self):
        self.admin, self.empresa = _crear_empresa_con_admin("admin@cartera.co", "Distribuidora Norte")
        self.cliente = Cliente.objects.create(
            empresa=self.empresa,
            tipo_documento="CC",
            numero_documento="10101010",
            nombre="Cliente Cartera",
        )
        self.producto = Producto.objects.create(
            empresa=self.empresa,
            codigo="PROD-1",
            nombre="Monitor 24",
            precio=Decimal("500000.00"),
            iva_porcentaje=Decimal("19.00"),
            stock=20,
            stock_minimo=2,
        )
        self.client.force_login(self.admin)

    def _emitir_factura(self, cantidad=1):
        return services.crear_factura(
            empresa=self.empresa,
            usuario=self.admin,
            cliente=self.cliente,
            items=[{"producto": self.producto, "cantidad": cantidad}],
        )

    def test_cartera_factura_form_excluye_facturas_pagadas_en_pos_wompi_o_pendientes(self):
        f_disponible = self._emitir_factura()
        f_wompi_aprobada = self._emitir_factura()
        Pago.objects.create(
            empresa=self.empresa,
            factura=f_wompi_aprobada,
            referencia="INT-APROBADO",
            monto_centavos=59500000,
            moneda="COP",
            estado=Pago.Estado.APROBADO,
        )

        f_wompi_pendiente = self._emitir_factura()
        Pago.objects.create(
            empresa=self.empresa,
            factura=f_wompi_pendiente,
            referencia="INT-PENDIENTE",
            monto_centavos=59500000,
            moneda="COP",
            estado=Pago.Estado.PENDIENTE,
        )

        # Factura cobrada en POS
        turno = caja.abrir_turno(empresa=self.empresa, usuario=self.admin, base="0")
        f_pos = caja.registrar_venta(
            turno=turno,
            usuario=self.admin,
            items=[{"producto": self.producto, "cantidad": 1}],
            pagos=[{"metodo": "efectivo", "recibido": "600000"}],
        )

        form = CarteraFacturaForm(empresa=self.empresa)
        ids_elegibles = set(form.fields["factura"].queryset.values_list("pk", flat=True))
        self.assertEqual(ids_elegibles, {f_disponible.pk})
        self.assertNotIn(f_wompi_aprobada.pk, ids_elegibles)
        self.assertNotIn(f_wompi_pendiente.pk, ids_elegibles)
        self.assertNotIn(f_pos.pk, ids_elegibles)

    def test_factura_en_cartera_bloquea_cobro_wompi_y_queda_pagada_al_abonar_total(self):
        factura = self._emitir_factura()
        vencimiento = timezone.localdate() + timedelta(days=15)

        resp = self.client.post(
            reverse("erp_cartera_factura"),
            {"factura": str(factura.pk), "vencimiento": vencimiento.isoformat()},
        )
        cuenta_cartera = CuentaCartera.objects.get(factura=factura)
        self.assertRedirects(resp, reverse("erp_detalle", args=["cartera", cuenta_cartera.pk]))

        # Intentar cobrar por Wompi una factura que ya está en cartera debe fallar
        with self.assertRaises(pagos.PagoNoPermitido):
            pagos.crear_pago(factura=factura)

        resp_cobrar = self.client.post(reverse("facturas_cobrar", args=[factura.pk]))
        self.assertRedirects(resp_cobrar, reverse("facturas_lista"))
        self.assertEqual(Pago.objects.filter(factura=factura).count(), 0)

        # Abonar el 100% en tesorería marca la factura como pagada
        banco = CuentaTesoreria.objects.create(
            empresa=self.empresa, nombre="Banco Principal", tipo="banco", activa=True
        )
        erp_services.registrar_tesoreria(
            empresa=self.empresa,
            usuario=self.admin,
            cuenta=banco,
            monto=factura.total,
            tipo="ingreso",
            concepto="Pago factura cliente",
            fecha=timezone.localdate(),
            operacion=uuid.uuid4(),
            cartera=cuenta_cartera,
        )
        factura.refresh_from_db()
        self.assertTrue(factura.esta_pagada)

        # Tampoco se puede anular una factura con abonos en cartera
        with self.assertRaises(ValueError):
            services.anular_factura(factura=factura, usuario=self.admin)


class FlujoOperativoERPTests(TestCase):
    def setUp(self):
        self.admin, self.empresa = _crear_empresa_con_admin("admin@erp.co", "Comercial ERP")
        self.otro_admin, self.otra_empresa = _crear_empresa_con_admin("otro@erp.co", "Empresa Ajena")
        self.producto = Producto.objects.create(
            empresa=self.empresa,
            codigo="INS-01",
            nombre="Teclado Mecánico",
            precio=Decimal("200000.00"),
            iva_porcentaje=Decimal("19.00"),
            stock=5,
            stock_minimo=2,
        )
        self.client.force_login(self.admin)

    def test_flujo_completo_compra_recepcion_kardex_cartera_tesoreria_y_reportes(self):
        # 1. Crear proveedor por vista
        resp_prov = self.client.post(
            reverse("erp_crear", args=["proveedores"]),
            {
                "nombre": "Mayorista Tech",
                "documento": "900555666-1",
                "email": "ventas@mayorista.co",
                "telefono": "6019998877",
                "direccion": "Zona Industrial",
                "activo": True,
            },
        )
        proveedor = Proveedor.objects.get(empresa=self.empresa, documento="900555666-1")
        self.assertRedirects(resp_prov, reverse("erp_detalle", args=["proveedores", proveedor.pk]))

        # 2. Crear compra en borrador
        hoy = timezone.localdate()
        vencimiento = hoy + timedelta(days=30)
        resp_compra = self.client.post(
            reverse("erp_crear", args=["compras"]),
            {
                "proveedor": str(proveedor.pk),
                "referencia": "FAC-PROV-100",
                "fecha": hoy.isoformat(),
                "vencimiento": vencimiento.isoformat(),
                "observaciones": "Pedido mensual",
            },
        )
        compra = Compra.objects.get(empresa=self.empresa, referencia="FAC-PROV-100")
        self.assertRedirects(resp_compra, reverse("erp_detalle", args=["compras", compra.pk]))

        # 3. Agregar línea a la compra (10 unidades a $100.000 + 19% IVA = $1.190.000)
        resp_linea = self.client.post(
            reverse("erp_detalle", args=["compras", compra.pk]),
            {
                "accion": "agregar",
                "producto": str(self.producto.pk),
                "cantidad": 10,
                "costo": "100000.00",
                "iva_porcentaje": "19.00",
            },
        )
        self.assertRedirects(resp_linea, reverse("erp_detalle", args=["compras", compra.pk]))
        self.assertEqual(compra.lineas.count(), 1)

        # 4. Recibir compra -> actualiza stock, kardex y genera CuentaCartera por pagar
        resp_recibir = self.client.post(
            reverse("erp_detalle", args=["compras", compra.pk]),
            {"accion": "recibir"},
        )
        self.assertRedirects(resp_recibir, reverse("erp_detalle", args=["compras", compra.pk]))
        compra.refresh_from_db()
        self.assertTrue(compra.recibida)
        self.assertEqual(compra.subtotal, Decimal("1000000.00"))
        self.assertEqual(compra.iva, Decimal("190000.00"))
        self.assertEqual(compra.total, Decimal("1190000.00"))

        self.producto.refresh_from_db()
        self.assertEqual(self.producto.stock, 15)
        self.assertTrue(
            MovimientoInventario.objects.filter(
                empresa=self.empresa,
                producto=self.producto,
                tipo="entrada",
                cantidad=10,
            ).exists()
        )

        cxp = CuentaCartera.objects.get(compra=compra)
        self.assertEqual(cxp.tipo, "pagar")
        self.assertEqual(cxp.total, Decimal("1190000.00"))
        self.assertEqual(cxp.saldo, Decimal("1190000.00"))

        # 5. Crear cuenta de tesorería y abonar parcialmente con idempotencia
        resp_cta = self.client.post(
            reverse("erp_crear", args=["cuentas"]),
            {"nombre": "Caja General", "tipo": "caja", "activa": True},
        )
        cuenta_tes = CuentaTesoreria.objects.get(empresa=self.empresa, nombre="Caja General")
        self.assertRedirects(resp_cta, reverse("erp_detalle", args=["cuentas", cuenta_tes.pk]))

        op_id = uuid.uuid4()
        datos_egreso = {
            "cuenta": str(cuenta_tes.pk),
            "tipo": "egreso",
            "fecha": hoy.isoformat(),
            "concepto": "Abono inicial proveedor",
            "monto": "500000.00",
            "cartera": str(cxp.pk),
            "referencia": "TRANS-001",
            "operacion": str(op_id),
        }
        resp_tes1 = self.client.post(reverse("erp_crear", args=["tesoreria"]), datos_egreso)
        mov = MovimientoTesoreria.objects.get(operacion=op_id)
        self.assertRedirects(resp_tes1, reverse("erp_detalle", args=["tesoreria", mov.pk]))

        # Reintento idempotente con la misma clave de operación no duplica el abono
        resp_tes2 = self.client.post(reverse("erp_crear", args=["tesoreria"]), datos_egreso)
        self.assertRedirects(resp_tes2, reverse("erp_detalle", args=["tesoreria", mov.pk]))
        self.assertEqual(MovimientoTesoreria.objects.filter(empresa=self.empresa).count(), 1)

        cxp.refresh_from_db()
        self.assertEqual(cxp.abonado, Decimal("500000.00"))
        self.assertEqual(cxp.saldo, Decimal("690000.00"))

        # 6. Verificar reporte operativo y exportación CSV
        resp_rep = self.client.get(reverse("erp_reportes"))
        self.assertEqual(resp_rep.status_code, 200)
        self.assertContains(resp_rep, "690.000")
        self.assertContains(resp_rep, "Caja General")

        resp_csv = self.client.get(reverse("erp_lista", args=["proveedores"]) + "?exportar=csv")
        self.assertEqual(resp_csv.status_code, 200)
        self.assertIn("Mayorista Tech", resp_csv.content.decode("utf-8-sig"))

    def test_permisos_ver_vs_gestionar_y_aislamiento_multitenant(self):
        prov_ajeno = Proveedor.objects.create(
            empresa=self.otra_empresa,
            nombre="Proveedor Ajeno",
            documento="800111222",
        )

        # Admin de self.empresa recibe 404 al intentar ver o tocar registro de otra empresa
        self.assertEqual(
            self.client.get(reverse("erp_detalle", args=["proveedores", prov_ajeno.pk])).status_code,
            404,
        )

        # Crear usuario con solo permiso de consulta ("compras.ver")
        lector = User.objects.create_user(
            username="lector@erp.co", email="lector@erp.co", password="PasswordSegura123!"
        )
        rol_lector = Rol.objects.create(empresa=self.empresa, nombre="Auditor Compras", es_admin=False)
        rol_lector.permisos.add(Permiso.objects.get(codigo="compras.ver"))
        Membresia.objects.create(usuario=lector, empresa=self.empresa, rol=rol_lector, activa=True)

        self.client.force_login(lector)
        self.assertEqual(self.client.get(reverse("erp_inicio")).status_code, 200)
        self.assertEqual(self.client.get(reverse("erp_lista", args=["proveedores"])).status_code, 200)
        # No tiene compras.gestionar -> 403 en crear
        self.assertEqual(self.client.get(reverse("erp_crear", args=["proveedores"])).status_code, 403)
        self.assertEqual(self.client.post(reverse("erp_crear", args=["proveedores"]), {}).status_code, 403)
        # No tiene cartera.ver -> 403 en cartera
        self.assertEqual(self.client.get(reverse("erp_lista", args=["cartera"])).status_code, 403)


class ContabilidadNominaProduccionAgendaERPTests(TestCase):
    def setUp(self):
        self.admin, self.empresa = _crear_empresa_con_admin("admin@modulos.co", "Industrias Integrales")
        self.client.force_login(self.admin)

    def test_contabilidad_partida_doble_borrador_y_reporte_balance(self):
        # 1. Crear dos cuentas contables
        self.client.post(
            reverse("erp_crear", args=["plan-contable"]),
            {"codigo": "110505", "nombre": "Caja General", "naturaleza": "debito"},
        )
        self.client.post(
            reverse("erp_crear", args=["plan-contable"]),
            {"codigo": "413501", "nombre": "Ingresos Operacionales", "naturaleza": "credito"},
        )
        cta_caja = CuentaContable.objects.get(empresa=self.empresa, codigo="110505")
        cta_ingreso = CuentaContable.objects.get(empresa=self.empresa, codigo="413501")

        # 2. Crear comprobante en borrador
        hoy = timezone.localdate().isoformat()
        self.client.post(
            reverse("erp_crear", args=["contabilidad"]),
            {"fecha": hoy, "concepto": "Reconocimiento ingreso", "referencia": "COMP-01"},
        )
        asiento = AsientoContable.objects.get(empresa=self.empresa, referencia="COMP-01")
        url_detalle = reverse("erp_detalle", args=["contabilidad", asiento.pk])

        # 3. Rechazar línea con débito y crédito al mismo tiempo
        resp_invalida = self.client.post(
            url_detalle,
            {
                "accion": "agregar",
                "cuenta": str(cta_caja.pk),
                "debito": "100000.00",
                "credito": "50000.00",
            },
        )
        self.assertEqual(resp_invalida.status_code, 200)
        self.assertEqual(asiento.lineas.count(), 0)

        # 4. Agregar una línea débito e intentar confirmar descuadrado -> falla
        self.client.post(
            url_detalle,
            {
                "accion": "agregar",
                "cuenta": str(cta_caja.pk),
                "debito": "250000.00",
                "credito": "0.00",
            },
        )
        self.client.post(url_detalle, {"accion": "confirmar"})
        asiento.refresh_from_db()
        self.assertFalse(asiento.confirmado)

        # 5. Agregar línea crédito igual al débito y confirmar -> partida doble OK
        self.client.post(
            url_detalle,
            {
                "accion": "agregar",
                "cuenta": str(cta_ingreso.pk),
                "debito": "0.00",
                "credito": "250000.00",
            },
        )
        self.client.post(url_detalle, {"accion": "confirmar"})
        asiento.refresh_from_db()
        self.assertTrue(asiento.confirmado)

        # Ya confirmado no permite eliminarse como borrador
        self.client.post(url_detalle, {"accion": "eliminar_borrador"})
        self.assertTrue(AsientoContable.objects.filter(pk=asiento.pk).exists())

        # Aparece en el balance de comprobación
        resp_rep = self.client.get(reverse("erp_reportes"))
        self.assertContains(resp_rep, "110505")
        self.assertContains(resp_rep, "413501")

        # 6. Un segundo borrador sin confirmar sí se puede eliminar
        self.client.post(
            reverse("erp_crear", args=["contabilidad"]),
            {"fecha": hoy, "concepto": "Borrador descartable", "referencia": "COMP-02"},
        )
        borrador = AsientoContable.objects.get(empresa=self.empresa, referencia="COMP-02")
        resp_del = self.client.post(
            reverse("erp_detalle", args=["contabilidad", borrador.pk]),
            {"accion": "eliminar_borrador"},
        )
        self.assertRedirects(resp_del, reverse("erp_lista", args=["contabilidad"]))
        self.assertFalse(AsientoContable.objects.filter(pk=borrador.pk).exists())

    def test_nomina_aprobacion_cuenta_por_pagar_y_bloqueo_de_solapamiento(self):
        hoy = timezone.localdate()
        self.client.post(
            reverse("erp_crear", args=["empleados"]),
            {
                "nombre": "María Pérez",
                "documento": "52000111",
                "cargo": "Analista",
                "salario_base": "2000000.00",
                "fecha_ingreso": hoy.isoformat(),
                "activo": True,
            },
        )
        empleado = Empleado.objects.get(empresa=self.empresa, documento="52000111")

        desde = hoy.replace(day=1)
        hasta = desde + timedelta(days=14)
        resp_crear = self.client.post(
            reverse("erp_crear", args=["nomina"]),
            {
                "empleado": str(empleado.pk),
                "desde": desde.isoformat(),
                "hasta": hasta.isoformat(),
                "base": "1000000.00",
                "adicionales": "150000.00",
                "deducciones": "80000.00",
                "observaciones": "Primera quincena",
            },
        )
        nomina1 = LiquidacionNomina.objects.get(empresa=self.empresa, empleado=empleado)
        self.assertRedirects(resp_crear, reverse("erp_detalle", args=["nomina", nomina1.pk]))
        self.assertEqual(nomina1.neto, Decimal("1070000.00"))

        # Aprobar primera liquidación -> genera CuentaCartera por pagar
        self.client.post(
            reverse("erp_detalle", args=["nomina", nomina1.pk]),
            {"accion": "aprobar"},
        )
        nomina1.refresh_from_db()
        self.assertTrue(nomina1.aprobada)
        self.assertIsNotNone(nomina1.cartera)
        self.assertEqual(nomina1.cartera.tipo, "pagar")
        self.assertEqual(nomina1.cartera.total, Decimal("1070000.00"))

        # Crear segunda liquidación con período solapado e intentar aprobar -> se rechaza
        nomina_solapada = LiquidacionNomina.objects.create(
            empresa=self.empresa,
            empleado=empleado,
            desde=desde + timedelta(days=10),
            hasta=desde + timedelta(days=25),
            base=Decimal("1000000.00"),
            adicionales=Decimal("0.00"),
            deducciones=Decimal("50000.00"),
            neto=Decimal("950000.00"),
        )
        self.client.post(
            reverse("erp_detalle", args=["nomina", nomina_solapada.pk]),
            {"accion": "aprobar"},
        )
        nomina_solapada.refresh_from_db()
        self.assertFalse(nomina_solapada.aprobada)

    def test_produccion_consumo_de_insumos_y_entrada_de_producto_terminado(self):
        harina = Producto.objects.create(
            empresa=self.empresa,
            codigo="INS-HAR",
            nombre="Harina 50kg",
            precio=Decimal("120000.00"),
            stock=10,
            stock_minimo=2,
        )
        pan = Producto.objects.create(
            empresa=self.empresa,
            codigo="PT-PAN",
            nombre="Lote Pan",
            precio=Decimal("250000.00"),
            stock=0,
            stock_minimo=1,
        )

        hoy = timezone.localdate().isoformat()
        self.client.post(
            reverse("erp_crear", args=["produccion"]),
            {
                "producto": str(pan.pk),
                "cantidad": 20,
                "fecha": hoy,
                "observaciones": "Orden turno mañana",
            },
        )
        orden = OrdenProduccion.objects.get(empresa=self.empresa, producto=pan)
        url_detalle = reverse("erp_detalle", args=["produccion", orden.pk])

        # No permite agregar el producto terminado como su propio insumo
        self.client.post(
            url_detalle,
            {"accion": "agregar", "producto": str(pan.pk), "cantidad": 2},
        )
        self.assertEqual(orden.insumos.count(), 0)

        # Agregar insumo Harina (3 unidades) y producir
        self.client.post(
            url_detalle,
            {"accion": "agregar", "producto": str(harina.pk), "cantidad": 3},
        )
        self.assertEqual(orden.insumos.count(), 1)

        self.client.post(url_detalle, {"accion": "producir"})
        orden.refresh_from_db()
        self.assertTrue(orden.completada)

        harina.refresh_from_db()
        pan.refresh_from_db()
        self.assertEqual(harina.stock, 7)
        self.assertEqual(pan.stock, 20)
        self.assertTrue(
            MovimientoInventario.objects.filter(
                empresa=self.empresa, producto=harina, tipo="salida", cantidad=3
            ).exists()
        )
        self.assertTrue(
            MovimientoInventario.objects.filter(
                empresa=self.empresa, producto=pan, tipo="entrada", cantidad=20
            ).exists()
        )

    def test_agenda_servicios_cruce_de_horarios_y_atencion_a_cartera(self):
        profesional = Empleado.objects.create(
            empresa=self.empresa,
            nombre="Dr. Andrés",
            documento="79000222",
            cargo="Especialista",
            salario_base=Decimal("3000000.00"),
            activo=True,
        )
        servicio = Servicio.objects.create(
            empresa=self.empresa,
            nombre="Consulta Especializada",
            precio=Decimal("100000.00"),
            iva_porcentaje=Decimal("19.00"),
            duracion_minutos=60,
            activo=True,
        )
        cliente = Cliente.objects.create(
            empresa=self.empresa,
            tipo_documento="CC",
            numero_documento="80900100",
            nombre="Paciente Uno",
        )

        inicio_base = (timezone.localtime() + timedelta(days=1)).replace(
            hour=10, minute=0, second=0, microsecond=0
        )
        resp_cita1 = self.client.post(
            reverse("erp_crear", args=["agenda"]),
            {
                "cliente": str(cliente.pk),
                "empleado": str(profesional.pk),
                "servicio": str(servicio.pk),
                "inicio": inicio_base.strftime("%Y-%m-%dT%H:%M"),
                "observaciones": "Primera vez",
            },
        )
        cita1 = Cita.objects.get(empresa=self.empresa, cliente=cliente)
        self.assertRedirects(resp_cita1, reverse("erp_detalle", args=["agenda", cita1.pk]))
        self.assertEqual(cita1.total, Decimal("119000.00"))

        # Intentar agendar otra cita que se cruza (10:30 AM, cuando la primera termina a las 11:00 AM)
        inicio_cruzado = inicio_base + timedelta(minutes=30)
        resp_cruzada = self.client.post(
            reverse("erp_crear", args=["agenda"]),
            {
                "cliente": str(cliente.pk),
                "empleado": str(profesional.pk),
                "servicio": str(servicio.pk),
                "inicio": inicio_cruzado.strftime("%Y-%m-%dT%H:%M"),
                "observaciones": "Intento cruce",
            },
        )
        self.assertEqual(resp_cruzada.status_code, 200)
        self.assertEqual(Cita.objects.filter(empresa=self.empresa).count(), 1)

        # Marcar cita como atendida -> genera CuentaCartera por cobrar
        self.client.post(
            reverse("erp_detalle", args=["agenda", cita1.pk]),
            {"accion": "atendida"},
        )
        cita1.refresh_from_db()
        self.assertEqual(cita1.estado, "atendida")
        self.assertIsNotNone(cita1.cartera)
        self.assertEqual(cita1.cartera.tipo, "cobrar")
        self.assertEqual(cita1.cartera.total, Decimal("119000.00"))


class IntegracionesFase10Tests(TestCase):
    """Pruebas de Fase 10: adaptador DIAN, contabilización automática y calculadora de aportes."""

    def setUp(self):
        self.admin, self.empresa = _crear_empresa_con_admin("admin-f10@test.co", "Fase 10 SAS")
        self.client.force_login(self.admin)

        self.cliente = Cliente.objects.create(
            empresa=self.empresa,
            tipo_documento="CC",
            numero_documento="10203040",
            nombre="Cliente DIAN",
        )
        self.producto = Producto.objects.create(
            empresa=self.empresa,
            codigo="DIAN-1",
            nombre="Servicio Cloud",
            precio=Decimal("100000.00"),
            iva_porcentaje=Decimal("19.00"),
            stock=20,
            stock_minimo=2,
        )

    def test_emision_factura_electronica_dian_simulada_idempotente_y_rechazo_proveedor(self):
        from .facturacion_electronica import (
            ProveedorFacturacionElectronica,
            ResultadoEmisionDian,
            emitir_factura_electronica,
        )
        from .models import Factura

        factura = services.crear_factura(
            empresa=self.empresa,
            usuario=self.admin,
            cliente=self.cliente,
            items=[{"producto": self.producto, "cantidad": 2}],
        )
        self.assertEqual(factura.estado_dian, Factura.EstadoDian.NO_APLICA)

        # Proveedor que rechaza primero
        class ProveedorRechazo(ProveedorFacturacionElectronica):
            def emitir_factura(self, fac):
                return ResultadoEmisionDian(aceptada=False, mensaje="NIT del adquiriente inválido en RUT")

        emitir_factura_electronica(factura=factura, proveedor=ProveedorRechazo())
        factura.refresh_from_db()
        self.assertEqual(factura.estado_dian, Factura.EstadoDian.RECHAZADA)
        self.assertIn("RUT", factura.dian_respuesta)

        # Emitir desde la vista con el simulador por defecto -> pasa a ACEPTADA con CUFE SHA-384 (96 hex chars)
        resp = self.client.post(reverse("facturas_emitir_dian", args=[factura.pk]), follow=True)
        self.assertEqual(resp.status_code, 200)
        factura.refresh_from_db()
        self.assertEqual(factura.estado_dian, Factura.EstadoDian.ACEPTADA)
        self.assertEqual(len(factura.cufe), 96)
        self.assertIsNotNone(factura.dian_emitida_en)

        # Idempotencia: volver a llamar no cambia el CUFE ni llama al proveedor
        cufe_original = factura.cufe
        emitir_factura_electronica(factura=factura, proveedor=ProveedorRechazo())
        factura.refresh_from_db()
        self.assertEqual(factura.estado_dian, Factura.EstadoDian.ACEPTADA)
        self.assertEqual(factura.cufe, cufe_original)

    def test_contabilizacion_automatica_de_factura_compra_tesoreria_y_nomina(self):
        import uuid
        from .contabilidad_automatica import (
            calcular_aportes_nomina_colombia,
            contabilizar_compra,
            contabilizar_factura,
            contabilizar_movimiento_tesoreria,
            contabilizar_nomina,
        )
        from .erp_services import aprobar_nomina, recibir_compra, registrar_tesoreria
        from .models import Compra, CuentaTesoreria, LineaCompra, Proveedor

        # 1. Factura -> Asiento confirmado e idempotente
        factura = services.crear_factura(
            empresa=self.empresa,
            usuario=self.admin,
            cliente=self.cliente,
            items=[{"producto": self.producto, "cantidad": 1}],
        )
        resp_fac_cont = self.client.post(reverse("facturas_contabilizar", args=[factura.pk]))
        self.assertRedirects(resp_fac_cont, reverse("facturas_detalle", args=[factura.pk]))
        asiento_fac = AsientoContable.objects.get(empresa=self.empresa, referencia=f"FACT-{factura.numero}")
        self.assertTrue(asiento_fac.confirmado)
        self.assertEqual(asiento_fac.pk, contabilizar_factura(factura=factura, usuario=self.admin).pk)

        # Si se anula una factura contabilizada, genera el asiento de reversión automático ANUL-FACT-{numero}
        services.anular_factura(factura=factura, usuario=self.admin)
        asiento_anul = AsientoContable.objects.get(empresa=self.empresa, referencia=f"ANUL-FACT-{factura.numero}")
        self.assertTrue(asiento_anul.confirmado)

        # 2. Compra recibida -> Asiento confirmado
        prov = Proveedor.objects.create(empresa=self.empresa, documento="900888777", nombre="Prov Contable")
        compra = Compra.objects.create(
            empresa=self.empresa,
            proveedor=prov,
            referencia="FC-901",
            fecha=timezone.localdate(),
            vencimiento=timezone.localdate(),
        )
        LineaCompra.objects.create(
            empresa=self.empresa,
            compra=compra,
            producto=self.producto,
            cantidad=2,
            costo=Decimal("50000.00"),
            iva_porcentaje=Decimal("19.00"),
        )
        compra = recibir_compra(empresa=self.empresa, pk=compra.pk, usuario=self.admin)
        asiento_comp = contabilizar_compra(compra=compra, usuario=self.admin)
        self.assertTrue(asiento_comp.confirmado)

        # 3. Movimiento de tesorería -> Asiento confirmado desde la vista ERP
        banco = CuentaTesoreria.objects.create(
            empresa=self.empresa, nombre="Banco Principal", tipo="banco", activa=True
        )
        mov = registrar_tesoreria(
            empresa=self.empresa,
            usuario=self.admin,
            cuenta=banco,
            monto=Decimal("119000.00"),
            tipo="ingreso",
            concepto="Recaudo cliente",
            fecha=timezone.localdate(),
            operacion=uuid.uuid4(),
        )
        resp_tes_cont = self.client.post(
            reverse("erp_detalle", args=["tesoreria", mov.pk]),
            {"accion": "contabilizar"},
        )
        self.assertRedirects(resp_tes_cont, reverse("erp_detalle", args=["tesoreria", mov.pk]))
        asiento_tes = AsientoContable.objects.get(empresa=self.empresa, referencia=f"TES-{mov.operacion}")
        self.assertTrue(asiento_tes.confirmado)

        # 4. Nómina aprobada y calculadora de aportes de ley
        aportes = calcular_aportes_nomina_colombia(
            salario_base=Decimal("2000000.00"),
            auxilio_transporte=Decimal("162000.00"),
        )
        self.assertEqual(aportes["salud_empleado"], Decimal("80000.00"))
        self.assertEqual(aportes["pension_empleado"], Decimal("80000.00"))
        self.assertEqual(aportes["deducciones_empleado"], Decimal("160000.00"))
        self.assertEqual(aportes["neto_estimado"], Decimal("2002000.00"))
        self.assertEqual(aportes["total_seguridad_social_empleador"], Decimal("420400.00"))
        self.assertEqual(aportes["total_parafiscales"], Decimal("180000.00"))
        self.assertGreater(aportes["costo_total_empleador"], Decimal("3000000.00"))

        emp = Empleado.objects.create(
            empresa=self.empresa,
            nombre="Carlos Nómina",
            documento="10305060",
            cargo="Contador",
            salario_base=Decimal("2000000.00"),
            activo=True,
        )
        hoy = timezone.localdate()
        nom = LiquidacionNomina.objects.create(
            empresa=self.empresa,
            empleado=emp,
            desde=hoy,
            hasta=hoy,
            base=Decimal("2000000.00"),
            adicionales=Decimal("162000.00"),
            deducciones=Decimal("0.00"),
            neto=Decimal("2162000.00"),
        )
        # Aplicar deducciones de ley desde la vista antes de aprobar
        resp_calc = self.client.post(
            reverse("erp_detalle", args=["nomina", nom.pk]),
            {"accion": "calcular_aportes"},
        )
        self.assertRedirects(resp_calc, reverse("erp_detalle", args=["nomina", nom.pk]))
        nom.refresh_from_db()
        self.assertEqual(nom.deducciones, Decimal("160000.00"))
        self.assertEqual(nom.neto, Decimal("2002000.00"))

        nom = aprobar_nomina(empresa=self.empresa, pk=nom.pk)
        # Generar comprobante contable directamente desde la vista de detalle ERP
        resp_cont = self.client.post(
            reverse("erp_detalle", args=["nomina", nom.pk]),
            {"accion": "contabilizar"},
        )
        self.assertRedirects(resp_cont, reverse("erp_detalle", args=["nomina", nom.pk]))
        asiento_nom = AsientoContable.objects.get(empresa=self.empresa, referencia=f"NOM-{nom.pk}")
        self.assertTrue(asiento_nom.confirmado)

    def test_fase_a_contabilizacion_recaudo_wompi_y_pos_deja_saldo_1305_en_cero(self):
        from .contabilidad_automatica import (
            contabilizar_factura,
            saldo_contable_cliente_factura,
        )

        # 1. Factura causada -> saldo en 1305 igual al total; luego pago Wompi aprobado -> saldo 1305 en 0
        factura_wompi = services.crear_factura(
            empresa=self.empresa,
            usuario=self.admin,
            cliente=self.cliente,
            items=[{"producto": self.producto, "cantidad": 1}],
        )
        contabilizar_factura(factura=factura_wompi, usuario=self.admin)
        self.assertEqual(saldo_contable_cliente_factura(factura=factura_wompi), factura_wompi.total)

        intento = pagos.crear_pago(factura=factura_wompi)
        pagos.aplicar_transaccion(
            {
                "id": "wompi-tx-fase-a",
                "reference": intento.referencia,
                "status": "APPROVED",
                "amount_in_cents": intento.monto_centavos,
                "currency": "COP",
                "payment_method_type": "CARD",
            }
        )
        asiento_rec_wompi = AsientoContable.objects.get(
            empresa=self.empresa,
            referencia=f"REC-FACT-{factura_wompi.numero}-{intento.referencia}"[:100],
        )
        self.assertTrue(asiento_rec_wompi.confirmado)
        self.assertEqual(saldo_contable_cliente_factura(factura=factura_wompi), Decimal("0.00"))

        # 2. Venta en POS -> al contabilizar desde la vista de factura genera FACT-n y REC-FACT-n-POS (saldo 1305 = 0)
        turno = caja.abrir_turno(empresa=self.empresa, usuario=self.admin, base="50000")
        factura_pos = caja.registrar_venta(
            turno=turno,
            usuario=self.admin,
            items=[{"producto": self.producto, "cantidad": 1}],
            pagos=[{"metodo": "efectivo", "recibido": "120000"}],
        )
        resp = self.client.post(reverse("facturas_contabilizar", args=[factura_pos.pk]))
        self.assertRedirects(resp, reverse("facturas_detalle", args=[factura_pos.pk]))
        self.assertTrue(
            AsientoContable.objects.filter(
                empresa=self.empresa, referencia=f"FACT-{factura_pos.numero}", confirmado=True
            ).exists()
        )
        self.assertTrue(
            AsientoContable.objects.filter(
                empresa=self.empresa, referencia=f"REC-FACT-{factura_pos.numero}-POS", confirmado=True
            ).exists()
        )
        self.assertEqual(saldo_contable_cliente_factura(factura=factura_pos), Decimal("0.00"))

    def test_fase_c_anular_factura_aceptada_por_dian_genera_nota_credito_cude_y_reversion_contable(self):
        from .contabilidad_automatica import (
            contabilizar_factura,
            saldo_contable_cliente_factura,
        )
        from .facturacion_electronica import (
            emitir_factura_electronica,
            emitir_nota_credito_electronica,
        )

        factura = services.crear_factura(
            empresa=self.empresa,
            usuario=self.admin,
            cliente=self.cliente,
            items=[{"producto": self.producto, "cantidad": 2}],
        )
        factura = emitir_factura_electronica(factura=factura)
        self.assertEqual(len(factura.cufe), 96)
        contabilizar_factura(factura=factura, usuario=self.admin)

        # Al anular la factura aceptada por DIAN, emite automáticamente la Nota Crédito Electrónica (CUDE) y revierte el asiento
        factura = services.anular_factura(factura=factura, usuario=self.admin)
        self.assertEqual(factura.estado, Factura.Estado.ANULADA)
        self.assertEqual(len(factura.cude_nota_credito), 96)
        self.assertNotEqual(factura.cude_nota_credito, factura.cufe)

        # Idempotencia de emitir_nota_credito_electronica
        cude_original = factura.cude_nota_credito
        self.assertEqual(emitir_nota_credito_electronica(factura=factura).cude_nota_credito, cude_original)

        # Asiento de reversión confirmado y saldo en cuenta 1305 igual a 0
        self.assertTrue(
            AsientoContable.objects.filter(
                empresa=self.empresa, referencia=f"ANUL-FACT-{factura.numero}", confirmado=True
            ).exists()
        )
        self.assertEqual(saldo_contable_cliente_factura(factura=factura), Decimal("0.00"))

        # La vista de detalle muestra el CUDE de la Nota Crédito
        resp_detalle = self.client.get(reverse("facturas_detalle", args=[factura.pk]))
        self.assertContains(resp_detalle, "Nota Crédito (CUDE):")
        self.assertContains(resp_detalle, factura.cude_nota_credito[:24])




