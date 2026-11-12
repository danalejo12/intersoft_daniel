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


@dataclass(frozen=True)
class ResultadoNotaCreditoDian:
    aceptada: bool
    cude: str = ""
    xml_url: str = ""
    pdf_url: str = ""
    mensaje: str = ""


class ProveedorFacturacionElectronica:
    """Interfaz base para conectar cualquier proveedor tecnológico autorizado por la DIAN."""

    def emitir_factura(self, factura: Factura) -> ResultadoEmisionDian:
        raise NotImplementedError

    def emitir_nota_credito(self, factura: Factura, motivo: str = "") -> ResultadoNotaCreditoDian:
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

    def calcular_cude(self, factura: Factura, motivo: str = "") -> str:
        nit_emisor = factura.empresa_nit or factura.empresa.nit
        semilla = f"NC|{nit_emisor}|{factura.numero}|{factura.cufe}|{factura.total:.2f}|{motivo.strip()}"
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

    def emitir_nota_credito(self, factura: Factura, motivo: str = "Anulación de operación") -> ResultadoNotaCreditoDian:
        cude = self.calcular_cude(factura, motivo=motivo)
        return ResultadoNotaCreditoDian(
            aceptada=True,
            cude=cude,
            xml_url=f"https://catalogo-vpfe.dian.gov.co/document/searchqr?documentkey={cude}",
            pdf_url=f"https://catalogo-vpfe.dian.gov.co/Document/DownloadPDF?trackId={cude}",
            mensaje=f"Nota crédito electrónica validada exitosamente ({motivo}).",
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


@transaction.atomic
def emitir_nota_credito_electronica(
    *,
    factura: Factura,
    motivo: str = "Anulación de operación",
    proveedor: ProveedorFacturacionElectronica | None = None,
) -> Factura:
    """Emite de forma idempotente una Nota Crédito Electrónica (CUDE) para una factura aceptada por la DIAN."""
    bloqueada = Factura.objects.select_for_update().select_related("empresa", "cliente").get(pk=factura.pk)
    if bloqueada.estado_dian != Factura.EstadoDian.ACEPTADA or not bloqueada.cufe:
        raise ValueError("Solo se puede emitir nota crédito electrónica para facturas aceptadas ante la DIAN.")
    if bloqueada.cude_nota_credito:
        return bloqueada

    adaptador = proveedor or ProveedorSimuladoDian()
    resultado = adaptador.emitir_nota_credito(bloqueada, motivo=motivo)
    if not resultado.aceptada or not (resultado.cude or "").strip():
        raise ValueError(resultado.mensaje or "El proveedor tecnológico no aprobó la nota crédito electrónica.")

    bloqueada.cude_nota_credito = resultado.cude.strip()[:120]
    bloqueada.dian_respuesta = (resultado.mensaje or "Nota crédito aceptada por DIAN")[:250]
    bloqueada.save(update_fields=["cude_nota_credito", "dian_respuesta", "actualizado_en"])
    return bloqueada
