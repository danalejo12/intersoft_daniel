"""Punto de venta: caja, ventas de mostrador con varios medios de pago, arqueo y ticket."""
import json
import threading
import uuid
from decimal import Decimal

from django.db import IntegrityError, connections, transaction
from django.test import TestCase, TransactionTestCase
from django.urls import reverse

from . import caja, services
from .models import Cliente, Empresa, Factura, Membresia, PagoCaja, Permiso, Producto, Rol, TurnoCaja, Usuario


def crear_admin(empresa, correo):
    usuario = Usuario.objects.create_user(username=correo, email=correo, password="x", first_name="Caja")
    rol = Rol.objects.create(empresa=empresa, nombre=f"Admin {correo}", es_admin=True)
    Membresia.objects.create(usuario=usuario, empresa=empresa, rol=rol)
    return usuario


class PosBase(TestCase):
    def setUp(self):
        self.empresa = Empresa.objects.create(
            nombre="Tienda Centro", nit="900555", slug="tienda-centro", direccion="Calle 5 # 6-7", telefono="6014445566"
        )
        self.cajero = crear_admin(self.empresa, "caja@tienda.co")
        self.arroz = Producto.objects.create(
            empresa=self.empresa, codigo="ARZ-1", nombre="Arroz", precio=Decimal("1000"), iva_porcentaje=Decimal("19"), stock=10
        )
        self.client.force_login(self.cajero)

    def abrir(self, base="50000"):
        return self.client.post(reverse("pos_abrir"), {"base": base})

    def vender(self, pagos, lineas=None, cliente=None, operacion=None):
        lineas = lineas if lineas is not None else [{"producto": str(self.arroz.pk), "cantidad": 2}]
        cuerpo = {"lineas": lineas, "pagos": pagos, "cliente": cliente}
        if operacion is not None:
            cuerpo["operacion"] = operacion
        return self.client.post(reverse("pos_vender"), data=json.dumps(cuerpo), content_type="application/json")

    def stock(self, producto=None):
        return Producto.objects.get(pk=(producto or self.arroz).pk).stock

    def nada_creado(self):
        self.assertFalse(Factura.objects.exists())
        self.assertFalse(PagoCaja.objects.exists())
        self.assertEqual(self.stock(), 10)


class AbrirCajaTests(PosBase):
    def test_sin_caja_pide_abrirla(self):
        respuesta = self.client.get(reverse("pos"))
        self.assertTemplateUsed(respuesta, "core/pos/abrir.html")

    def test_abrir_caja_y_entrar_al_punto_de_venta(self):
        self.abrir("50000")
        turno = TurnoCaja.objects.get()
        self.assertEqual((turno.cajero, turno.base_inicial, turno.abierto), (self.cajero, Decimal("50000"), True))
        self.assertTemplateUsed(self.client.get(reverse("pos")), "core/pos/pos.html")

    def test_no_se_abren_dos_cajas(self):
        self.abrir()
        self.abrir()
        self.assertEqual(TurnoCaja.objects.count(), 1)
        with self.assertRaises(IntegrityError), transaction.atomic():
            TurnoCaja.objects.create(empresa=self.empresa, cajero=self.cajero)

    def test_base_invalida_no_abre(self):
        for base in ("-5", "abc", "1.234"):
            with self.subTest(base=base):
                self.abrir(base)
                self.assertFalse(TurnoCaja.objects.exists())

    def test_sin_caja_no_se_puede_vender(self):
        self.assertEqual(self.vender([{"metodo": "efectivo", "recibido": "5000"}]).status_code, 409)
        self.nada_creado()


