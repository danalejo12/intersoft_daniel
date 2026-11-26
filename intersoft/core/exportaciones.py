"""Generación de documentos descargables: Factura en PDF (ReportLab) y Reportes ERP en Excel (OpenPyXL)."""
import io
from decimal import Decimal

from openpyxl import Workbook
from openpyxl.styles import Alignment, Font, PatternFill
from reportlab.lib import colors
from reportlab.lib.pagesizes import letter
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

from .validadores import sanitizar_celda_hoja


def _pesos(valor) -> str:
    """Formatea un valor como pesos colombianos sin decimales ($ 1.234.567)."""
    cantidad = Decimal(str(valor or 0))
    return f"$ {cantidad:,.0f}".replace(",", ".")


def generar_factura_pdf(factura) -> bytes:
    """Construye el PDF oficial de una factura (incluyendo datos fiscales y CUFE/CUDE DIAN)."""
    buffer = io.BytesIO()
    doc = SimpleDocTemplate(
        buffer,
        pagesize=letter,
        leftMargin=18 * mm,
        rightMargin=18 * mm,
        topMargin=16 * mm,
        bottomMargin=16 * mm,
        title=f"Factura {factura.numero}",
    )

    estilos = getSampleStyleSheet()
    azul = colors.HexColor("#0F2A5C")
    esmeralda = colors.HexColor("#10B981")
    gris_claro = colors.HexColor("#F8FAFC")
    gris_borde = colors.HexColor("#CBD5E1")

    estilo_sub = ParagraphStyle(
        "SubFactura", parent=estilos["Normal"], fontSize=9.5, textColor=colors.HexColor("#475569"), leading=13
    )
    estilo_celda = ParagraphStyle("Celda", parent=estilos["Normal"], fontSize=9, leading=12)

    empresa = factura.empresa
    emisor_nombre = factura.empresa_nombre or empresa.nombre
    emisor_nit = factura.empresa_nit or empresa.nit
    emisor_dir = factura.empresa_direccion or empresa.direccion or "Sin dirección registrada"
    emisor_tel = factura.empresa_telefono or empresa.telefono or "Sin teléfono"

    cliente_nombre = factura.cliente_nombre or factura.cliente.nombre
    cliente_doc = factura.cliente_documento or f"{factura.cliente.tipo_documento} {factura.cliente.numero_documento}"

    elementos = []

    cabecera = Table(
        [
            [
                Paragraph(
                    f"<b>{emisor_nombre}</b><br/>"
                    f"NIT: {emisor_nit}<br/>"
                    f"{emisor_dir}<br/>"
                    f"Tel: {emisor_tel}",
                    estilo_sub,
                ),
                Paragraph(
                    f"<font size='16' color='#0F2A5C'><b>FACTURA N.º {factura.numero}</b></font><br/>"
                    f"<b>Fecha:</b> {factura.creado_en.strftime('%d/%m/%Y %H:%M')}<br/>"
                    f"<b>Estado:</b> {factura.get_estado_display()}<br/>"
                    f"<b>DIAN:</b> {factura.get_estado_dian_display()}",
                    ParagraphStyle("Der", parent=estilo_sub, alignment=2),
                ),
            ]
        ],
        colWidths=[95 * mm, 85 * mm],
    )
    cabecera.setStyle(
        TableStyle(
            [
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ("LINEBELOW", (0, 0), (-1, 0), 2, esmeralda),
                ("BOTTOMPADDING", (0, 0), (-1, 0), 10),
            ]
        )
    )
    elementos.append(cabecera)
    elementos.append(Spacer(1, 10))

    elementos.append(
        Paragraph(
            f"<b>Cliente:</b> {cliente_nombre} &nbsp;&nbsp;|&nbsp;&nbsp; <b>Documento:</b> {cliente_doc}",
            estilo_celda,
        )
    )
    elementos.append(Spacer(1, 10))

    filas_items = [["Código", "Producto", "Cant.", "Precio unit.", "IVA %", "Subtotal"]]
    for d in factura.detalles.select_related("producto").all():
        filas_items.append(
            [
                d.producto.codigo,
                Paragraph(d.nombre_producto or d.producto.nombre, estilo_celda),
                str(d.cantidad),
                _pesos(d.precio_unitario),
                f"{d.iva_porcentaje:.0f}%",
                _pesos(d.subtotal),
            ]
        )

    tabla_items = Table(
        filas_items,
        colWidths=[24 * mm, 72 * mm, 16 * mm, 26 * mm, 16 * mm, 26 * mm],
        repeatRows=1,
    )
    tabla_items.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, 0), azul),
                ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
                ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
                ("FONTSIZE", (0, 0), (-1, -1), 9),
                ("ALIGN", (2, 0), (-1, -1), "RIGHT"),
                ("ALIGN", (0, 0), (1, -1), "LEFT"),
                ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
                ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, gris_claro]),
                ("GRID", (0, 0), (-1, -1), 0.5, gris_borde),
                ("TOPPADDING", (0, 0), (-1, -1), 6),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
            ]
        )
    )
    elementos.append(tabla_items)
    elementos.append(Spacer(1, 12))

    tabla_totales = Table(
        [
            ["", "Subtotal", _pesos(factura.subtotal)],
            ["", "IVA", _pesos(factura.iva)],
            ["", "TOTAL A PAGAR", _pesos(factura.total)],
        ],
        colWidths=[106 * mm, 42 * mm, 32 * mm],
    )
    tabla_totales.setStyle(
        TableStyle(
            [
                ("ALIGN", (1, 0), (-1, -1), "RIGHT"),
                ("FONTNAME", (1, 2), (-1, 2), "Helvetica-Bold"),
                ("FONTSIZE", (1, 2), (-1, 2), 11),
                ("TEXTCOLOR", (1, 2), (-1, 2), azul),
                ("LINEABOVE", (1, 2), (-1, 2), 1.5, azul),
                ("TOPPADDING", (0, 0), (-1, -1), 5),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
            ]
        )
    )
    elementos.append(tabla_totales)

    if factura.cufe or factura.cude_nota_credito:
        elementos.append(Spacer(1, 14))
        texto_dian = "<b>Validación Electrónica DIAN</b><br/>"
        if factura.cufe:
            texto_dian += f"<b>CUFE:</b> {factura.cufe}<br/>"
        if factura.cude_nota_credito:
            texto_dian += f"<b>CUDE Nota Crédito (Anulación):</b> {factura.cude_nota_credito}<br/>"
        elementos.append(Paragraph(texto_dian, estilo_sub))

    elementos.append(Spacer(1, 16))
    elementos.append(
        Paragraph(
            "Documento generado por <b>InterSoft</b> · Tu negocio, conectado.",
            ParagraphStyle("Pie", parent=estilo_sub, alignment=1, fontSize=8.5),
        )
    )

    doc.build(elementos)
    return buffer.getvalue()


