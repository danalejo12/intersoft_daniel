from django import forms

from .models import Categoria, Cliente, MovimientoInventario, Producto


class ClienteForm(forms.ModelForm):
    class Meta:
        model = Cliente
        # "empresa" NO está en la lista: la asigna el servidor (TenantMixin.form_valid)
        fields = ["tipo_documento", "numero_documento", "nombre", "email", "telefono", "direccion"]
        labels = {
            "tipo_documento": "Tipo de documento",
            "numero_documento": "Número de documento",
            "email": "Correo electrónico",
            "telefono": "Teléfono",
            "direccion": "Dirección",
        }

    def __init__(self, *args, empresa=None, **kwargs):
        # La vista nos pasa la empresa activa para poder validar duplicados
        super().__init__(*args, **kwargs)
        self.empresa = empresa
        # Opción vacía en español
        self.fields["tipo_documento"].choices = [("", "Selecciona el tipo")] + list(
            Cliente.TipoDocumento.choices
        )

    def clean_numero_documento(self):
        # clean_<campo> valida UN campo. Normalizamos: "1.020.304 050" -> "1020304050"
        numero = self.cleaned_data["numero_documento"]
        return numero.replace(".", "").replace(" ", "")

    def clean(self):
        # clean() valida VARIOS campos juntos (tipo + número)
        datos = super().clean()
        tipo = datos.get("tipo_documento")
        numero = datos.get("numero_documento")

        if tipo and numero and self.empresa:
            existe = (
                Cliente.objects
                .filter(empresa=self.empresa, tipo_documento=tipo, numero_documento=numero)
                .exclude(pk=self.instance.pk)   # al editar, no compararse consigo mismo
                .exists()
            )
            if existe:
                self.add_error("numero_documento", "Ya existe un cliente con este documento en tu empresa.")
        return datos


# ---------------------------------------------------------------
# Facturación: un formulario para el encabezado + un FORMSET para las líneas
# ---------------------------------------------------------------
class FacturaForm(forms.Form):
    """Encabezado de la factura. Es forms.Form (no ModelForm): no guarda nada solo."""

    cliente = forms.ModelChoiceField(
        queryset=Cliente.objects.none(),   # vacío aquí; se llena en __init__ con la empresa
        label="Cliente",
        empty_label="Selecciona el cliente",
    )

    def __init__(self, *args, empresa, **kwargs):
        super().__init__(*args, **kwargs)
        # Solo clientes de la empresa activa: un id de otra empresa será "opción no válida"
        self.fields["cliente"].queryset = (
            Cliente.objects.de_empresa(empresa).filter(activo=True).order_by("nombre")
        )


class LineaFacturaForm(forms.Form):
    """Una fila de la factura: producto + cantidad."""

    producto = forms.ModelChoiceField(queryset=Producto.objects.none(), label="Producto", empty_label="—")
    cantidad = forms.IntegerField(min_value=1, label="Cantidad")

    def __init__(self, *args, empresa, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["producto"].queryset = (
            Producto.objects.de_empresa(empresa).filter(activo=True).order_by("nombre")
        )
        # Cómo se ve cada opción del <select>
        self.fields["producto"].label_from_instance = (
            lambda p: f"{p.codigo} · {p.nombre} (stock: {p.stock})"
        )


class BaseLineasFormSet(forms.BaseFormSet):
    """Validaciones que miran TODAS las filas juntas."""

    def clean(self):
        super().clean()
        if any(self.errors):          # si alguna fila ya tiene errores, no seguimos
            return
        vistos = set()
        for form in self.forms:
            producto = form.cleaned_data.get("producto")
            if producto is None:      # fila vacía: se ignora
                continue
            if producto.pk in vistos:
                raise forms.ValidationError(
                    "Cada producto solo puede aparecer una vez. Suma las cantidades en una sola línea."
                )
            vistos.add(producto.pk)


# 5 filas: 1 obligatoria (min_num) + 4 opcionales (extra)
LineasFacturaFormSet = forms.formset_factory(
    LineaFacturaForm,
    formset=BaseLineasFormSet,
    extra=4,
    min_num=1,
    validate_min=True,
)


# ---------------------------------------------------------------
# Inventario
# ---------------------------------------------------------------
class ProductoForm(forms.ModelForm):
    class Meta:
        model = Producto
        # "stock" NO está: el stock solo cambia con movimientos (kardex), nunca a mano
        fields = ["codigo", "nombre", "categoria", "precio", "iva_porcentaje", "stock_minimo", "descripcion"]
        labels = {
            "codigo": "Código",
            "categoria": "Categoría",
            "iva_porcentaje": "IVA (%)",
            "stock_minimo": "Stock mínimo",
            "descripcion": "Descripción",
        }
        widgets = {"descripcion": forms.Textarea(attrs={"rows": 3})}

    # Campo EXTRA: no existe en el modelo. Solo se usa al crear.
    stock_inicial = forms.IntegerField(
        label="Stock inicial",
        min_value=0,
        initial=0,
        required=False,
        help_text="Unidades que tienes hoy. Se registra como una entrada en el kardex.",
    )

    # Orden en que se muestran los campos
    field_order = [
        "codigo", "nombre", "categoria", "precio", "iva_porcentaje",
        "stock_inicial", "stock_minimo", "descripcion",
    ]

    def __init__(self, *args, empresa=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.empresa = empresa
        # Al EDITAR no se muestra: el stock de un producto existente solo cambia con movimientos.
        # _state.adding es True solo si el producto aún no está guardado en la base.
        if not self.instance._state.adding:
            del self.fields["stock_inicial"]
        # Solo categorías de la empresa activa
        self.fields["categoria"].queryset = (
            Categoria.objects.de_empresa(empresa).filter(activa=True).order_by("nombre")
        )
        self.fields["categoria"].empty_label = "Sin categoría"

    def clean_codigo(self):
        # Normalizamos: " p-001 " -> "P-001", y validamos que no se repita en la empresa
        codigo = self.cleaned_data["codigo"].strip().upper()
        existe = (
            Producto.objects
            .filter(empresa=self.empresa, codigo=codigo)
            .exclude(pk=self.instance.pk)
            .exists()
        )
        if existe:
            raise forms.ValidationError("Ya existe un producto con este código en tu empresa.")
        return codigo


class MovimientoForm(forms.Form):
    """Entrada o ajuste de stock. Las SALIDAS solo ocurren al facturar."""

    tipo = forms.ChoiceField(
        label="Tipo de movimiento",
        choices=[
            (MovimientoInventario.Tipo.ENTRADA, "Entrada (compra a proveedor, devolución)"),
            (MovimientoInventario.Tipo.AJUSTE, "Ajuste (conteo físico, daño, pérdida)"),
        ],
    )
    cantidad = forms.IntegerField(
        label="Cantidad",
        help_text="En un ajuste usa un número negativo para restar. Ejemplo: -2.",
    )
    referencia = forms.CharField(
        label="Referencia", max_length=60, required=False,
        help_text="Ejemplo: Factura proveedor 4521, Conteo de fin de mes.",
    )

    def clean(self):
        datos = super().clean()
        tipo = datos.get("tipo")
        cantidad = datos.get("cantidad")
        if cantidad is not None:
            if tipo == MovimientoInventario.Tipo.ENTRADA and cantidad <= 0:
                self.add_error("cantidad", "Una entrada debe ser mayor que cero.")
            if tipo == MovimientoInventario.Tipo.AJUSTE and cantidad == 0:
                self.add_error("cantidad", "Un ajuste no puede ser cero.")
        return datos