class VentaTests(PosBase):
    def setUp(self):
        super().setUp()
        self.abrir("50000")
        self.turno = TurnoCaja.objects.get()

    def test_efectivo_con_cambio(self):
        datos = self.vender([{"metodo": "efectivo", "recibido": "5000"}]).json()
        self.assertTrue(datos["ok"])
        self.assertEqual((datos["total"], datos["cambio"]), ("2380.00", "2620.00"))
        factura = Factura.objects.get()
        self.assertEqual(factura.turno, self.turno)
        self.assertEqual(factura.cliente.numero_documento, caja.DOCUMENTO_CONSUMIDOR_FINAL)
        self.assertTrue(factura.esta_pagada)
        pago = PagoCaja.objects.get()
        self.assertEqual((pago.metodo, pago.monto, pago.recibido, pago.cambio), ("efectivo", Decimal("2380"), Decimal("5000"), Decimal("2620")))
        self.assertEqual(self.stock(), 8)

    def test_pago_mixto(self):
        datos = self.vender([
            {"metodo": "tarjeta", "monto": "1000", "referencia": "AUT-55"},
            {"metodo": "transferencia", "monto": "380", "referencia": "NEQUI-9"},
            {"metodo": "efectivo", "recibido": "1000"},
        ]).json()
        self.assertTrue(datos["ok"])
        pagos = {p.metodo: p for p in PagoCaja.objects.all()}
        self.assertEqual(pagos["tarjeta"].monto, Decimal("1000"))
        self.assertEqual(pagos["tarjeta"].referencia, "AUT-55")
        self.assertEqual(pagos["transferencia"].monto, Decimal("380"))
        self.assertEqual((pagos["efectivo"].monto, pagos["efectivo"].cambio), (Decimal("1000"), Decimal("0")))
        self.assertEqual(sum(p.monto for p in pagos.values()), Factura.objects.get().total)

    def test_solo_tarjeta_por_el_total(self):
        self.assertTrue(self.vender([{"metodo": "tarjeta", "monto": "2380"}]).json()["ok"])
        self.assertEqual(PagoCaja.objects.get().metodo, "tarjeta")

    def test_pago_insuficiente_no_crea_nada(self):
        respuesta = self.vender([{"metodo": "efectivo", "recibido": "1000"}])
        self.assertEqual(respuesta.status_code, 409)
        self.nada_creado()

    def test_tarjeta_no_puede_superar_el_total(self):
        respuesta = self.vender([{"metodo": "tarjeta", "monto": "3000"}])
        self.assertIn("solo se da en efectivo", respuesta.json()["error"])
        self.nada_creado()

    def test_efectivo_de_mas_cuando_ya_esta_cubierto(self):
        respuesta = self.vender([{"metodo": "tarjeta", "monto": "2380"}, {"metodo": "efectivo", "recibido": "100"}])
        self.assertEqual(respuesta.status_code, 409)
        self.nada_creado()

    def test_el_precio_del_navegador_se_ignora(self):
        lineas = [{"producto": str(self.arroz.pk), "cantidad": 2, "precio": "1"}]
        self.assertEqual(self.vender([{"metodo": "efectivo", "recibido": "2"}], lineas=lineas).status_code, 409)
        self.assertTrue(self.vender([{"metodo": "efectivo", "recibido": "2380"}], lineas=lineas).json()["ok"])
        self.assertEqual(Factura.objects.get().total, Decimal("2380"))

    def test_lineas_repetidas_se_suman(self):
        linea = {"producto": str(self.arroz.pk), "cantidad": 1}
        self.vender([{"metodo": "efectivo", "recibido": "2380"}], lineas=[linea, linea])
        self.assertEqual(Factura.objects.get().detalles.get().cantidad, 2)

    def test_stock_insuficiente(self):
        lineas = [{"producto": str(self.arroz.pk), "cantidad": 11}]
        respuesta = self.vender([{"metodo": "efectivo", "recibido": "99999"}], lineas=lineas)
        self.assertEqual(respuesta.status_code, 409)
        self.assertIn("Stock insuficiente", respuesta.json()["error"])
        self.nada_creado()

    def test_producto_de_otra_empresa(self):
        otra = Empresa.objects.create(nombre="Otra", nit="1", slug="otra")
        ajeno = Producto.objects.create(empresa=otra, codigo="X", nombre="Ajeno", precio=Decimal("10"), stock=5)
        respuesta = self.vender([{"metodo": "efectivo", "recibido": "100"}], lineas=[{"producto": str(ajeno.pk), "cantidad": 1}])
        self.assertEqual(respuesta.status_code, 400)
        self.assertEqual(Producto.objects.get(pk=ajeno.pk).stock, 5)
        self.nada_creado()

    def test_datos_invalidos(self):
        for cuerpo in ("no es json", json.dumps({"lineas": "x"}), json.dumps({"lineas": [{"producto": "no-uuid", "cantidad": 1}], "pagos": []})):
            with self.subTest(cuerpo=cuerpo):
                respuesta = self.client.post(reverse("pos_vender"), data=cuerpo, content_type="application/json")
                self.assertEqual(respuesta.status_code, 400)
        self.assertEqual(self.vender([{"metodo": "efectivo", "recibido": "5000"}], lineas=[{"producto": str(self.arroz.pk), "cantidad": 0}]).status_code, 400)
        self.assertEqual(self.vender([{"metodo": "cheque", "monto": "2380"}]).status_code, 409)
        self.nada_creado()

    def test_redondeo_de_empate(self):
        galleta = Producto.objects.create(empresa=self.empresa, codigo="G", nombre="Galleta", precio=Decimal("0.50"), iva_porcentaje=Decimal("1"), stock=5)
        datos = self.vender([{"metodo": "efectivo", "recibido": "0.51"}], lineas=[{"producto": str(galleta.pk), "cantidad": 1}]).json()
        self.assertEqual(datos["total"], "0.51")

    def test_con_cliente_registrado(self):
        cliente = Cliente.objects.create(empresa=self.empresa, tipo_documento="CC", numero_documento="77", nombre="Marta")
        self.vender([{"metodo": "efectivo", "recibido": "2380"}], cliente=str(cliente.pk))
        self.assertEqual(Factura.objects.get().cliente, cliente)

    def test_cliente_de_otra_empresa(self):
        otra = Empresa.objects.create(nombre="Otra", nit="1", slug="otra")
        ajeno = Cliente.objects.create(empresa=otra, tipo_documento="CC", numero_documento="77", nombre="Ajeno")
        self.assertEqual(self.vender([{"metodo": "efectivo", "recibido": "2380"}], cliente=str(ajeno.pk)).status_code, 400)
        self.nada_creado()

    def test_consumidor_final_se_reutiliza(self):
        self.vender([{"metodo": "efectivo", "recibido": "2380"}])
        self.vender([{"metodo": "efectivo", "recibido": "2380"}])
        self.assertEqual(Cliente.objects.filter(numero_documento=caja.DOCUMENTO_CONSUMIDOR_FINAL).count(), 1)

    def test_otro_cajero_no_vende_en_esta_caja(self):
        otro = crear_admin(self.empresa, "otro@tienda.co")
        with self.assertRaises(caja.OperacionCaja):
            caja.registrar_venta(turno=self.turno, usuario=otro, items=[{"producto": self.arroz, "cantidad": 1}],
                                 pagos=[{"metodo": "efectivo", "recibido": "5000"}])
        self.nada_creado()

    def test_la_venta_aparece_pagada_y_no_se_anula(self):
        self.vender([{"metodo": "efectivo", "recibido": "2380"}])
        factura = Factura.objects.get()
        self.assertTrue(self.client.get(reverse("facturas_lista")).context["facturas"][0].pagada)
        self.client.post(reverse("facturas_anular", args=[factura.pk]))
        factura.refresh_from_db()
        self.assertEqual(factura.estado, Factura.Estado.EMITIDA)
        self.assertContains(self.client.get(reverse("facturas_detalle", args=[factura.pk])), "Pagos en caja")

    def test_rechaza_cantidades_no_enteras_booleanos_y_acumuladas_fuera_de_rango(self):
        for cantidad_invalida in (True, False, 1.5, 2.0, "1.5", "2,5", "abc", "", None, -1, 10000):
            with self.subTest(cantidad=cantidad_invalida):
                respuesta = self.vender(
                    [{"metodo": "efectivo", "recibido": "5000"}],
                    lineas=[{"producto": str(self.arroz.pk), "cantidad": cantidad_invalida}],
                )
                self.assertEqual(respuesta.status_code, 400)
        # Dos líneas que individualmente son <= 9999 pero sumadas superan 9999
        respuesta_acumulada = self.vender(
            [{"metodo": "efectivo", "recibido": "5000"}],
            lineas=[
                {"producto": str(self.arroz.pk), "cantidad": 5000},
                {"producto": str(self.arroz.pk), "cantidad": 5000},
            ],
        )
        self.assertEqual(respuesta_acumulada.status_code, 400)
        self.assertIn("entre 1 y 9.999", respuesta_acumulada.json()["error"])
        self.nada_creado()

    def test_crear_factura_acumula_lineas_repetidas_y_valida_stock_total(self):
        cliente = caja.consumidor_final(self.empresa)
        with self.assertRaises(services.StockInsuficiente):
            services.crear_factura(
                empresa=self.empresa,
                usuario=self.cajero,
                cliente=cliente,
                items=[
                    {"producto": self.arroz, "cantidad": 6},
                    {"producto": self.arroz, "cantidad": 6},
                ],
            )
        self.nada_creado()

        factura = services.crear_factura(
            empresa=self.empresa,
            usuario=self.cajero,
            cliente=cliente,
            items=[
                {"producto": self.arroz, "cantidad": 3},
                {"producto": self.arroz, "cantidad": 2},
            ],
        )
        self.assertEqual(factura.detalles.get().cantidad, 5)
        self.assertEqual(self.stock(), 5)

    def test_idempotencia_en_venta_pos(self):
        op = str(uuid.uuid4())
        primera = self.vender([{"metodo": "efectivo", "recibido": "5000"}], operacion=op).json()
        segunda = self.vender([{"metodo": "efectivo", "recibido": "5000"}], operacion=op).json()
        self.assertTrue(primera["ok"])
        self.assertEqual(primera, segunda)
        self.assertEqual(Factura.objects.count(), 1)
        self.assertEqual(PagoCaja.objects.count(), 1)
        self.assertEqual(self.stock(), 8)

        # Reutilizar la misma clave con datos distintos devuelve conflicto
        conflicto = self.vender(
            [{"metodo": "efectivo", "recibido": "5000"}],
            lineas=[{"producto": str(self.arroz.pk), "cantidad": 1}],
            operacion=op,
        )
        self.assertEqual(conflicto.status_code, 409)
        self.assertEqual(Factura.objects.count(), 1)

        # Clave de operación con formato inválido devuelve 400
        for op_mala in ("no-es-uuid", 123, True):
            with self.subTest(operacion=op_mala):
                self.assertEqual(
                    self.vender([{"metodo": "efectivo", "recibido": "5000"}], operacion=op_mala).status_code,
                    400,
                )


