"""Aportes de nómina (QA-03): los adicionales salariales aportan a salud y pensión; el auxilio de transporte no."""
from decimal import Decimal

from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from .models import Empleado, LiquidacionNomina
from .tests_compra import crear_negocio, crear_usuario


class AportesNominaTests(TestCase):
    def setUp(self):
        self.duena = crear_usuario("duena@nomina.co")
        self.negocio = crear_negocio("Pastelería Nómina", "900", self.duena)
        self.client.force_login(self.duena)
        empleado = Empleado.objects.create(empresa=self.negocio, nombre="Carlos Pérez", documento="1010",
                                           cargo="Panadero", salario_base=Decimal("1300000"), activo=True)
        hoy = timezone.localdate()
        self.nomina = LiquidacionNomina.objects.create(
            empresa=self.negocio, empleado=empleado, desde=hoy, hasta=hoy,
            base=Decimal("1300000"), adicionales=Decimal("200000"), auxilio_transporte=Decimal("162000"),
            neto=Decimal("1662000"),
        )

    def test_ejemplo_del_informe_de_calidad(self):
        """Base $1.300.000 + $200.000 de horas extra: salud 4 % y pensión 4 % sobre $1.500.000 = $120.000.
        Antes los adicionales se trataban como auxilio de transporte y solo se deducían $104.000."""
        self.client.post(reverse("erp_detalle", args=["nomina", self.nomina.pk]), {"accion": "calcular_aportes"})
        self.nomina.refresh_from_db()
        self.assertEqual(self.nomina.deducciones, Decimal("120000.00"))
        # Neto = base + adicionales + auxilio (se paga aunque no aporte) − deducciones
        self.assertEqual(self.nomina.neto, Decimal("1542000.00"))

    def test_el_auxilio_de_transporte_no_cambia_las_deducciones(self):
        LiquidacionNomina.objects.filter(pk=self.nomina.pk).update(auxilio_transporte=Decimal("500000"))
        self.client.post(reverse("erp_detalle", args=["nomina", self.nomina.pk]), {"accion": "calcular_aportes"})
        self.nomina.refresh_from_db()
        self.assertEqual(self.nomina.deducciones, Decimal("120000.00"))

    def test_el_formulario_pide_el_auxilio_por_separado(self):
        respuesta = self.client.get(reverse("erp_crear", args=["nomina"]))
        self.assertContains(respuesta, 'name="auxilio_transporte"')
        self.assertContains(respuesta, "Adicionales salariales")

    def test_aprobar_incluye_el_auxilio_en_la_cuenta_por_pagar(self):
        from .erp_services import aprobar_nomina

        aprobada = aprobar_nomina(empresa=self.negocio, pk=self.nomina.pk)
        self.assertEqual(aprobada.neto, Decimal("1662000.00"))
        self.assertEqual(aprobada.cartera.total, Decimal("1662000.00"))
