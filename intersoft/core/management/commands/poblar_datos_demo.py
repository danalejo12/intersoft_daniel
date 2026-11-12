"""Puebla una empresa (por defecto la de Miguel Angel Ortiz Castillo) con datos realistas e imágenes reales."""
import io
import random
import urllib.request
import uuid
from datetime import timedelta
from decimal import Decimal

from django.core.files.base import ContentFile
from django.core.management.base import BaseCommand
from django.db import transaction
from django.utils import timezone
from PIL import Image, ImageDraw

from core import erp_services, services
from core.contabilidad_automatica import (
    asegurar_cuentas_puc,
    calcular_aportes_nomina_colombia,
    contabilizar_compra,
    contabilizar_factura,
    contabilizar_movimiento_tesoreria,
    contabilizar_nomina,
)
from core.facturacion_electronica import emitir_factura_electronica
from core.models import (
    Categoria,
    Cita,
    Cliente,
    Compra,
    CuentaCartera,
    CuentaTesoreria,
    DetallePedido,
    Empleado,
    Empresa,
    Factura,
    LineaCompra,
    LiquidacionNomina,
    Membresia,
    Pedido,
    Producto,
    Proveedor,
    Servicio,
    Usuario,
)
from core.permisos import sincronizar_catalogo_permisos