class CierreTests(PosBase):
    def setUp(self):
        super().setUp()
        self.abrir("50000")
        self.vender([{"metodo": "efectivo", "recibido": "5000"}])  # entra 2.380 en efectivo
        self.vender([{"metodo": "tarjeta", "monto": "2380"}])     # no suma al efectivo
        self.turno = TurnoCaja.objects.get()

    def cerrar(self, contado):
        return self.client.post(reverse("pos_cerrar"), {"contado": contado, "observaciones": "Faltó una moneda"})

    def test_el_formulario_no_muestra_lo_esperado(self):
        respuesta = self.client.get(reverse("pos_cerrar"))
        self.assertContains(respuesta, "2 ventas")
        self.assertNotContains(respuesta, "52.380")

    def test_arqueo_con_faltante(self):
        respuesta = self.cerrar("52000")
        self.assertRedirects(respuesta, reverse("pos_turno", args=[self.turno.pk]))
        self.turno.refresh_from_db()
        self.assertFalse(self.turno.abierto)
        self.assertEqual(
            (self.turno.efectivo_esperado, self.turno.efectivo_contado, self.turno.diferencia),
            (Decimal("52380"), Decimal("52000"), Decimal("-380")),
        )
        detalle = self.client.get(reverse("pos_turno", args=[self.turno.pk]))
        self.assertContains(detalle, "Falta dinero")
        self.assertContains(detalle, "Faltó una moneda")

    def test_arqueo_que_cuadra(self):
        self.cerrar("52380")
        self.turno.refresh_from_db()
        self.assertEqual(self.turno.diferencia, Decimal("0"))

    def test_resumen_por_medio_de_pago(self):
        resumen = caja.resumen_turno(self.turno)
        self.assertEqual(resumen["ventas"], 2)
        self.assertEqual(dict(resumen["por_metodo"])["Efectivo"], Decimal("2380"))
        self.assertEqual(dict(resumen["por_metodo"])["Tarjeta (datáfono)"], Decimal("2380"))

    def test_despues_de_cerrar_no_se_vende_y_se_puede_abrir_otra(self):
        self.cerrar("52380")
        self.assertEqual(self.vender([{"metodo": "efectivo", "recibido": "5000"}]).status_code, 409)
        self.assertTemplateUsed(self.client.get(reverse("pos")), "core/pos/abrir.html")
        self.abrir("10000")
        self.assertEqual(TurnoCaja.objects.filter(cerrado_en__isnull=True).count(), 1)

    def test_no_se_cierra_dos_veces_ni_una_caja_ajena(self):
        otro = crear_admin(self.empresa, "otro@tienda.co")
        with self.assertRaises(caja.OperacionCaja):
            caja.cerrar_turno(turno=self.turno, usuario=otro, contado="1")
        caja.cerrar_turno(turno=self.turno, usuario=self.cajero, contado="52380")
        with self.assertRaises(caja.OperacionCaja):
            caja.cerrar_turno(turno=self.turno, usuario=self.cajero, contado="52380")


