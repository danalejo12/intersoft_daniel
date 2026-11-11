from decimal import Decimal

from django.contrib.auth import get_user_model
from django.core.management import call_command
from django.test import TestCase
from django.urls import reverse

from core.models import Cliente, Empresa, Factura, Membresia, Permiso, Producto, Rol
from core.negocios import registrar_negocio
from core.permisos import CATALOGO_PERMISOS, ROLES_BASE

User = get_user_model()


def _crear_dueno_y_negocio(email, nombre_negocio, nombre_dueno="Admin", nit=None):
    usuario = User.objects.create_user(
        username=email,
        email=email,
        password="PasswordSegura123!",
        first_name=nombre_dueno,
    )
    datos = {"nombre": nombre_negocio, "nit": (nit or f"NIT-{email}")[:20]}
    empresa = registrar_negocio(
        usuario=usuario,
        datos=datos,
    )
    return usuario, empresa


class CatalogoYRolesBaseTests(TestCase):
    def test_registrar_negocio_crea_admin_y_roles_base_con_permisos(self):
        dueno, empresa = _crear_dueno_y_negocio(
            email="ana@ferreteria.co",
            nombre_negocio="Ferretería Central",
            nombre_dueno="Ana Gómez",
        )
        roles = {rol.nombre: rol for rol in Rol.objects.filter(empresa=empresa)}
        self.assertIn("Administrador", roles)
        self.assertTrue(roles["Administrador"].es_admin)

        for plantilla in ROLES_BASE:
            self.assertIn(plantilla["nombre"], roles)
            rol = roles[plantilla["nombre"]]
            self.assertFalse(rol.es_admin)
            codigos = set(rol.permisos.values_list("codigo", flat=True))
            self.assertEqual(codigos, set(plantilla["permisos"]))

        membresia_dueno = Membresia.objects.get(usuario=dueno, empresa=empresa)
        self.assertEqual(membresia_dueno.rol, roles["Administrador"])
        self.assertTrue(membresia_dueno.tiene_permiso("equipo.gestionar"))

    def test_comando_sincronizar_permisos_es_idempotente_y_completa_empresas_existentes(self):
        empresa = Empresa.objects.create(nombre="Empresa Sin Roles Base", slug="sin-roles-base")
        call_command("sincronizar_permisos")
        call_command("sincronizar_permisos")

        codigos_esperados = {codigo for codigo, _ in CATALOGO_PERMISOS}
        codigos_db = set(Permiso.objects.values_list("codigo", flat=True))
        self.assertTrue(codigos_esperados.issubset(codigos_db))

        roles_empresa = set(Rol.objects.filter(empresa=empresa).values_list("nombre", flat=True))
        for plantilla in ROLES_BASE:
            self.assertIn(plantilla["nombre"], roles_empresa)


