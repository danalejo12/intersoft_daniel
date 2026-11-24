"""Auditoría automática del HTML de cada página de /plataforma/.

Abre todas las secciones como Dueño, con datos reales en cada una, y revisa lo que suele romper formularios
y la experiencia sin que nadie lo note: ids repetidos (una etiqueta que activa el campo de otro formulario),
etiquetas que apuntan a campos inexistentes, formularios POST sin CSRF, formularios anidados (el navegador los
rompe), campos visibles sin etiqueta y clases de insignias que no existen en el CSS.
"""
import re
from collections import Counter
from decimal import Decimal
from html.parser import HTMLParser

from django.contrib.staticfiles import finders
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from core.models import Usuario
from core.tests_compra import crear_negocio, crear_usuario
from pqrs.models import PQRS
from pqrs.services import radicar_pqrs
from soporte.models import ComentarioWidget, ErrorRegistrado, Idea
from suscripciones.models import CobroSuscripcion, CuponPlan, Plan

from . import auditoria
from .models import FeatureFlag, RolPlataforma

CAMPOS_SIN_ETIQUETA_PERMITIDOS = {"hidden", "submit", "button", "reset", "image"}


class AnalizadorHTML(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.ids = []
        self.etiquetas_for = []
        self.formularios = []          # [{"metodo":..., "csrf": bool}]
        self.anidados = 0
        self.profundidad_form = 0
        self.campos = []               # (tipo, id, tiene_aria, dentro_de_label)
        self.dentro_label = 0
        self.clases_badge = []

    def handle_starttag(self, etiqueta, atributos):
        a = dict(atributos)
        if a.get("id"):
            self.ids.append(a["id"])
        clases = (a.get("class") or "").split()
        if "badge" in clases:
            self.clases_badge.extend(c for c in clases if c != "badge")
        if etiqueta == "label":
            self.dentro_label += 1
            if a.get("for"):
                self.etiquetas_for.append(a["for"])
        elif etiqueta == "form":
            if self.profundidad_form:
                self.anidados += 1
            self.profundidad_form += 1
            self.formularios.append({"metodo": (a.get("method") or "get").lower(), "csrf": False})
        elif etiqueta in ("input", "select", "textarea"):
            if etiqueta == "input" and a.get("name") == "csrfmiddlewaretoken" and self.formularios:
                self.formularios[-1]["csrf"] = True
            tipo = (a.get("type") or "text").lower() if etiqueta == "input" else etiqueta
            if tipo not in CAMPOS_SIN_ETIQUETA_PERMITIDOS and "hidden" not in a:
                self.campos.append((tipo, a.get("id"), bool(a.get("aria-label") or a.get("aria-labelledby")),
                                    self.dentro_label > 0, a.get("name")))

    def handle_endtag(self, etiqueta):
        if etiqueta == "label":
            self.dentro_label = max(self.dentro_label - 1, 0)
        elif etiqueta == "form":
            self.profundidad_form = max(self.profundidad_form - 1, 0)


class RevisionUIPlataformaTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.jefe = Usuario.objects.create_user(username="jefe@intersoft.co", email="jefe@intersoft.co",
                                               password="x", is_staff=True, first_name="Daniel")
        RolPlataforma.objects.create(usuario=cls.jefe, rol=RolPlataforma.Rol.DUENO, activo=True)

        dueno = crear_usuario("dueno@negocio.co", "Marta")
        cls.negocio = crear_negocio("Dulce Hogar", "900", dueno)
        plan = Plan.objects.get(codigo="pro")
        CobroSuscripcion.objects.create(
            empresa=cls.negocio, plan=plan, ciclo="MENSUAL", referencia="SUS-revision",
            precio_lista=Decimal("149900"), monto=Decimal("149900"),
            estado=CobroSuscripcion.Estado.REQUIERE_REVISION, detalle="Monto distinto",
        )
        CuponPlan.objects.create(codigo="BIENVENIDA", valor=Decimal("10"))
        FeatureFlag.objects.create(empresa=cls.negocio, codigo="multisede", habilitado=True)
        cls.pqrs = radicar_pqrs(autor=dueno, tipo=PQRS.Tipo.PETICION, flujo=PQRS.Flujo.NEGOCIO_INTERSOFT,
                                asunto="Ayuda con facturas", descripcion="No sé cómo anular", empresa=cls.negocio)
        cls.error = ErrorRegistrado.objects.create(huella="h1", tipo_excepcion="ValueError", mensaje="falló",
                                                   archivo="core/views.py", linea=10, url="/panel/")
        ComentarioWidget.objects.create(empresa=cls.negocio, usuario=dueno, util=False, comentario="Lento",
                                        pantalla="/panel/")
        Idea.objects.create(empresa=cls.negocio, autor=dueno, titulo="Modo offline", descripcion="Para el POS")
        auditoria.registrar(actor=cls.jefe, accion="editar_plan", objeto_tipo="Plan", objeto_id=str(plan.pk))
        cls.plan = plan

    def setUp(self):
        self.client.force_login(self.jefe)
        sesion = self.client.session
        sesion["plataforma_totp_verificado"] = str(self.jefe.pk)
        sesion.save()

    def paginas(self):
        return {
            "Inicio": reverse("plataforma_inicio"),
            "Negocios": reverse("plataforma_negocios"),
            "Planes y cobros": reverse("plataforma_planes_cobros"),
            "Editar plan": reverse("plataforma_editar_plan", args=[self.plan.pk]),
            "PQRS": reverse("plataforma_pqrs"),
            "Detalle PQRS": reverse("plataforma_pqrs_detalle", args=[self.pqrs.pk]),
            "Errores": reverse("plataforma_errores"),
            "Detalle error": reverse("plataforma_error_detalle", args=[self.error.pk]),
            "Comentarios": reverse("plataforma_comentarios"),
            "Ideas": reverse("plataforma_ideas"),
            "Operación": reverse("plataforma_operacion"),
            "Auditoría": reverse("plataforma_auditoria"),
        }

    def analizar(self, url):
        respuesta = self.client.get(url)
        self.assertEqual(respuesta.status_code, 200, url)
        analizador = AnalizadorHTML()
        analizador.feed(respuesta.content.decode())
        return analizador

    def test_cada_pagina_tiene_html_y_formularios_sanos(self):
        problemas = []
        for nombre, url in self.paginas().items():
            html = self.analizar(url)
            repetidos = [i for i, n in Counter(html.ids).items() if n > 1]
            if repetidos:
                problemas.append(f"{nombre}: ids repetidos {repetidos}")
            huerfanas = sorted(set(html.etiquetas_for) - set(html.ids))
            if huerfanas:
                problemas.append(f"{nombre}: etiquetas que apuntan a campos inexistentes {huerfanas}")
            sin_csrf = [f for f in html.formularios if f["metodo"] == "post" and not f["csrf"]]
            if sin_csrf:
                problemas.append(f"{nombre}: {len(sin_csrf)} formulario(s) POST sin CSRF")
            if html.anidados:
                problemas.append(f"{nombre}: {html.anidados} formulario(s) dentro de otro formulario")
            etiquetados = set(html.etiquetas_for)
            sin_etiqueta = [
                c[4] or c[0] for c in html.campos
                if not (c[2] or c[3] or (c[1] and c[1] in etiquetados))
            ]
            if sin_etiqueta:
                problemas.append(f"{nombre}: campos sin etiqueta {sin_etiqueta}")
        self.assertEqual(problemas, [], "\n" + "\n".join(problemas))

    def test_las_insignias_usan_clases_que_existen(self):
        with open(finders.find("core/css/app.css"), encoding="utf-8") as archivo:
            definidas = set(re.findall(r"\.badge\.([a-z-]+)", archivo.read()))
        usadas = set()
        for url in self.paginas().values():
            usadas.update(self.analizar(url).clases_badge)
        # También las que solo aparecen con ciertos datos: se leen directo de las plantillas
        from pathlib import Path

        from django.conf import settings
        raiz = Path(settings.BASE_DIR)
        plantillas = [*raiz.glob("plataforma/templates/plataforma/*.html"),
                      *raiz.glob("pqrs/templates/pqrs/plataforma_*.html"),
                      *raiz.glob("soporte/templates/soporte/plataforma_*.html")]
        for ruta in plantillas:
            usadas.update(re.findall(r'class="badge ([a-z-]+)', ruta.read_text(encoding="utf-8")))
        self.assertEqual(sorted(usadas - definidas), [], "Insignias sin estilo definido")

    def test_planes_y_cobros_sin_campos_cruzados(self):
        """Cortesía, cupones e interruptores tienen campos con el mismo nombre en la misma página."""
        html = self.client.get(reverse("plataforma_planes_cobros")).content.decode()
        for id_esperado in ('id="cortesia_empresa"', 'id="flag_empresa"', 'id="cupon_codigo"', 'id="flag_codigo"'):
            self.assertIn(id_esperado, html)
        # Los nombres que se envían no cambian: crear un cupón sigue funcionando igual
        respuesta = self.client.post(reverse("plataforma_planes_cobros"), {
            "accion": "crear_cupon", "codigo": "NAVIDAD", "tipo": "porcentaje", "valor": "15",
            "inicia_en": timezone.now().strftime("%Y-%m-%dT%H:%M"), "activo": "on",
        })
        self.assertEqual(respuesta.status_code, 302)
        self.assertTrue(CuponPlan.objects.filter(codigo="NAVIDAD").exists())

    def test_cupones_e_interruptores_no_se_montan(self):
        """Antes iban lado a lado y el formulario de cupones (7 campos) y su tabla empujaban la tarjeta
        sobre la de interruptores. Ahora van apiladas, con formularios compactos, y ninguna tarjeta de un
        grid puede crecer más que su columna."""
        html = self.client.get(reverse("plataforma_planes_cobros")).content.decode()
        seccion = html[html.index('id="seccion-cupones"'):]
        self.assertIn('class="tarjetas-apiladas"', html[html.index('id="seccion-cupones"') - 60:][:120])
        self.assertEqual(seccion.count('class="form-compacto"'), 2)
        self.assertNotIn('class="formulario"', seccion)
        with open(finders.find("core/css/app.css"), encoding="utf-8") as archivo:
            css = archivo.read()
        self.assertIn(".tarjeta, .kpi { min-width: 0; }", css)
        self.assertIn(".tarjetas-apiladas { display: grid; grid-template-columns: minmax(0, 1fr);", css)

    def test_la_ventana_queda_centrada_con_el_menu_abierto_o_cerrado(self):
        """El menú (dock) va en la primera columna y a la derecha hay una columna espejo del mismo ancho;
        así abrir el menú no corre la ventana. Exige que la escena tenga solo dos hijos: dock y ventana."""
        with open(finders.find("core/css/app.css"), encoding="utf-8") as archivo:
            css = archivo.read()
        self.assertIn("grid-template-columns: var(--dock-col) minmax(0, 1fr) var(--dock-col);", css)
        self.assertIn(".dock-abierto .escena { --dock-col: 210px; }", css)
        self.assertIn('.escena::after { content: ""; }', css)

        class Hijos(HTMLParser):
            def __init__(self):
                super().__init__()
                self.nivel, self.en_escena, self.hijos = 0, None, []

            def handle_starttag(self, etiqueta, atributos):
                if etiqueta in ("img", "input", "br", "meta", "link", "source", "hr"):
                    return
                self.nivel += 1
                if self.en_escena is None and "escena" in (dict(atributos).get("class") or "").split():
                    self.en_escena = self.nivel
                elif self.en_escena is not None and self.nivel == self.en_escena + 1:
                    self.hijos.append((etiqueta, dict(atributos).get("class", "")))

            def handle_endtag(self, etiqueta):
                if etiqueta in ("img", "input", "br", "meta", "link", "source", "hr"):
                    return
                if self.en_escena is not None and self.nivel == self.en_escena:
                    self.en_escena = -1
                self.nivel -= 1

        for url in (reverse("plataforma_inicio"), reverse("plataforma_planes_cobros")):
            analizador = Hijos()
            analizador.feed(self.client.get(url).content.decode())
            self.assertEqual([c.split()[0] for _, c in analizador.hijos], ["dock", "ventana"], url)

    def test_modo_dia_y_noche_en_todas_las_paginas(self):
        for nombre, url in self.paginas().items():
            html = self.client.get(url).content.decode()
            self.assertIn("data-tema-boton", html, nombre)
            self.assertIn("core/js/tema-init.js", html, nombre)