class BusquedaYTicketTests(PosBase):
    def setUp(self):
        super().setUp()
        self.otra = Empresa.objects.create(nombre="Otra", nit="1", slug="otra")
        Producto.objects.create(empresa=self.otra, codigo="ARZ-1", nombre="Arroz ajeno", precio=Decimal("1"), stock=5)

    def test_codigo_exacto_sin_distinguir_mayusculas(self):
        datos = self.client.get(reverse("pos_productos"), {"q": "arz-1"}).json()
        self.assertEqual(datos["exacto"]["id"], str(self.arroz.pk))
        self.assertEqual([p["nombre"] for p in datos["productos"]], ["Arroz"])

    def test_busqueda_por_nombre_solo_de_esta_empresa(self):
        nombres = [p["nombre"] for p in self.client.get(reverse("pos_productos"), {"q": "arroz"}).json()["productos"]]
        self.assertEqual(nombres, ["Arroz"])

    def test_productos_inactivos_no_aparecen(self):
        Producto.objects.filter(pk=self.arroz.pk).update(activo=False)
        self.assertEqual(self.client.get(reverse("pos_productos"), {"q": "arroz"}).json()["productos"], [])

    def test_busqueda_de_clientes_sin_consumidor_final(self):
        Cliente.objects.create(empresa=self.empresa, tipo_documento="CC", numero_documento="77", nombre="Marta")
        caja.consumidor_final(self.empresa)
        Cliente.objects.create(empresa=self.otra, tipo_documento="CC", numero_documento="78", nombre="Marta ajena")
        nombres = [c["nombre"] for c in self.client.get(reverse("pos_clientes"), {"q": "a"}).json()["clientes"]]
        self.assertEqual(nombres, ["Marta"])

    def test_ticket_con_datos_del_negocio_y_cambio(self):
        self.abrir()
        self.vender([{"metodo": "efectivo", "recibido": "5000"}])
        respuesta = self.client.get(reverse("pos_ticket", args=[Factura.objects.get().pk]))
        for texto in ("Tienda Centro", "NIT 900555", "Calle 5 # 6-7", "Arroz", "TOTAL", "$2.380", "Cambio", "$2.620"):
            with self.subTest(texto=texto):
                self.assertContains(respuesta, texto)

    def test_ticket_de_otra_empresa_responde_404(self):
        cajero_ajeno = crear_admin(self.otra, "ajeno@otra.co")
        turno = caja.abrir_turno(empresa=self.otra, usuario=cajero_ajeno, base="0")
        ajeno = Producto.objects.get(empresa=self.otra)
        factura = caja.registrar_venta(turno=turno, usuario=cajero_ajeno, items=[{"producto": ajeno, "cantidad": 1}],
                                       pagos=[{"metodo": "efectivo", "recibido": "2"}])  # $1 + 19 % de IVA = $1,19
        self.assertEqual(self.client.get(reverse("pos_ticket", args=[factura.pk])).status_code, 404)
        self.assertEqual(self.client.get(reverse("pos_turno", args=[turno.pk])).status_code, 404)

    def test_ticket_congela_instantanea_y_consulta_pagos_una_sola_vez(self):
        self.abrir()
        cliente = Cliente.objects.create(
            empresa=self.empresa, tipo_documento="CC", numero_documento="778899", nombre="Marta Original"
        )
        self.vender([{"metodo": "efectivo", "recibido": "5000"}], cliente=str(cliente.pk))
        factura = Factura.objects.get()

        # Aunque luego se editen producto, cliente y empresa, la reimpresión conserva los datos originales
        Producto.objects.filter(pk=self.arroz.pk).update(nombre="Arroz Modificado")
        Cliente.objects.filter(pk=cliente.pk).update(nombre="Marta Editada", numero_documento="000000")
        Empresa.objects.filter(pk=self.empresa.pk).update(
            nombre="Tienda Nueva", direccion="Otra Calle", telefono="3000000000"
        )

        from django.db import connection
        from django.test.utils import CaptureQueriesContext

        with CaptureQueriesContext(connection) as consultas:
            respuesta = self.client.get(reverse("pos_ticket", args=[factura.pk]))
        consultas_pagos_caja = [q["sql"] for q in consultas if "pagocaja" in q["sql"].lower()]
        self.assertEqual(len(consultas_pagos_caja), 1)

        for original in ("Tienda Centro", "Calle 5 # 6-7", "6014445566", "Marta Original", "CC 778899", "Arroz"):
            with self.subTest(original=original):
                self.assertContains(respuesta, original)
        for editado in ("Arroz Modificado", "Marta Editada", "Tienda Nueva"):
            with self.subTest(editado=editado):
                self.assertNotContains(respuesta, editado)