def generar_reporte_erp_excel(*, empresa, cartera=None, cuentas=None, balance=None) -> bytes:
    """Genera un libro Excel (.xlsx) con las secciones financieras autorizadas para el usuario."""
    wb = Workbook()
    # Quitamos la hoja vacía por defecto al final si creamos hojas específicas
    hoja_inicial = wb.active
    hoja_inicial.title = "Resumen"
    hoja_inicial.append(["Reporte Financiero y Contable — InterSoft"])
    hoja_inicial.append(["Empresa", empresa.nombre])
    hoja_inicial.append(["NIT", empresa.nit])

    fill_header = PatternFill("solid", fgColor="0F2A5C")
    font_header = Font(bold=True, color="FFFFFF")
    font_titulo = Font(bold=True, size=13, color="0F2A5C")
    hoja_inicial["A1"].font = font_titulo

    def _estilizar_cabecera(ws, fila=1):
        """Pone el estilo de encabezado en una fila de la hoja de Excel."""
        for cell in ws[fila]:
            cell.fill = fill_header
            cell.font = font_header
            cell.alignment = Alignment(horizontal="left", vertical="center")

    def _auto_ancho(ws):
        """Ajusta el ancho de las columnas de la hoja a su contenido (entre 14 y 45)."""
        for col in ws.columns:
            max_len = max((len(str(c.value or "")) for c in col), default=10)
            ws.column_dimensions[col[0].column_letter].width = min(45, max(14, max_len + 4))

    if cartera is not None:
        ws = wb.create_sheet("Cartera")
        ws.append(["Tipo de cartera", "Saldo pendiente (COP)"])
        _estilizar_cabecera(ws)
        for item in cartera:
            ws.append([sanitizar_celda_hoja(item["tipo"]), float(item["total"] or 0)])
        for row in ws.iter_rows(min_row=2, min_col=2, max_col=2):
            row[0].number_format = '"$ "#,##0'
        _auto_ancho(ws)

    if cuentas is not None:
        ws = wb.create_sheet("Tesoreria")
        ws.append(["Cuenta de caja / banco", "Saldo actual (COP)"])
        _estilizar_cabecera(ws)
        for c in cuentas:
            ws.append([sanitizar_celda_hoja(c["nombre"]), float(c["saldo"] or 0)])
        for row in ws.iter_rows(min_row=2, min_col=2, max_col=2):
            row[0].number_format = '"$ "#,##0'
        _auto_ancho(ws)

    if balance is not None:
        ws = wb.create_sheet("Balance de Prueba")
        ws.append(["Código PUC", "Cuenta contable", "Débito (COP)", "Crédito (COP)"])
        _estilizar_cabecera(ws)
        for b in balance:
            ws.append(
                [
                    sanitizar_celda_hoja(b["cuenta__codigo"]),
                    sanitizar_celda_hoja(b["cuenta__nombre"]),
                    float(b["debito"] or 0),
                    float(b["credito"] or 0),
                ]
            )
        for row in ws.iter_rows(min_row=2, min_col=3, max_col=4):
            for cell in row:
                cell.number_format = '"$ "#,##0'
        _auto_ancho(ws)

    _auto_ancho(hoja_inicial)
    salida = io.BytesIO()
    wb.save(salida)
    return salida.getvalue()


