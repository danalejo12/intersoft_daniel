# Análisis de InterSoft y mejora del recibo POS

Fecha: 10 de noviembre de 2026.

## Alcance

Revisión del proyecto Django, configuración, rutas, aislamiento por empresa y flujo POS: vistas, JavaScript, servicios de ventas, caja, modelos y pruebas existentes. No constituye una auditoría exhaustiva del marketplace, la pasarela de pagos ni del despliegue.

## Arquitectura y puntos fuertes

- Aplicación Django con PostgreSQL, plantillas HTML y JavaScript. Incluye clientes, inventario y kardex, facturas, marketplace, pedidos, pagos y punto de venta.
- TenantMiddleware selecciona una membresía activa del usuario. Las consultas del POS y del recibo se restringen a la empresa activa.
- Los permisos distinguen creación y consulta de ventas.
- caja.registrar_venta y services.crear_factura usan transacciones: factura, inventario y pagos se confirman juntos o se revierten.
- Los precios y el IVA se calculan en el servidor. Los importes enviados por el navegador no determinan el precio de venta.
- Hay bloqueos de filas para proteger stock, consecutivos y turnos; restricciones impiden duplicar consecutivos o abrir dos turnos del mismo cajero en una empresa.
- El POS admite efectivo con cambio, tarjeta, transferencia y pagos mixtos. El cierre calcula diferencia entre efectivo esperado y contado.

## Hallazgos y prioridades

| Prioridad | Evidencia | Efecto y siguiente paso |
| --- | --- | --- |
| Alta | VenderView convierte cantidad con int() y depende de assert para validar la lista. | Una cantidad JSON fraccionaria puede truncarse y un booleano puede aceptarse como entero. Validar tipos explícitamente, rechazar fracciones y comprobar también la cantidad acumulada de líneas repetidas. |
| Alta | El POST de venta no incluye una clave de idempotencia. pos.js invita a reintentar ante un error de conexión. | Si la venta se confirma pero se pierde la respuesta, un reintento puede duplicarla. Guardar una clave única por operación y devolver el resultado original al repetirla. |
| Media | El recibo consulta producto.nombre, cliente y empresa actuales; el detalle congela únicamente precio e IVA. | Una reimpresión puede cambiar de nombre o datos después de editar los registros. Guardar los datos descriptivos de la venta como instantáneas si se requiere fidelidad histórica. |
| Media | caja.dinero hace quantize sin capturar InvalidOperation ni limitar el máximo de los campos decimales. | Valores numéricos extremos pueden causar errores de servidor. Validar límites monetarios antes de cuantizar o guardar. |
| Media | PosMixin requiere ventas.crear y TicketView requiere ventas.ver. | Revisar roles que puedan cobrar sin consultar ventas: podrían registrar una venta y no poder abrir su recibo. Definir el comportamiento esperado y probar esa combinación. |
| Baja | TicketView consulta pagos_caja por separado para el listado y para sumar cambio. | Materializar los pagos una vez permite reutilizarlos y evita una consulta repetida. |
| Operativa | La primera ejecución de pruebas recibió DEBUG=release desde el entorno. | python-decouple exige un booleano válido. Para verificar se usó DEBUG=False únicamente en el proceso de pruebas; no se modificó la configuración persistente. |

Estos hallazgos proceden de la lectura del código; no se ejecutaron pruebas de explotación ni de concurrencia. Quedan documentados como trabajo posterior, sin alterar la lógica de venta durante el cambio visual.

## Recibo actualizado

Archivo: intersoft/core/templates/core/pos/ticket.html.

- Vista en pantalla con fondo suave, tarjeta blanca y acentos verde oscuro.
- Cabecera del negocio, número de venta y fecha con mayor jerarquía visual.
- Datos de cliente y cajero, productos con cantidad y precio unitario, subtotal, IVA y total destacado.
- Referencias de pagos separadas; efectivo marcado como recibido y cambio visible.
- Diseño adaptable a pantallas pequeñas, tablas con encabezados y foco visible en botones.
- Impresión con ancho de contenido de 72 mm y márgenes de 4 mm para papel de 80 mm; colores negros y sin botones, fondo ni sombras.
- Conserva la impresión automática mediante imprimir=1 y los valores calculados por el servidor.

La impresión física y el aspecto final en navegador requieren revisión visual. La longitud del papel y los márgenes efectivos también dependen del navegador y del controlador de la impresora.

## Verificación realizada

- Ejecutado: env/Scripts/python.exe intersoft/manage.py test core.tests_pos --noinput, con DEBUG=False en el proceso.
- Resultado: 38 pruebas aprobadas; comprobación de Django sin problemas.
- Incluye ventas, pagos mixtos, cambio, inventario, cierre de caja, permisos, aislamiento entre empresas y contenido del recibo.
- git diff --check terminó sin errores de espacios.
- No se ejecutó la suite completa ni se probó una impresora física o la presentación en navegador.