class PermisosPosTests(TestCase):
    def test_rol_sin_permiso_de_vender_no_entra(self):
        empresa = Empresa.objects.create(nombre="Una", nit="1", slug="una")
        usuario = Usuario.objects.create_user(username="v@c.co", email="v@c.co", password="x")
        rol = Rol.objects.create(empresa=empresa, nombre="Bodega", es_admin=False)
        perm, _ = Permiso.objects.get_or_create(codigo="inventario.ver", defaults={"descripcion": "Ver inventario"})
        rol.permisos.add(perm)
        Membresia.objects.create(usuario=usuario, empresa=empresa, rol=rol)
        self.client.force_login(usuario)
        for nombre in ("pos", "pos_productos", "pos_cerrar"):
            with self.subTest(ruta=nombre):
                self.assertEqual(self.client.get(reverse(nombre)).status_code, 403)

    def test_rol_con_ventas_crear_o_ventas_ver_puede_abrir_ticket(self):
        empresa = Empresa.objects.create(nombre="Una", nit="1", slug="una")
        admin = crear_admin(empresa, "admin@una.co")
        producto = Producto.objects.create(empresa=empresa, codigo="P1", nombre="Pan", precio=Decimal("1000"), stock=5)
        turno = caja.abrir_turno(empresa=empresa, usuario=admin, base="0")
        factura = caja.registrar_venta(
            turno=turno,
            usuario=admin,
            items=[{"producto": producto, "cantidad": 1}],
            pagos=[{"metodo": "efectivo", "recibido": "2000"}],
        )
        url_ticket = reverse("pos_ticket", args=[factura.pk])

        for codigo, esperado in (("ventas.crear", 200), ("ventas.ver", 200), ("inventario.ver", 403)):
            with self.subTest(permiso=codigo):
                u = Usuario.objects.create_user(username=f"{codigo}@una.co", email=f"{codigo}@una.co", password="x")
                rol = Rol.objects.create(empresa=empresa, nombre=f"Rol {codigo}", es_admin=False)
                perm, _ = Permiso.objects.get_or_create(codigo=codigo, defaults={"descripcion": codigo})
                rol.permisos.add(perm)
                Membresia.objects.create(usuario=u, empresa=empresa, rol=rol)
                self.client.force_login(u)
                self.assertEqual(self.client.get(url_ticket).status_code, esperado)

    def test_sin_sesion_pide_ingresar(self):
        self.assertEqual(self.client.get(reverse("pos")).status_code, 302)


