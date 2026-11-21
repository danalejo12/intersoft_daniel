from django.utils.text import format_lazy
from django.utils.translation import gettext, gettext_lazy
from django import forms
from django.core.files.uploadedfile import UploadedFile

from .models import (
    FOTOS_EXTRA_MAXIMO, Bodega, Categoria, Cliente, Empresa, FotoProducto, MovimientoInventario, Producto, Usuario,
)

IMAGEN_TAMANO_MAXIMO = 5 * 1024 * 1024  # 5 MB


class ClienteForm(forms.ModelForm):
    class Meta:
        model = Cliente
        # "empresa" NO está en la lista: la asigna el servidor (TenantMixin.form_valid)
        fields = ["tipo_documento", "numero_documento", "nombre", "email", "telefono", "direccion"]
        labels = {
            "tipo_documento": gettext_lazy("Tipo de documento"),
            "numero_documento": gettext_lazy("Número de documento"),
            "email": gettext_lazy("Correo electrónico"),
            "telefono": gettext_lazy("Teléfono"),
            "direccion": gettext_lazy("Dirección"),
        }

    def __init__(self, *args, empresa=None, **kwargs):
        # La vista nos pasa la empresa activa para poder validar duplicados
        super().__init__(*args, **kwargs)
        self.empresa = empresa
        # Opción vacía en español
        self.fields["tipo_documento"].choices = [("", gettext("Selecciona el tipo"))] + list(
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
                self.add_error("numero_documento", gettext("Ya existe un cliente con este documento en tu empresa."))
        return datos


# ---------------------------------------------------------------
# Facturación: un formulario para el encabezado + un FORMSET para las líneas
# ---------------------------------------------------------------
class FacturaForm(forms.Form):
    """Encabezado de la factura. Es forms.Form (no ModelForm): no guarda nada solo."""

    cliente = forms.ModelChoiceField(
        queryset=Cliente.objects.none(),   # vacío aquí; se llena en __init__ con la empresa
        label=gettext_lazy("Cliente"),
        empty_label=gettext_lazy("Selecciona el cliente"),
    )

    def __init__(self, *args, empresa, **kwargs):
        super().__init__(*args, **kwargs)
        # Solo clientes de la empresa activa: un id de otra empresa será "opción no válida"
        self.fields["cliente"].queryset = (
            Cliente.objects.de_empresa(empresa).filter(activo=True).order_by("nombre")
        )


class LineaFacturaForm(forms.Form):
    """Una fila de la factura: producto + cantidad."""

    producto = forms.ModelChoiceField(queryset=Producto.objects.none(), label=gettext_lazy("Producto"), empty_label="—")
    cantidad = forms.IntegerField(min_value=1, label=gettext_lazy("Cantidad"))

    def __init__(self, *args, empresa, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["producto"].queryset = (
            Producto.objects.de_empresa(empresa).filter(activo=True).order_by("nombre")
        )
        # Cómo se ve cada opción del <select>
        self.fields["producto"].label_from_instance = (
            lambda p: gettext("{codigo} · {nombre} (stock: {stock})").format(codigo=p.codigo, nombre=p.nombre, stock=p.stock)
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
                    gettext("Cada producto solo puede aparecer una vez. Suma las cantidades en una sola línea.")
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
        labels = {"nombre": gettext_lazy("Nombre de la categoría")}

    def __init__(self, *args, empresa=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.empresa = empresa

    def clean_nombre(self):
        nombre = self.cleaned_data["nombre"].strip()
        if not nombre:
            raise forms.ValidationError(gettext("El nombre de la categoría no puede estar vacío."))
        if self.empresa is not None:
            existe = (
                Categoria.objects.filter(empresa=self.empresa, nombre__iexact=nombre)
                .exclude(pk=self.instance.pk)
                .exists()
            )
            if existe:
                raise forms.ValidationError(gettext("Ya existe una categoría con este nombre en tu empresa."))
        return nombre


class EntradaVariasFotos(forms.ClearableFileInput):
    allow_multiple_selected = True


class CampoVariasFotos(forms.ImageField):
    """Varias imágenes en un solo campo: cada una se valida como imagen real (Pillow)."""

    widget = EntradaVariasFotos(attrs={"accept": "image/jpeg,image/png,image/webp"})

    def clean(self, data, initial=None):
        archivos = data if isinstance(data, (list, tuple)) else ([data] if data else [])
        limpios = []
        for archivo in archivos:
            limpio = super().clean(archivo, initial)
            if limpio.size > IMAGEN_TAMANO_MAXIMO:
                raise forms.ValidationError(gettext("«{name}» pesa más de 5 MB.").format(name=limpio.name))
            limpios.append(limpio)
        return limpios


class FotoParaQuitar(forms.ModelMultipleChoiceField):
    def label_from_instance(self, foto):
        return foto.imagen.url  # la plantilla la muestra como miniatura


class ProductoForm(forms.ModelForm):
    class Meta:
        model = Producto
        # "stock" NO está: el stock solo cambia con movimientos (kardex), nunca a mano
        fields = [
            "codigo", "nombre", "categoria", "precio", "iva_porcentaje",
            "stock_minimo", "peso_gramos", "descripcion", "imagen", "publicado",
        ]
        labels = {
            "codigo": gettext_lazy("Código"),
            "categoria": gettext_lazy("Categoría"),
            "iva_porcentaje": gettext_lazy("IVA (%)"),
            "stock_minimo": gettext_lazy("Stock mínimo"),
            "peso_gramos": gettext_lazy("Peso por unidad (gramos)"),
            "descripcion": gettext_lazy("Descripción"),
            "publicado": gettext_lazy("Publicar en el marketplace"),
        }
        help_texts = {
            "peso_gramos": gettext_lazy("Opcional. Se usa para calcular el envío por peso (0 si no aplica)."),
            "publicado": gettext_lazy("Si lo marcas, cualquier persona podrá ver este producto en el catálogo."),
            "imagen": gettext_lazy("JPG, PNG o WEBP, máximo 5 MB."),
        }
        widgets = {"descripcion": forms.Textarea(attrs={"rows": 3})}

    # Campo EXTRA: no existe en el modelo. Solo se usa al crear.
    stock_inicial = forms.IntegerField(
        label=gettext_lazy("Stock inicial"),
        min_value=0,
        initial=0,
        required=False,
        help_text=gettext_lazy("Unidades que tienes hoy. Se registra como una entrada en el kardex."),
    )

    fotos_extra = CampoVariasFotos(
        label=gettext_lazy("Más fotos (galería)"),
        required=False,
        help_text=format_lazy(gettext_lazy("Hasta {maximo} fotos más: otros ángulos, el corte, el empaque. JPG, PNG o WEBP de hasta 5 MB."), maximo=FOTOS_EXTRA_MAXIMO),
    )
    quitar_fotos = FotoParaQuitar(
        label=gettext_lazy("Fotos de la galería"),
        queryset=FotoProducto.objects.none(),
        required=False,
        widget=forms.CheckboxSelectMultiple,
        help_text=gettext_lazy("Marca las que quieras quitar."),
    )

    # Orden en que se muestran los campos
    field_order = [
        "codigo", "nombre", "categoria", "precio", "iva_porcentaje",
        "stock_inicial", "stock_minimo", "peso_gramos", "descripcion", "imagen",
        "quitar_fotos", "fotos_extra", "publicado",
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
        self.fields["categoria"].empty_label = gettext("Sin categoría")
        if self.instance._state.adding or not self.instance.fotos.exists():
            del self.fields["quitar_fotos"]
        else:
            self.fields["quitar_fotos"].queryset = self.instance.fotos.all()

    def clean(self):
        datos = super().clean()
        actuales = 0 if self.instance._state.adding else self.instance.fotos.count()
        quitadas = len(datos.get("quitar_fotos") or [])
        nuevas = len(datos.get("fotos_extra") or [])
        if actuales - quitadas + nuevas > FOTOS_EXTRA_MAXIMO:
            self.add_error("fotos_extra", gettext("La galería admite hasta {fotos_extra_maximo} fotos además de la principal.").format(fotos_extra_maximo=FOTOS_EXTRA_MAXIMO))
        return datos

    def clean_peso_gramos(self):
        return self.cleaned_data.get("peso_gramos") or 0

    def clean_imagen(self):
        imagen = self.cleaned_data.get("imagen")
        if isinstance(imagen, UploadedFile) and imagen.size > IMAGEN_TAMANO_MAXIMO:
            raise forms.ValidationError(gettext("La imagen no puede pesar más de 5 MB."))
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
            raise forms.ValidationError(gettext("Ya existe un producto con este código en tu empresa."))
        return codigo


class DatosNegocioForm(forms.ModelForm):
    """Datos legales, identidad pública y logística que ve el comprador. El nombre y el NIT no se cambian desde aquí."""

    quitar_logo = forms.BooleanField(required=False, label=gettext_lazy("Quitar logo actual"))

    class Meta:
        model = Empresa
        fields = [
            "logo",
            "direccion",
            "telefono",
            "email",
            "sitio_web",
            "descripcion",
            "tarifa_envio_base",
            "tarifa_envio_por_kg",
            "envio_gratis_desde",
        ]
        labels = {
            "logo": gettext_lazy("Logo del negocio"),
            "direccion": gettext_lazy("Dirección de notificaciones"),
            "telefono": gettext_lazy("Teléfono"),
            "email": gettext_lazy("Correo del negocio"),
            "sitio_web": gettext_lazy("Sitio web o red social"),
            "descripcion": gettext_lazy("Descripción pública del negocio"),
            "tarifa_envio_base": gettext_lazy("Tarifa base de envío ($)"),
            "tarifa_envio_por_kg": gettext_lazy("Recargo por kilogramo ($)"),
            "envio_gratis_desde": gettext_lazy("Envío gratis desde ($)"),
        }
        widgets = {
            "logo": forms.FileInput(
                attrs={"accept": "image/jpeg,image/png,image/webp", "class": "perfil-input-archivo"}
            ),
            "sitio_web": forms.URLInput(attrs={"placeholder": gettext_lazy("https://tu-tienda.com o Instagram")}),
            "descripcion": forms.Textarea(
                attrs={
                    "rows": 3,
                    "placeholder": gettext_lazy("Describe qué vende tu negocio, horarios de atención o tiempos de despacho..."),
                }
            ),
        }
        help_texts = {
            "logo": gettext_lazy("Formatos JPG, PNG o WebP · Tamaño máximo 5 MB."),
            "tarifa_envio_base": gettext_lazy("Deja 0 si coordinas el envío directamente o no cobras tarifa base."),
            "tarifa_envio_por_kg": gettext_lazy("Valor adicional por cada kg (o fracción) según el peso de los productos."),
            "envio_gratis_desde": gettext_lazy("Si los productos del pedido alcanzan este monto, el envío cuesta $0."),
        }

    def __init__(self, *args, **kwargs):
        from .forms_tienda import hacer_obligatorios_datos_legales  # evita una importación circular

        super().__init__(*args, **kwargs)
        hacer_obligatorios_datos_legales(self)
        for campo in ("tarifa_envio_base", "tarifa_envio_por_kg", "envio_gratis_desde"):
            self.fields[campo].required = False

    def clean_logo(self):
        archivo = self.cleaned_data.get("logo")
        if isinstance(archivo, UploadedFile) and archivo.size > IMAGEN_TAMANO_MAXIMO:
            raise forms.ValidationError(gettext("El logo no puede superar los 5 MB."))
        return archivo

    def save(self, commit=True):
        empresa = super().save(commit=False)
        if self.cleaned_data.get("quitar_logo") and not isinstance(self.cleaned_data.get("logo"), UploadedFile):
            empresa.logo = None
        if commit:
            empresa.save()
        return empresa

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

    def __init__(self, *args, empresa=None, **kwargs):
        super().__init__(*args, **kwargs)
        activas = Bodega.objects.filter(empresa=empresa, activa=True) if empresa else Bodega.objects.none()
        if activas.count() > 1:
            self.fields["bodega"] = forms.ModelChoiceField(
                label=gettext("Bodega"), queryset=activas, initial=activas.filter(es_principal=True).first(),
                empty_label=None,
            )

    tipo = forms.ChoiceField(
        label=gettext_lazy("Tipo de movimiento"),
        choices=[
            (MovimientoInventario.Tipo.ENTRADA, gettext_lazy("Entrada (compra a proveedor, devolución)")),
            (MovimientoInventario.Tipo.AJUSTE, gettext_lazy("Ajuste (conteo físico, daño, pérdida)")),
        ],
    )
    cantidad = forms.IntegerField(
        label=gettext_lazy("Cantidad"),
        help_text=gettext_lazy("En un ajuste usa un número negativo para restar. Ejemplo: -2."),
    )
    referencia = forms.CharField(
        label=gettext_lazy("Referencia"), max_length=60, required=False,
        help_text=gettext_lazy("Ejemplo: Factura proveedor 4521, Conteo de fin de mes."),
    )

    def clean(self):
        datos = super().clean()
        tipo = datos.get("tipo")
        cantidad = datos.get("cantidad")
        if cantidad is not None:
            if tipo == MovimientoInventario.Tipo.ENTRADA and cantidad <= 0:
                self.add_error("cantidad", gettext("Una entrada debe ser mayor que cero."))
            if tipo == MovimientoInventario.Tipo.AJUSTE and cantidad == 0:
                self.add_error("cantidad", gettext("Un ajuste no puede ser cero."))
        return datos


class PerfilUsuarioForm(forms.ModelForm):
    quitar_foto = forms.BooleanField(required=False, label=gettext_lazy("Quitar foto actual"))

    class Meta:
        model = Usuario
        fields = ["foto", "first_name", "last_name", "cargo", "telefono", "descripcion"]
        labels = {
            "foto": gettext_lazy("Foto de perfil"),
            "first_name": gettext_lazy("Nombres"),
            "last_name": gettext_lazy("Apellidos"),
            "cargo": gettext_lazy("Cargo o especialidad"),
            "telefono": gettext_lazy("Teléfono de contacto"),
            "descripcion": gettext_lazy("Sobre mí / descripción"),
        }
        widgets = {
            "foto": forms.FileInput(
                attrs={"accept": "image/jpeg,image/png,image/webp", "class": "perfil-input-archivo"}
            ),
            "descripcion": forms.Textarea(
                attrs={"rows": 4, "placeholder": gettext_lazy("Cuéntanos brevemente sobre ti, tu rol o tu experiencia...")}
            ),
            "cargo": forms.TextInput(attrs={"placeholder": gettext_lazy("Ej. Administrador, Asesor comercial, Contador...")}),
            "telefono": forms.TextInput(attrs={"placeholder": gettext_lazy("Ej. 300 123 4567")}),
        }
        help_texts = {
            "foto": gettext_lazy("Formatos JPG, PNG o WebP · Tamaño máximo 5 MB."),
        }

    def clean_first_name(self):
        valor = (self.cleaned_data.get("first_name") or "").strip()
        if not valor:
            raise forms.ValidationError(gettext("Ingresa tu nombre."))
        return valor

    def clean_last_name(self):
        return (self.cleaned_data.get("last_name") or "").strip()

    def clean_foto(self):
        archivo = self.cleaned_data.get("foto")
        if isinstance(archivo, UploadedFile) and archivo.size > IMAGEN_TAMANO_MAXIMO:
            raise forms.ValidationError(gettext("La foto no puede superar los 5 MB."))
        return archivo

    def save(self, commit=True):
        usuario = super().save(commit=False)
        if self.cleaned_data.get("quitar_foto") and not isinstance(self.cleaned_data.get("foto"), UploadedFile):
            usuario.foto = None
        if commit:
            usuario.save()
        return usuario

class BodegaForm(forms.Form):
    nombre = forms.CharField(label=gettext_lazy("Nombre"), max_length=80, help_text=gettext_lazy("Ejemplo: Bodega norte, Local centro."))
    direccion = forms.CharField(label=gettext_lazy("Dirección"), max_length=200, required=False)
    es_principal = forms.BooleanField(
        label=gettext_lazy("Bodega principal"), required=False,
        help_text=gettext_lazy("Recibe las compras y la producción, y es la bodega por defecto en el panel."),
    )
    vende_en_linea = forms.BooleanField(
        label=gettext_lazy("Vende en línea"), required=False,
        help_text=gettext_lazy("El marketplace reserva el stock de esta bodega."),
    )


class TrasladoForm(forms.Form):
    origen = forms.ModelChoiceField(label=gettext_lazy("Desde"), queryset=Bodega.objects.none(), empty_label=None)
    destino = forms.ModelChoiceField(label=gettext_lazy("Hacia"), queryset=Bodega.objects.none(), empty_label=None)
    cantidad = forms.IntegerField(label=gettext_lazy("Cantidad"), min_value=1, max_value=999999)

    def __init__(self, *args, empresa, **kwargs):
        super().__init__(*args, **kwargs)
        activas = Bodega.objects.filter(empresa=empresa, activa=True)
        self.fields["origen"].queryset = activas
        self.fields["destino"].queryset = activas

    def clean(self):
        datos = super().clean()
        if datos.get("origen") and datos.get("origen") == datos.get("destino"):
            self.add_error("destino", gettext("Elige una bodega distinta a la de origen."))
        return datos