def generar_ticket_pos_pdf(factura) -> bytes:
    """Genera el ticket POS en formato PDF (80mm) con ReportLab."""
    buffer = io.BytesIO()
    ancho = 80 * mm
    detalles = list(factura.detalles.select_related("producto"))
    pagos = list(factura.pagos_caja.all())
    alto = max(140 * mm, (110 + len(detalles) * 14 + len(pagos) * 10) * mm)

    doc = SimpleDocTemplate(
        buffer,
        pagesize=(ancho, alto),
        leftMargin=5 * mm,
        rightMargin=5 * mm,
        topMargin=6 * mm,
        bottomMargin=6 * mm,
        title=f"Ticket POS {factura.numero}",
    )
    estilos = getSampleStyleSheet()
    centro = ParagraphStyle("Centro", parent=estilos["Normal"], fontSize=8.5, alignment=1, leading=11)
    titulo = ParagraphStyle("TituloTicket", parent=estilos["Heading2"], fontSize=11, alignment=1, spaceAfter=2)
    normal = ParagraphStyle("NormalTicket", parent=estilos["Normal"], fontSize=8, leading=10)

    empresa = factura.empresa
    elementos = [
        Paragraph(factura.empresa_nombre or empresa.nombre, titulo),
        Paragraph(f"NIT {factura.empresa_nit or empresa.nit}", centro),
        Spacer(1, 3 * mm),
        Paragraph(f"<b>Venta N.º {factura.numero}</b> · {factura.creado_en:%d/%m/%Y %H:%M}", normal),
        Paragraph(f"Cliente: {factura.cliente_nombre or factura.cliente.nombre}", normal),
        Spacer(1, 2 * mm),
    ]

    filas = [["Producto", "Cant", "Total"]]
    for d in detalles:
        filas.append([Paragraph(d.producto.nombre[:28], normal), str(d.cantidad), _pesos(d.subtotal)])
    filas.append(["", "Subtotal", _pesos(factura.subtotal)])
    filas.append(["", "IVA", _pesos(factura.iva)])
    filas.append(["", "TOTAL", _pesos(factura.total)])

    tabla = Table(filas, colWidths=[38 * mm, 12 * mm, 20 * mm])
    tabla.setStyle(
        TableStyle(
            [
                ("FONTSIZE", (0, 0), (-1, -1), 7.5),
                ("LINEBELOW", (0, 0), (-1, 0), 0.5, colors.black),
                ("LINEABOVE", (0, -1), (-1, -1), 0.8, colors.black),
                ("ALIGN", (1, 0), (-1, -1), "RIGHT"),
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
            ]
        )
    )
    elementos.append(tabla)

    if pagos:
        elementos.append(Spacer(1, 3 * mm))
        elementos.append(Paragraph("<b>Pagos:</b>", normal))
        for p in pagos:
            elementos.append(Paragraph(f"- {p.get_metodo_display()}: {_pesos(p.monto)}", normal))

    doc.build(elementos)
    return buffer.getvalue()