class DineroTests(TestCase):
    def test_convierte_y_valida(self):
        self.assertEqual(caja.dinero("1,5"), Decimal("1.50"))
        self.assertEqual(caja.dinero(" 2380 "), Decimal("2380.00"))
        self.assertEqual(caja.dinero("999999999999.99"), Decimal("999999999999.99"))
        for malo in ("-1", "abc", "1.234", "NaN", "Infinity", "-Infinity", "1000000000000", "1e50", "9" * 40, True, False, None):
            with self.subTest(valor=malo):
                with self.assertRaises(caja.OperacionCaja):
                    caja.dinero(malo)

    def test_formato_de_pesos(self):
        self.assertEqual(caja.pesos(Decimal("1234567.50")), "$1.234.567,50")
        self.assertEqual(caja.pesos(Decimal("2380.00")), "$2.380")


class ConcurrenciaPosTests(TransactionTestCase):
    def test_reintento_concurrente_con_misma_operacion_crea_una_sola_venta(self):
        empresa = Empresa.objects.create(nombre="Tienda Concurrencia", nit="900999", slug="tienda-concurrencia")
        cajero = crear_admin(empresa, "cajero@concurrencia.co")
        producto = Producto.objects.create(
            empresa=empresa, codigo="C-1", nombre="Café", precio=Decimal("1000"), iva_porcentaje=Decimal("19"), stock=10
        )
        turno = caja.abrir_turno(empresa=empresa, usuario=cajero, base="10000")
        operacion = uuid.uuid4()
        barrera = threading.Barrier(2)
        resultados = []
        errores = []

        def intentar_venta():
            try:
                barrera.wait(timeout=5)
                f = caja.registrar_venta(
                    turno=turno,
                    usuario=cajero,
                    items=[{"producto": producto, "cantidad": 2}],
                    pagos=[{"metodo": "efectivo", "recibido": "5000"}],
                    operacion=operacion,
                )
                resultados.append(f.pk)
            except Exception as exc:  # pragma: no cover
                errores.append(exc)
            finally:
                connections.close_all()

        hilos = [threading.Thread(target=intentar_venta) for _ in range(2)]
        for h in hilos:
            h.start()
        for h in hilos:
            h.join()

        self.assertEqual(errores, [])
        self.assertEqual(len(resultados), 2)
        self.assertEqual(resultados[0], resultados[1])
        self.assertEqual(Factura.objects.filter(empresa=empresa).count(), 1)
        self.assertEqual(PagoCaja.objects.filter(empresa=empresa).count(), 1)
        producto.refresh_from_db()
        self.assertEqual(producto.stock, 8)