PRODUCTOS_DEMO = [
    {
        "categoria": "Computadores y Portátiles",
        "codigo": "LAP-PRO-14",
        "nombre": "Portátil Ultrabook Pro 14\" Ryzen 7 16GB 1TB SSD",
        "descripcion": "Portátil empresarial ultraligero con pantalla IPS antirreflejo, chasis de aluminio, 16 GB RAM DDR5 y unidad SSD NVMe de 1 TB.",
        "precio": Decimal("3890000.00"),
        "costo": Decimal("2950000.00"),
        "stock": 14,
        "stock_minimo": 4,
        "peso_gramos": 1450,
        "url_imagen": "https://images.unsplash.com/photo-1517336714731-489689fd1ca8?auto=format&fit=crop&w=900&q=82",
        "credito": "Foto de Dmitry Chernyshov en Unsplash",
        "fuente": "https://unsplash.com/photos/mP7aPSUm7aE",
    },
    {
        "categoria": "Computadores y Portátiles",
        "codigo": "PC-WORK-01",
        "nombre": "Estación de Trabajo Core i7 32GB RTX 4060",
        "descripcion": "Torre de alto rendimiento para diseño, arquitectura y desarrollo de software con refrigeración silenciosa.",
        "precio": Decimal("5200000.00"),
        "costo": Decimal("4100000.00"),
        "stock": 8,
        "stock_minimo": 3,
        "peso_gramos": 7800,
        "url_imagen": "https://images.unsplash.com/photo-1587202372775-e229f172b9d7?auto=format&fit=crop&w=900&q=82",
        "credito": "Foto de Christian Wiediger en Unsplash",
        "fuente": "https://unsplash.com/photos/WkfDrhxDMC8",
    },
    {
        "categoria": "Monitores y Pantallas",
        "codigo": "MON-4K-27",
        "nombre": "Monitor Profesional 27\" 4K UHD USB-C IPS",
        "descripcion": "Monitor sin bordes con calibración de color 99% sRGB, puerto USB-C con carga de 65W y soporte ergonómico ajustable.",
        "precio": Decimal("1450000.00"),
        "costo": Decimal("1020000.00"),
        "stock": 18,
        "stock_minimo": 5,
        "peso_gramos": 5200,
        "url_imagen": "https://images.unsplash.com/photo-1527443224154-c4a3942d3acf?auto=format&fit=crop&w=900&q=82",
        "credito": "Foto de Quaritsch Photography en Unsplash",
        "fuente": "https://unsplash.com/photos/m2zuB8DqwyM",
    },
    {
        "categoria": "Periféricos y Gaming",
        "codigo": "TEC-MEC-RGB",
        "nombre": "Teclado Mecánico Inalámbrico Hot-Swap TKL",
        "descripcion": "Teclado mecánico compacto con switches táctiles silenciosos, triple conexión (Bluetooth, 2.4 GHz y USB-C) y teclas PBT.",
        "precio": Decimal("380000.00"),
        "costo": Decimal("240000.00"),
        "stock": 25,
        "stock_minimo": 6,
        "peso_gramos": 880,
        "url_imagen": "https://images.unsplash.com/photo-1587829741301-dc798b83add3?auto=format&fit=crop&w=900&q=82",
        "credito": "Foto de Sergi Kabrera en Unsplash",
        "fuente": "https://unsplash.com/photos/2xU7rYxsTiM",
    },
    {
        "categoria": "Periféricos y Gaming",
        "codigo": "MOU-ERG-PRO",
        "nombre": "Mouse Ergonómico Inalámbrico 8000 DPI Recargable",
        "descripcion": "Mouse de precisión con rueda electromagnética silenciosa, conexión multidispositivo y batería de hasta 70 días.",
        "precio": Decimal("320000.00"),
        "costo": Decimal("210000.00"),
        "stock": 3,
        "stock_minimo": 6,
        "peso_gramos": 145,
        "url_imagen": "https://images.unsplash.com/photo-1527864550417-7fd91fc51a46?auto=format&fit=crop&w=900&q=82",
        "credito": "Foto de Oscar Ivan Esquivel Arteaga en Unsplash",
        "fuente": "https://unsplash.com/photos/ZtxED1cpB1E",
    },
    {
        "categoria": "Audio y Accesorios",
        "codigo": "AUD-ANC-PRO",
        "nombre": "Audífonos Inalámbricos con Cancelación Activa ANC",
        "descripcion": "Diadema circumaural Bluetooth 5.3 con cancelación de ruido híbrida, micrófonos con IA para llamadas y 40 horas de autonomía.",
        "precio": Decimal("640000.00"),
        "costo": Decimal("430000.00"),
        "stock": 19,
        "stock_minimo": 5,
        "peso_gramos": 260,
        "url_imagen": "https://images.unsplash.com/photo-1505740420928-5e560c06d30e?auto=format&fit=crop&w=900&q=82",
        "credito": "Foto de C D-X en Unsplash",
        "fuente": "https://unsplash.com/photos/PDX_a_82obo",
    },
    {
        "categoria": "Redes y Conectividad",
        "codigo": "ROU-WIFI6-AX",
        "nombre": "Router Mesh Wi-Fi 6 AX3000 Doble Banda Gigabit",
        "descripcion": "Cobertura empresarial de alta densidad para hasta 150 dispositivos simultáneos con seguridad WPA3 y puertos Gigabit.",
        "precio": Decimal("460000.00"),
        "costo": Decimal("310000.00"),
        "stock": 2,
        "stock_minimo": 5,
        "peso_gramos": 690,
        "url_imagen": "https://images.unsplash.com/photo-1544197150-b99a580bb7a8?auto=format&fit=crop&w=900&q=82",
        "credito": "Foto de Jordan Harrison en Unsplash",
        "fuente": "https://unsplash.com/photos/40XgDxBfYXM",
    },
    {
        "categoria": "Audio y Accesorios",
        "codigo": "CAM-STREAM-4K",
        "nombre": "Cámara Web 4K Ultra HD con Autofoco y Doble Micrófono",
        "descripcion": "Cámara profesional para videoconferencias con corrección automática de luz HDR y tapa de privacidad integrada.",
        "precio": Decimal("410000.00"),
        "costo": Decimal("270000.00"),
        "stock": 15,
        "stock_minimo": 4,
        "peso_gramos": 210,
        "url_imagen": "https://images.unsplash.com/photo-1589739900243-4b52cd9b104e?auto=format&fit=crop&w=900&q=82",
        "credito": "Foto de Unsplash",
        "fuente": "https://unsplash.com",
    },
    {
        "categoria": "Sillas y Oficina",
        "codigo": "SIL-ERGO-MESH",
        "nombre": "Silla Ergonómica Ejecutiva en Malla con Soporte Lumbar",
        "descripcion": "Silla certificada para jornadas extensas con cabecero 3D, brazos ajustables, reclinación 135° y base cromada.",
        "precio": Decimal("890000.00"),
        "costo": Decimal("590000.00"),
        "stock": 11,
        "stock_minimo": 3,
        "peso_gramos": 14200,
        "url_imagen": "https://images.unsplash.com/photo-1580480055273-228ff5388ef8?auto=format&fit=crop&w=900&q=82",
        "credito": "Foto de Daiga Ellaby en Unsplash",
        "fuente": "https://unsplash.com/photos/ClWvcrk1MY4",
    },
    {
        "categoria": "Periféricos y Gaming",
        "codigo": "SSD-NVME-2TB",
        "nombre": "Unidad SSD Externa Portátil NVMe USB 3.2 de 2TB",
        "descripcion": "Almacenamiento de bolsillo resistente a golpes con velocidades de transferencia de hasta 1050 MB/s.",
        "precio": Decimal("590000.00"),
        "costo": Decimal("410000.00"),
        "stock": 16,
        "stock_minimo": 4,
        "peso_gramos": 95,
        "url_imagen": "https://images.unsplash.com/photo-1597872200969-2b65d56bd16b?auto=format&fit=crop&w=900&q=82",
        "credito": "Foto de Samsung Memory en Unsplash",
        "fuente": "https://unsplash.com/photos/usR7n6A1I2w",
    },
]