class GestionEquipoYRolesTests(TestCase):
    def setUp(self):
        self.admin_user, self.empresa = _crear_dueno_y_negocio(
            email="carlos@andina.co",
            nombre_negocio="Comercial Andina",
            nombre_dueno="Carlos Admin",
        )
        self.otro_admin, self.otra_empresa = _crear_dueno_y_negocio(
            email="laura@vecina.co",
            nombre_negocio="Tienda Vecina",
            nombre_dueno="Laura Vecina",
        )
        self.client.force_login(self.admin_user)

    def test_crear_editar_y_eliminar_rol_personalizado(self):
        perm_ver = Permiso.objects.get(codigo="inventario.ver")
        perm_crear = Permiso.objects.get(codigo="ventas.crear")

        resp = self.client.post(
            reverse("equipo_rol_crear"),
            {
                "nombre": "Supervisor Piso",
                "descripcion": "Supervisa mostrador",
                "es_admin": False,
                "permisos": [perm_ver.pk, perm_crear.pk],
            },
        )
        self.assertRedirects(resp, reverse("equipo_lista"))
        rol = Rol.objects.get(empresa=self.empresa, nombre="Supervisor Piso")
        self.assertEqual(
            set(rol.permisos.values_list("codigo", flat=True)),
            {"inventario.ver", "ventas.crear"},
        )

        # Editar rol
        perm_clientes = Permiso.objects.get(codigo="clientes.ver")
        resp_edit = self.client.post(
            reverse("equipo_rol_editar", args=[rol.pk]),
            {
                "nombre": "Supervisor Senior",
                "descripcion": "Supervisa mostrador y clientes",
                "es_admin": False,
                "permisos": [perm_ver.pk, perm_clientes.pk],
            },
        )
        self.assertRedirects(resp_edit, reverse("equipo_lista"))
        rol.refresh_from_db()
        self.assertEqual(rol.nombre, "Supervisor Senior")
        self.assertEqual(
            set(rol.permisos.values_list("codigo", flat=True)),
            {"inventario.ver", "clientes.ver"},
        )

        # Eliminar rol sin miembros asignados
        resp_del = self.client.post(reverse("equipo_rol_eliminar", args=[rol.pk]))
        self.assertRedirects(resp_del, reverse("equipo_lista"))
        self.assertFalse(Rol.objects.filter(pk=rol.pk).exists())

    def test_no_permite_eliminar_rol_con_miembros_ni_quitar_ultimo_admin(self):
        rol_admin = Rol.objects.get(empresa=self.empresa, nombre="Administrador")

        # No puede eliminar rol con miembros asignados
        resp_del = self.client.post(reverse("equipo_rol_eliminar", args=[rol_admin.pk]))
        self.assertRedirects(resp_del, reverse("equipo_lista"))
        self.assertTrue(Rol.objects.filter(pk=rol_admin.pk).exists())

        # No puede quitar es_admin al único rol con administradores activos
        resp_edit = self.client.post(
            reverse("equipo_rol_editar", args=[rol_admin.pk]),
            {
                "nombre": "Administrador",
                "descripcion": "Intento quitar admin",
                "es_admin": False,
                "permisos": [],
            },
        )
        self.assertEqual(resp_edit.status_code, 200)
        rol_admin.refresh_from_db()
        self.assertTrue(rol_admin.es_admin)

    def test_crear_miembro_nuevo_y_vincular_usuario_existente(self):
        rol_cajero = Rol.objects.get(empresa=self.empresa, nombre="Cajero POS")

        # 1. Crear usuario nuevo con contraseña
        resp_nuevo = self.client.post(
            reverse("equipo_miembro_crear"),
            {
                "email": "pedro@andina.co",
                "first_name": "Pedro",
                "last_name": "Cajero",
                "rol": rol_cajero.pk,
                "password": "ClavePedro123!",
            },
        )
        self.assertRedirects(resp_nuevo, reverse("equipo_lista"))
        pedro = User.objects.get(email="pedro@andina.co")
        self.assertTrue(pedro.check_password("ClavePedro123!"))
        membresia_pedro = Membresia.objects.get(usuario=pedro, empresa=self.empresa)
        self.assertEqual(membresia_pedro.rol, rol_cajero)
        self.assertTrue(membresia_pedro.activa)

        # 2. Vincular usuario ya existente en otra empresa sin exigir ni cambiar contraseña
        rol_contador = Rol.objects.get(empresa=self.empresa, nombre="Contador")
        resp_existente = self.client.post(
            reverse("equipo_miembro_crear"),
            {
                "email": "laura@vecina.co",
                "first_name": "Laura",
                "last_name": "Vecina",
                "rol": rol_contador.pk,
                "password": "",
            },
        )
        self.assertRedirects(resp_existente, reverse("equipo_lista"))
        self.otro_admin.refresh_from_db()
        self.assertTrue(self.otro_admin.check_password("PasswordSegura123!"))
        self.assertTrue(
            Membresia.objects.filter(
                usuario=self.otro_admin, empresa=self.empresa, rol=rol_contador
            ).exists()
        )

    def test_proteccion_anti_bloqueo_ultimo_admin_en_membresia(self):
        membresia_admin = Membresia.objects.get(usuario=self.admin_user, empresa=self.empresa)
        rol_cajero = Rol.objects.get(empresa=self.empresa, nombre="Cajero POS")
        rol_admin = membresia_admin.rol

        # Intentar degradar al único administrador activo
        resp_degradar = self.client.post(
            reverse("equipo_miembro_editar", args=[membresia_admin.pk]),
            {
                "rol": rol_cajero.pk,
                "activa": True,
            },
        )
        self.assertEqual(resp_degradar.status_code, 200)
        membresia_admin.refresh_from_db()
        self.assertEqual(membresia_admin.rol, rol_admin)

        # Intentar desactivar al único administrador activo
        resp_desactivar = self.client.post(
            reverse("equipo_miembro_editar", args=[membresia_admin.pk]),
            {
                "rol": rol_admin.pk,
                "activa": False,
            },
        )
        self.assertEqual(resp_desactivar.status_code, 200)
        membresia_admin.refresh_from_db()
        self.assertTrue(membresia_admin.activa)

    def test_aislamiento_multitenant_en_roles_y_membresias(self):
        rol_ajeno = Rol.objects.filter(empresa=self.otra_empresa).first()
        membresia_ajena = Membresia.objects.get(usuario=self.otro_admin, empresa=self.otra_empresa)

        self.assertEqual(
            self.client.get(reverse("equipo_rol_editar", args=[rol_ajeno.pk])).status_code,
            404,
        )
        self.assertEqual(
            self.client.post(reverse("equipo_rol_eliminar", args=[rol_ajeno.pk])).status_code,
            404,
        )
        self.assertEqual(
            self.client.get(reverse("equipo_miembro_editar", args=[membresia_ajena.pk])).status_code,
            404,
        )

        # Intentar asignar un rol de otra empresa al crear miembro
        resp_rol_ajeno = self.client.post(
            reverse("equipo_miembro_crear"),
            {
                "email": "intruso@andina.co",
                "first_name": "Intruso",
                "rol": rol_ajeno.pk,
                "password": "ClaveIntruso123!",
            },
        )
        self.assertEqual(resp_rol_ajeno.status_code, 200)
        self.assertFalse(Membresia.objects.filter(usuario__email="intruso@andina.co").exists())

    def test_visibilidad_menu_y_dashboard_segun_rol(self):
        cliente = Cliente.objects.create(
            empresa=self.empresa,
            nombre="Cliente General",
            tipo_documento="CC",
            numero_documento="222222222222",
        )
        Producto.objects.create(
            empresa=self.empresa,
            codigo="P-001",
            nombre="Taladro",
            precio=Decimal("150000.00"),
            stock=5,
            stock_minimo=2,
        )
        Factura.objects.create(
            empresa=self.empresa,
            cliente=cliente,
            creada_por=self.admin_user,
            numero=1,
            total=Decimal("150000.00"),
            estado="PAGADA",
        )

        # Crear usuario con rol "Bodega e inventario" (tiene inventario.*, compras, produccion; NO tiene ventas.ver ni equipo.ver)
        rol_bodega = Rol.objects.get(empresa=self.empresa, nombre="Bodega e inventario")
        bodeguero = User.objects.create_user(
            username="bodega@andina.co",
            email="bodega@andina.co",
            password="PasswordSegura123!",
            first_name="Bodeguero",
        )
        Membresia.objects.create(
            usuario=bodeguero,
            empresa=self.empresa,
            rol=rol_bodega,
            activa=True,
        )

        self.client.force_login(bodeguero)

        # No puede entrar a gestión de equipo ni POS
        self.assertEqual(self.client.get(reverse("equipo_lista")).status_code, 403)
        self.assertEqual(self.client.get(reverse("pos")).status_code, 403)

        # Sí puede entrar a productos y dashboard
        self.assertEqual(self.client.get(reverse("productos_lista")).status_code, 200)
        resp_dash = self.client.get(reverse("dashboard"))
        self.assertEqual(resp_dash.status_code, 200)
        self.assertFalse(resp_dash.context["puede_ver_ventas"])
        self.assertEqual(resp_dash.context["ventas_mes"], 0)
        self.assertEqual(list(resp_dash.context["ultimas_facturas"]), [])

        html = resp_dash.content.decode("utf-8")
        # En el dock ve Inventario pero no Punto de venta ni Equipo y roles
        self.assertIn(reverse("productos_lista"), html)
        self.assertNotIn(reverse("pos"), html)
        self.assertNotIn(reverse("equipo_lista"), html)
