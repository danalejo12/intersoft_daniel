"""Adaptador desacoplado de facturación electrónica DIAN (CUFE, validación previa y proveedor tecnológico)."""
from dataclasses import dataclass
import hashlib

from django.db import transaction
from django.utils import timezone

from .models import Factura


@dataclass(frozen=True)
class ResultadoEmisionDian:
    aceptada: bool
    cufe: str = ""
    xml_url: str = ""
    pdf_url: str = ""
    mensaje: str = ""


class ProveedorFacturacionElectronica:
    """Interfaz base para conectar cualquier proveedor tecnológico autorizado por la DIAN."""

    def emitir_factura(self, factura: Factura) -> ResultadoEmisionDian:
        raise NotImplementedError


class ProveedorSimuladoDian(ProveedorFacturacionElectronica):
    """Proveedor determinista local para pruebas y validación funcional sin red externa."""

    def calcular_cufe(self, factura: Factura) -> str:
        nit_emisor = factura.empresa_nit or factura.empresa.nit
        doc_adquiriente = factura.cliente_documento or f"{factura.cliente.tipo_documento} {factura.cliente.numero_documento}"
        semilla = (
            f"{nit_emisor}|{factura.numero}|{factura.subtotal:.2f}|"
            f"{factura.iva:.2f}|{factura.total:.2f}|{doc_adquiriente}"
        )
        return hashlib.sha384(semilla.encode("utf-8")).hexdigest()

    def emitir_factura(self, factura: Factura) -> ResultadoEmisionDian:
        cufe = self.calcular_cufe(factura)
        return ResultadoEmisionDian(
            aceptada=True,
            cufe=cufe,
            xml_url=f"https://catalogo-vpfe.dian.gov.co/document/searchqr?documentkey={cufe}",
            pdf_url=f"https://catalogo-vpfe.dian.gov.co/Document/DownloadPDF?trackId={cufe}",
            mensaje="Documento electrónico validado exitosamente (simulador DIAN).",
        )


@transaction.atomic
def emitir_factura_electronica(*, factura: Factura, proveedor: ProveedorFacturacionElectronica | None = None) -> Factura:
    """Emite o sincroniza una factura ante el proveedor electrónico de forma idempotente."""
    bloqueada = Factura.objects.select_for_update().select_related("empresa", "cliente").get(pk=factura.pk)
    if bloqueada.estado == Factura.Estado.ANULADA:
        raise ValueError("No se puede emitir ante la DIAN una factura anulada.")
    if bloqueada.total <= 0:
        raise ValueError("Solo se pueden emitir facturas con total mayor que cero.")

    # Idempotencia: si ya fue aceptada y tiene CUFE, no se vuelve a emitir
    if bloqueada.estado_dian == Factura.EstadoDian.ACEPTADA and bloqueada.cufe:
        return bloqueada

    adaptador = proveedor or ProveedorSimuladoDian()
    resultado = adaptador.emitir_factura(bloqueada)
    if resultado.aceptada:
        if not (resultado.cufe or "").strip():
            raise ValueError("El proveedor tecnológico aprobó la factura sin devolver el CUFE.")
        bloqueada.estado_dian = Factura.EstadoDian.ACEPTADA
        bloqueada.cufe = resultado.cufe.strip()[:120]
        bloqueada.dian_xml_url = (resultado.xml_url or "").strip()[:200]
        bloqueada.dian_pdf_url = (resultado.pdf_url or "").strip()[:200]
        bloqueada.dian_respuesta = (resultado.mensaje or "Aceptada por DIAN")[:250]
        bloqueada.dian_emitida_en = timezone.now()
    else:
        bloqueada.estado_dian = Factura.EstadoDian.RECHAZADA
        bloqueada.dian_respuesta = (resultado.mensaje or "Rechazada por el proveedor tecnológico")[:250]

    bloqueada.save(
        update_fields=[
            "estado_dian",
            "cufe",
            "dian_xml_url",
            "dian_pdf_url",
            "dian_respuesta",
            "dian_emitida_en",
            "actualizado_en",
        ]
    )
    return bloqueada
