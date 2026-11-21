"""Importación masiva de productos y stock inicial desde Excel (.xlsx con openpyxl)."""
from django.utils.translation import gettext
from decimal import Decimal, InvalidOperation

import openpyxl
from django.db import transaction

from .bodegas import bodega_principal, validar_bodega
from .models import Categoria, MovimientoInventario, Producto
from .services import registrar_movimiento


def _limpiar_texto(valor) -> str:
    return str(valor).strip() if valor is not None else ""


def _parsear_decimal(valor, *, defecto=None, campo: str) -> Decimal:
    if valor in (None, ""):
        if defecto is not None:
            return defecto
        raise ValueError(gettext("El campo '{campo}' es obligatorio.").format(campo=campo))
    try:
        dec = Decimal(str(valor).strip())
    except (InvalidOperation, ValueError) as exc:
        raise ValueError(gettext("Valor numérico inválido en '{campo}': {valor}").format(campo=campo, valor=valor)) from exc
    if dec < Decimal("0"):
        raise ValueError(gettext("El campo '{campo}' no puede ser negativo.").format(campo=campo))
    return dec


def _parsear_entero(valor, *, defecto=0, campo: str) -> int:
    if valor in (None, ""):
        return defecto
    try:
        num = int(float(str(valor).strip()))
    except (ValueError, TypeError) as exc:
        raise ValueError(gettext("Valor entero inválido en '{campo}': {valor}").format(campo=campo, valor=valor)) from exc
    if num < 0:
        raise ValueError(gettext("El campo '{campo}' no puede ser negativo.").format(campo=campo))
    return num


def importar_productos_excel(*, empresa, archivo, usuario, bodega=None) -> dict:
    """Valida e importa productos y stock inicial desde un archivo .xlsx.

    Columnas soportadas en la fila 1 (encabezados):
    `codigo`, `nombre`, `categoria` (opcional), `precio`, `costo` (opcional),
    `iva_porcentaje` (opcional), `stock_minimo` (opcional), `stock_inicial` (opcional).

    Si alguna fila tiene errores, no crea productos y devuelve `{"creados": 0, "errores": [...]}`.
    """
    try:
        wb = openpyxl.load_workbook(archivo, data_only=True, read_only=True)
    except Exception as exc:
        return {"creados": 0, "errores": [{"fila": 1, "error": gettext("Archivo Excel inválido: {exc}").format(exc=exc)}]}

    ws = wb.active
    filas = list(ws.iter_rows(values_only=True))
    wb.close()

    if not filas:
        return {"creados": 0, "errores": [{"fila": 1, "error": gettext("El archivo Excel está vacío.")}]}

    encabezados = [_limpiar_texto(h).lower() for h in filas[0]]
    indice = {nombre: idx for idx, nombre in enumerate(encabezados) if nombre}
    for obligatorio in ("codigo", "nombre", "precio"):
        if obligatorio not in indice:
            return {
                "creados": 0,
                "errores": [{"fila": 1, "error": gettext("Falta la columna obligatoria '{obligatorio}'.").format(obligatorio=obligatorio)}],
            }

    existentes = set(
        Producto.objects.filter(empresa=empresa).values_list("codigo", flat=True)
    )
    vistos_archivo = set()
    errores = []
    validados = []

    def _celda(fila, col):
        pos = indice.get(col)
        if pos is None or pos >= len(fila):
            return None
        return fila[pos]

    for num_fila, fila in enumerate(filas[1:], start=2):
        if all(c is None or _limpiar_texto(c) == "" for c in fila):
            continue
        codigo = _limpiar_texto(_celda(fila, "codigo"))
        nombre = _limpiar_texto(_celda(fila, "nombre"))
        categoria_nombre = _limpiar_texto(_celda(fila, "categoria")) or "General"

        errores_fila = []
        if not codigo:
            errores_fila.append(gettext("El código es obligatorio."))
        elif codigo in existentes:
            errores_fila.append(gettext("El código '{codigo}' ya existe en el catálogo.").format(codigo=codigo))
        elif codigo in vistos_archivo:
            errores_fila.append(gettext("El código '{codigo}' está duplicado en el archivo.").format(codigo=codigo))

        if not nombre:
            errores_fila.append(gettext("El nombre es obligatorio."))

        try:
            precio = _parsear_decimal(_celda(fila, "precio"), campo="precio")
        except ValueError as exc:
            errores_fila.append(str(exc))
            precio = Decimal("0")

        try:
            costo = _parsear_decimal(_celda(fila, "costo"), defecto=Decimal("0"), campo="costo")
        except ValueError as exc:
            errores_fila.append(str(exc))
            costo = Decimal("0")

        try:
            iva = _parsear_decimal(_celda(fila, "iva_porcentaje"), defecto=Decimal("0"), campo="iva_porcentaje")
            if iva > Decimal("100"):
                errores_fila.append(gettext("El IVA no puede superar 100%."))
        except ValueError as exc:
            errores_fila.append(str(exc))
            iva = Decimal("0")

        try:
            stock_minimo = _parsear_entero(_celda(fila, "stock_minimo"), defecto=0, campo="stock_minimo")
        except ValueError as exc:
            errores_fila.append(str(exc))
            stock_minimo = 0

        try:
            stock_inicial = _parsear_entero(_celda(fila, "stock_inicial"), defecto=0, campo="stock_inicial")
        except ValueError as exc:
            errores_fila.append(str(exc))
            stock_inicial = 0

        if errores_fila:
            errores.append({"fila": num_fila, "error": " ".join(errores_fila)})
            continue

        vistos_archivo.add(codigo)
        validados.append(
            {
                "codigo": codigo[:40],
                "nombre": nombre[:150],
                "categoria": categoria_nombre[:80],
                "precio": precio,
                "costo": costo,
                "iva_porcentaje": iva,
                "stock_minimo": stock_minimo,
                "stock_inicial": stock_inicial,
            }
        )

    if errores:
        return {"creados": 0, "errores": errores}

    bodega_destino = validar_bodega(empresa, bodega) if bodega else bodega_principal(empresa)
    creados = 0
    with transaction.atomic():
        for item in validados:
            categoria, _ = Categoria.objects.get_or_create(
                empresa=empresa,
                nombre=item["categoria"],
                defaults={"activa": True},
            )
            prod = Producto.objects.create(
                empresa=empresa,
                categoria=categoria,
                codigo=item["codigo"],
                nombre=item["nombre"],
                precio=item["precio"],
                iva_porcentaje=item["iva_porcentaje"],
                stock_minimo=item["stock_minimo"],
                activo=True,
            )
            if item["stock_inicial"] > 0:
                registrar_movimiento(
                    empresa=empresa,
                    producto=prod,
                    tipo=MovimientoInventario.Tipo.ENTRADA,
                    cantidad=item["stock_inicial"],
                    usuario=usuario,
                    referencia="Stock inicial Excel",
                    bodega=bodega_destino,
                )
            creados += 1

    return {"creados": creados, "errores": []}