def _libro_excel_con_cabecera(titulo_hoja: str, encabezados: list[str], filas: list[list], cols_moneda: tuple[int, ...] = ()) -> bytes:
    """Construye un libro .xlsx estilizado con encabezados, autoajuste y formato moneda COP."""
    wb = Workbook()
    ws = wb.active
    ws.title = titulo_hoja[:31]
    ws.append(encabezados)

    fill_header = PatternFill("solid", fgColor="0F2A5C")
    font_header = Font(bold=True, color="FFFFFF")
    for cell in ws[1]:
        cell.fill = fill_header
        cell.font = font_header
        cell.alignment = Alignment(horizontal="left", vertical="center")

    for fila in filas:
        ws.append(fila)

    for row in ws.iter_rows(min_row=2):
        for idx in cols_moneda:
            if idx - 1 < len(row):
                row[idx - 1].number_format = '"$ "#,##0'

    for col in ws.columns:
        max_len = max((len(str(c.value or "")) for c in col), default=10)
        ws.column_dimensions[col[0].column_letter].width = min(45, max(12, max_len + 4))

    salida = io.BytesIO()
    wb.save(salida)
    return salida.getvalue()


def generar_pedidos_marketplace_excel(*, empresa, pedidos) -> bytes:
    """Exporta a Excel (.xlsx) los pedidos del marketplace y su liquidación."""
    encabezados = [
        "Pedido #",
        "Fecha",
        "Comprador",
        "Ciudad",
        "Estado pago",
        "Estado envío",
        "Bodega",
        "Guía",
        "Subtotal",
        "IVA",
        "Envío",
        "Comisión",
        "Neto negocio",
        "Total cobrado",
    ]
    filas = []
    for p in pedidos:
        filas.append([
            p.numero,
            p.creado_en.strftime("%Y-%m-%d %H:%M"),
            p.nombre,
            p.ciudad,
            p.get_estado_display(),
            p.get_estado_envio_display() if p.estado == p.Estado.PAGADO else "—",
            p.bodega.nombre if p.bodega else "—",
            p.numero_guia or "—",
            float(p.subtotal or 0),
            float(p.iva or 0),
            float(p.costo_envio or 0),
            float(p.comision_valor or 0),
            float(p.neto_vendedor or 0),
            float(p.total or 0),
        ])
    return _libro_excel_con_cabecera("Pedidos Marketplace", encabezados, filas, cols_moneda=(9, 10, 11, 12, 13, 14))


def generar_turnos_pos_excel(*, empresa, turnos) -> bytes:
    """Exporta a Excel (.xlsx) el historial de turnos de caja POS."""
    encabezados = [
        "Apertura",
        "Cierre",
        "Cajero",
        "Bodega",
        "Base inicial",
        "Efectivo contado",
        "Diferencia",
        "Estado",
    ]
    filas = []
    for t in turnos:
        filas.append([
            t.creado_en.strftime("%Y-%m-%d %H:%M"),
            t.cerrado_en.strftime("%Y-%m-%d %H:%M") if t.cerrado_en else "—",
            t.cajero.get_full_name() or t.cajero.email,
            t.bodega.nombre if t.bodega else "Principal",
            float(t.base_inicial or 0),
            float(t.efectivo_contado or 0) if t.cerrado_en else 0.0,
            float(t.diferencia or 0) if t.cerrado_en else 0.0,
            "Cerrada" if t.cerrado_en else "Abierta",
        ])
    return _libro_excel_con_cabecera("Turnos POS", encabezados, filas, cols_moneda=(5, 6, 7))

