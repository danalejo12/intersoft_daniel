from django import forms
from django.core.files.uploadedfile import UploadedFile

from .models import Categoria, Cliente, Empresa, MovimientoInventario, Producto

IMAGEN_TAMANO_MAXIMO = 5 * 1024 * 1024  # 5 MB


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
# Inventario: Categorías y Productos
# ---------------------------------------------------------------
class CategoriaForm(forms.ModelForm):
    class Meta:
        model = Categoria
        fields = ["nombre"]
        labels = {"nombre": "Nombre de la categoría"}

    def __init__(self, *args, empresa=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.empresa = empresa

    def clean_nombre(self):
        nombre = self.cleaned_data["nombre"].strip()
        if not nombre:
            raise forms.ValidationError("El nombre de la categoría no puede estar vacío.")
        if self.empresa is not None:
            existe = (
                Categoria.objects.filter(empresa=self.empresa, nombre__iexact=nombre)
                .exclude(pk=self.instance.pk)
                .exists()
            )
            if existe:
                raise forms.ValidationError("Ya existe una categoría con este nombre en tu empresa.")
        return nombre


class ProductoForm(forms.ModelForm):
    class Meta:
        model = Producto
        # "stock" NO está: el stock solo cambia con movimientos (kardex), nunca a mano
        fields = [
            "codigo", "nombre", "categoria", "precio", "iva_porcentaje",
            "stock_minimo", "peso_gramos", "descripcion", "imagen", "publicado",
        ]
        labels = {
            "codigo": "Código",
            "categoria": "Categoría",
            "iva_porcentaje": "IVA (%)",
            "stock_minimo": "Stock mínimo",
            "peso_gramos": "Peso por unidad (gramos)",
            "descripcion": "Descripción",
            "publicado": "Publicar en el marketplace",
        }
        help_texts = {
            "peso_gramos": "Opcional. Se usa para calcular el envío por peso (0 si no aplica).",
            "publicado": "Si lo marcas, cualquier persona podrá ver este producto en el catálogo.",
            "imagen": "JPG, PNG o WEBP, máximo 5 MB.",
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
        "stock_inicial", "stock_minimo", "peso_gramos", "descripcion", "imagen", "publicado",
    ]

    def __init__(self, *args, empresa=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.empresa = empresa
        self.fields["peso_gramos"].required = False
        # Al EDITAR no se muestra: el stock de un producto existente solo cambia con movimientos.
        # _state.adding es True solo si el producto aún no está guardado en la base.
        if not self.instance._state.adding:
            del self.fields["stock_inicial"]
        # Solo categorías de la empresa activa
        self.fields["categoria"].queryset = (
            Categoria.objects.de_empresa(empresa).filter(activa=True).order_by("nombre")
        )
        self.fields["categoria"].empty_label = "Sin categoría"

    def clean_peso_gramos(self):
        return self.cleaned_data.get("peso_gramos") or 0

    def clean_imagen(self):
        imagen = self.cleaned_data.get("imagen")
        if isinstance(imagen, UploadedFile) and imagen.size > IMAGEN_TAMANO_MAXIMO:
            raise forms.ValidationError("La imagen no puede pesar más de 5 MB.")
        # False = el usuario marcó "limpiar". Si la foto cambia, el crédito de la anterior ya no aplica
        if imagen is False or isinstance(imagen, UploadedFile):
            self.instance.imagen_credito = ""
            self.instance.imagen_fuente = ""
        return imagen

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


class DatosNegocioForm(forms.ModelForm):
    """Datos legales y de logística que ve el comprador. El nombre y el NIT no se cambian desde aquí."""

    class Meta:
        model = Empresa
        fields = [
            "direccion",
            "telefono",
            "email",
            "tarifa_envio_base",
            "tarifa_envio_por_kg",
            "envio_gratis_desde",
        ]
        labels = {
            "direccion": "Dirección de notificaciones",
            "telefono": "Teléfono",
            "email": "Correo del negocio",
            "tarifa_envio_base": "Tarifa base de envío ($)",
            "tarifa_envio_por_kg": "Recargo por kilogramo ($)",
            "envio_gratis_desde": "Envío gratis desde ($)",
        }
        help_texts = {
            "tarifa_envio_base": "Deja 0 si coordinas el envío directamente o no cobras tarifa base.",
            "tarifa_envio_por_kg": "Valor adicional por cada kg (o fracción) según el peso de los productos.",
            "envio_gratis_desde": "Si los productos del pedido alcanzan este monto, el envío cuesta $0.",
        }

    def __init__(self, *args, **kwargs):
        from .forms_tienda import hacer_obligatorios_datos_legales  # evita una importación circular

        super().__init__(*args, **kwargs)
        hacer_obligatorios_datos_legales(self)
        for campo in ("tarifa_envio_base", "tarifa_envio_por_kg", "envio_gratis_desde"):
            self.fields[campo].required = False

    def clean_tarifa_envio_base(self):
        from decimal import Decimal
        return self.cleaned_data.get("tarifa_envio_base") or Decimal("0")

    def clean_tarifa_envio_por_kg(self):
        from decimal import Decimal
        return self.cleaned_data.get("tarifa_envio_por_kg") or Decimal("0")

    def clean_envio_gratis_desde(self):
        from decimal import Decimal
        return self.cleaned_data.get("envio_gratis_desde") or Decimal("0")


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