def descargar_o_generar_imagen(url, titulo):
    """Descarga una foto real en JPG desde Unsplash; si no hay red, genera un JPG limpio."""
    try:
        req = urllib.request.Request(
            url,
            headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) IntersoftDemo/1.0"},
        )
        with urllib.request.urlopen(req, timeout=12) as resp:
            datos = resp.read()
        img = Image.open(io.BytesIO(datos)).convert("RGB")
        img.thumbnail((900, 675))
        salida = io.BytesIO()
        img.save(salida, format="JPEG", quality=86)
        return salida.getvalue()
    except Exception:
        img = Image.new("RGB", (800, 600), color=(30, 58, 138))
        draw = ImageDraw.Draw(img)
        draw.rectangle([40, 40, 760, 560], outline=(255, 90, 31), width=4)
        draw.text((80, 280), titulo[:40], fill=(255, 255, 255))
        salida = io.BytesIO()
        img.save(salida, format="JPEG", quality=85)
        return salida.getvalue()


class Command(BaseCommand):
    help = "Puebla la cuenta de Miguel Angel Ortiz Castillo (o la empresa indicada) con datos e imágenes reales."

    def add_arguments(self, parser):
        parser.add_argument(
            "--email",
            default="miguel2007ortiz@gmail.com",
            help="Correo del usuario administrador objetivo.",
        )

    def handle(self, *args, **options):
        sincronizar_catalogo_permisos()
        email = options["email"]
        usuario = Usuario.objects.filter(email__iexact=email).first()
        if not usuario:
            usuario = Usuario.objects.filter(first_name__icontains="Miguel").first()
        if not usuario:
            self.stderr.write(self.style.ERROR("No se encontró el usuario objetivo."))
            return

        membresia = (
            Membresia.objects.filter(usuario=usuario, activa=True)
            .select_related("empresa", "rol")
            .first()
        )
        if not membresia:
            self.stderr.write(self.style.ERROR("El usuario no tiene una membresía activa."))
            return

        empresa = membresia.empresa
        if not empresa.direccion or not empresa.telefono:
            empresa.direccion = empresa.direccion or "Calle 54 Sur # 71B-68, Bogotá D.C."
            empresa.telefono = empresa.telefono or "3223876845"
            empresa.save(update_fields=["direccion", "telefono"])

        self.stdout.write(f"Poblando datos para: {usuario.get_full_name()} · Empresa: {empresa.nombre}...")

        with transaction.atomic():
            asegurar_cuentas_puc(empresa=empresa)

            # 1. Categorías
            mapa_categorias = {}
            for item in PRODUCTOS_DEMO:
                nombre_cat = item["categoria"]
                if nombre_cat not in mapa_categorias:
                    cat, _ = Categoria.objects.get_or_create(
                        empresa=empresa,
                        nombre=nombre_cat,
                        defaults={"activa": True},
                    )
                    mapa_categorias[nombre_cat] = cat

            # 2. Productos con imágenes reales
            productos_creados = []
            for item in PRODUCTOS_DEMO:
                prod, creado = Producto.objects.get_or_create(
                    empresa=empresa,
                    codigo=item["codigo"],
                    defaults={
                        "categoria": mapa_categorias[item["categoria"]],
                        "nombre": item["nombre"],
                        "descripcion": item["descripcion"],
                        "precio": item["precio"],
                        "iva_porcentaje": Decimal("19.00"),
                        "stock": item["stock"],
                        "stock_minimo": item["stock_minimo"],
                        "peso_gramos": item["peso_gramos"],
                        "activo": True,
                        "publicado": True,
                        "imagen_credito": item["credito"],
                        "imagen_fuente": item["fuente"],
                    },
                )
                if not prod.imagen:
                    bytes_jpg = descargar_o_generar_imagen(item["url_imagen"], item["nombre"])
                    prod.imagen.save(f"{item['codigo'].lower()}.jpg", ContentFile(bytes_jpg), save=True)
                    self.stdout.write(f"  + Imagen real guardada para {prod.codigo} ({len(bytes_jpg) // 1024} KB)")
                productos_creados.append(prod)

            # 3. Clientes
            clientes_data = [
                ("NIT", "901452310-8", "Soluciones Digitales Andinas SAS", "compras@andinasdigital.co", "6017428890", "Av. El Dorado # 68C-61, Bogotá"),
                ("CC", "1020784512", "Laura Valentina Gómez Ruiz", "laura.gomez@gmail.com", "3158923411", "Carrera 15 # 93-40, Bogotá"),
                ("NIT", "900812654-1", "Grupo Constructor Horizonte SAS", "gerencia@horizonteco.com", "6044489021", "Calle 10 # 43E-35, Medellín"),
                ("CC", "80192433", "Carlos Andrés Mejía Vargas", "cmejia@outlook.com", "3104556789", "Calle 116 # 19-50, Bogotá"),
                ("NIT", "901229980-4", "Clínica Odontológica Sonrisa Real", "administracion@sonrisareal.co", "6025551234", "Av. Pasoancho # 57-80, Cali"),
                ("CC", "52890123", "Diana Carolina Rojas Pineda", "diana.rojas@yahoo.com", "3007812345", "Carrera 7 # 72-41, Bogotá"),
            ]
            clientes = []
            for tipo_doc, doc, nombre, correo, tel, dir_c in clientes_data:
                cli, _ = Cliente.objects.get_or_create(
                    empresa=empresa,
                    numero_documento=doc,
                    defaults={
                        "tipo_documento": tipo_doc,
                        "nombre": nombre,
                        "email": correo,
                        "telefono": tel,
                        "direccion": dir_c,
                    },
                )
                clientes.append(cli)

            # 4. Proveedores y Compras recibidas
            proveedores_data = [
                ("900334455-1", "Importadora Tecnológica Mayorista SAS", "ventas@importech.co", "6013204455", "Zona Franca Fontibón Bodega 14, Bogotá"),
                ("901112233-9", "Distribuidora Global de Redes y Partes", "pedidos@globalredes.co", "6016509988", "Autopista Norte Km 19, Chía"),
                ("890900111-4", "Mobiliario Corporativo de Colombia SAS", "comercial@mobiliarioco.com", "6043228877", "Parque Industrial Itagüí, Antioquia"),
            ]
            proveedores = []
            for doc, nombre, correo, tel, dir_p in proveedores_data:
                prov, _ = Proveedor.objects.get_or_create(
                    empresa=empresa,
                    documento=doc,
                    defaults={
                        "nombre": nombre,
                        "email": correo,
                        "telefono": tel,
                        "direccion": dir_p,
                        "activo": True,
                    },
                )
                proveedores.append(prov)

            hoy = timezone.localdate()
            if not Compra.objects.filter(empresa=empresa).exists():
                compra1 = Compra.objects.create(
                    empresa=empresa,
                    proveedor=proveedores[0],
                    referencia="FC-IMP-2026-101",
                    fecha=hoy - timedelta(days=12),
                    vencimiento=hoy + timedelta(days=18),
                    observaciones="Reabastecimiento mensual de portátiles y monitores.",
                )
                LineaCompra.objects.create(
                    empresa=empresa,
                    compra=compra1,
                    producto=productos_creados[0],
                    cantidad=4,
                    costo=Decimal("2950000.00"),
                    iva_porcentaje=Decimal("19.00"),
                )
                LineaCompra.objects.create(
                    empresa=empresa,
                    compra=compra1,
                    producto=productos_creados[2],
                    cantidad=5,
                    costo=Decimal("1020000.00"),
                    iva_porcentaje=Decimal("19.00"),
                )
                compra1 = erp_services.recibir_compra(empresa=empresa, pk=compra1.pk, usuario=usuario)
                contabilizar_compra(compra=compra1, usuario=usuario)

                compra2 = Compra.objects.create(
                    empresa=empresa,
                    proveedor=proveedores[1],
                    referencia="FC-RED-2026-044",
                    fecha=hoy - timedelta(days=5),
                    vencimiento=hoy + timedelta(days=25),
                    observaciones="Pedido de periféricos y almacenamiento SSD.",
                )
                LineaCompra.objects.create(
                    empresa=empresa,
                    compra=compra2,
                    producto=productos_creados[3],
                    cantidad=6,
                    costo=Decimal("240000.00"),
                    iva_porcentaje=Decimal("19.00"),
                )
                compra2 = erp_services.recibir_compra(empresa=empresa, pk=compra2.pk, usuario=usuario)
                contabilizar_compra(compra=compra2, usuario=usuario)

            # 5. Cuentas de Tesorería y Movimientos
            caja_principal, _ = CuentaTesoreria.objects.get_or_create(
                empresa=empresa,
                nombre="Caja Principal Mostrador",
                defaults={"tipo": "caja", "activa": True},
            )
            banco_principal, _ = CuentaTesoreria.objects.get_or_create(
                empresa=empresa,
                nombre="Bancolombia Cuenta Corriente",
                defaults={"tipo": "banco", "activa": True},
            )
            banco_sec, _ = CuentaTesoreria.objects.get_or_create(
                empresa=empresa,
                nombre="Davivienda Empresarial",
                defaults={"tipo": "banco", "activa": True},
            )

            # 6. Facturas emitidas, DIAN, Contabilidad y Cartera
            if not Factura.objects.filter(empresa=empresa).exists():
                f1 = services.crear_factura(
                    empresa=empresa,
                    usuario=usuario,
                    cliente=clientes[0],
                    items=[
                        {"producto": productos_creados[0], "cantidad": 2},
                        {"producto": productos_creados[2], "cantidad": 2},
                    ],
                )
                emitir_factura_electronica(factura=f1)
                contabilizar_factura(factura=f1, usuario=usuario)
                cxc1 = erp_services.llevar_factura_a_cartera(
                    empresa=empresa,
                    pk=f1.pk,
                    vencimiento=hoy + timedelta(days=15),
                )
                # Abono parcial en tesorería
                mov_abono = erp_services.registrar_tesoreria(
                    empresa=empresa,
                    usuario=usuario,
                    cuenta=banco_principal,
                    monto=Decimal("5000000.00"),
                    tipo="ingreso",
                    concepto=f"Abono inicial Factura #{f1.numero} - {clientes[0].nombre}",
                    fecha=hoy - timedelta(days=2),
                    operacion=uuid.uuid4(),
                    referencia="TRANS-BC-90812",
                    cartera=cxc1,
                )
                contabilizar_movimiento_tesoreria(movimiento=mov_abono)

                f2 = services.crear_factura(
                    empresa=empresa,
                    usuario=usuario,
                    cliente=clientes[2],
                    items=[
                        {"producto": productos_creados[1], "cantidad": 1},
                        {"producto": productos_creados[8], "cantidad": 2},
                    ],
                )
                emitir_factura_electronica(factura=f2)
                contabilizar_factura(factura=f2, usuario=usuario)

                f3 = services.crear_factura(
                    empresa=empresa,
                    usuario=usuario,
                    cliente=clientes[1],
                    items=[
                        {"producto": productos_creados[5], "cantidad": 1},
                        {"producto": productos_creados[3], "cantidad": 1},
                    ],
                )
                emitir_factura_electronica(factura=f3)
                contabilizar_factura(factura=f3, usuario=usuario)

            # 7. Empleados, Nómina, Servicios y Agenda
            empleados_data = [
                ("1018492031", "Camila Andrea Pardo", "Contadora General", Decimal("3800000.00")),
                ("1032456789", "Sebastián Morales Díaz", "Ingeniero de Soporte y Redes", Decimal("3200000.00")),
                ("52998412", "Natalia Herrera Castro", "Asesora Comercial Senior", Decimal("2600000.00")),
            ]
            empleados = []
            for doc, nombre, cargo, salario in empleados_data:
                emp, _ = Empleado.objects.get_or_create(
                    empresa=empresa,
                    documento=doc,
                    defaults={
                        "nombre": nombre,
                        "cargo": cargo,
                        "salario_base": salario,
                        "fecha_ingreso": hoy - timedelta(days=240),
                        "activo": True,
                    },
                )
                empleados.append(emp)

            if not LiquidacionNomina.objects.filter(empresa=empresa).exists():
                inicio_mes = hoy.replace(day=1)
                for emp in empleados[:2]:
                    aportes = calcular_aportes_nomina_colombia(
                        salario_base=emp.salario_base,
                        auxilio_transporte=Decimal("162000.00"),
                    )
                    nom = LiquidacionNomina.objects.create(
                        empresa=empresa,
                        empleado=emp,
                        desde=inicio_mes,
                        hasta=hoy,
                        base=emp.salario_base,
                        adicionales=Decimal("162000.00"),
                        deducciones=aportes["deducciones_empleado"],
                        neto=aportes["neto_estimado"],
                        observaciones="Liquidación mensual con aportes de ley.",
                    )
                    nom = erp_services.aprobar_nomina(empresa=empresa, pk=nom.pk)
                    contabilizar_nomina(nomina=nom, usuario=usuario)

            servicios_data = [
                ("Mantenimiento Preventivo y Limpieza Térmica PC/Portátil", Decimal("120000.00"), 60),
                ("Configuración de Red Empresarial y Firewall Wi-Fi 6", Decimal("350000.00"), 120),
                ("Diagnóstico y Recuperación de Datos SSD/NVMe", Decimal("220000.00"), 90),
            ]
            servicios = []
            for nom_s, precio_s, dur_s in servicios_data:
                srv, _ = Servicio.objects.get_or_create(
                    empresa=empresa,
                    nombre=nom_s,
                    defaults={
                        "precio": precio_s,
                        "iva_porcentaje": Decimal("19.00"),
                        "duracion_minutos": dur_s,
                        "activo": True,
                    },
                )
                servicios.append(srv)

            if not Cita.objects.filter(empresa=empresa).exists():
                inicio_cita = timezone.now().replace(minute=0, second=0, microsecond=0) + timedelta(days=1, hours=2)
                cita = Cita(
                    empresa=empresa,
                    cliente=clientes[0],
                    empleado=empleados[1],
                    servicio=servicios[1],
                    inicio=inicio_cita,
                    observaciones="Revisión de cableado estructurado y puntos de acceso.",
                )
                erp_services.reservar_cita(cita)

            # 8. Pedido web de ejemplo en el panel de pedidos
            if not Pedido.objects.filter(empresa=empresa).exists():
                prod_pedido = productos_creados[5]
                subtotal_p = prod_pedido.precio
                iva_p = prod_pedido.precio_con_iva - prod_pedido.precio
                envio_p = Decimal("12000.00")
                total_p = prod_pedido.precio_con_iva + envio_p
                comision_p = (total_p * Decimal("0.05")).quantize(Decimal("0.01"))
                pedido = Pedido.objects.create(
                    empresa=empresa,
                    comprador=usuario,
                    numero=1,
                    estado=Pedido.Estado.PAGADO,
                    expira_en=timezone.now() + timedelta(days=1),
                    tipo_documento="CC",
                    numero_documento="1020784512",
                    nombre="Laura Valentina Gómez Ruiz",
                    email="laura.gomez@gmail.com",
                    telefono="3158923411",
                    departamento="Cundinamarca",
                    ciudad="Bogotá D.C.",
                    direccion="Carrera 15 # 93-40 Apto 502",
                    indicaciones="Entregar en portería principal.",
                    subtotal=subtotal_p,
                    iva=iva_p,
                    costo_envio=envio_p,
                    total=total_p,
                    peso_total_gramos=prod_pedido.peso_gramos,
                    comision_porcentaje=Decimal("5.00"),
                    comision_valor=comision_p,
                    neto_vendedor=total_p - comision_p,
                    estado_envio=Pedido.EstadoEnvio.ENVIADO,
                    transportadora="Servientrega",
                    numero_guia="SV-992837465CO",
                    enviado_en=timezone.now() - timedelta(hours=5),
                )
                DetallePedido.objects.create(
                    empresa=empresa,
                    pedido=pedido,
                    producto=prod_pedido,
                    cantidad=1,
                    precio_unitario=prod_pedido.precio,
                    iva_porcentaje=prod_pedido.iva_porcentaje,
                )

        self.stdout.write(
            self.style.SUCCESS(
                f"Datos cargados con éxito en {empresa.nombre}: "
                f"{Categoria.objects.filter(empresa=empresa).count()} categorías, "
                f"{Producto.objects.filter(empresa=empresa).count()} productos con foto, "
                f"{Cliente.objects.filter(empresa=empresa).count()} clientes, "
                f"{Factura.objects.filter(empresa=empresa).count()} facturas electrónicas."
            )
        )
