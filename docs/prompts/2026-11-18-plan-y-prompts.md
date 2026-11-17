# Plan del 18 de noviembre de 2026: análisis y prompts para el equipo

Para: **danalejo12** y **miguel2007ortiz**. Cada prompt se pega tal cual en Claude Code, desde la raíz del repositorio.

---

## 1. Estado actual (17-nov, noche)

`main` ya reúne el trabajo de los dos. Así quedó:

| Quién | Qué subió | Commits |
|---|---|---|
| miguel2007ortiz | Documentación ADSO (SRS IEEE 830, diccionario de datos, manual, plan de pruebas, reporte de cobertura del 90 %), diagramas UML/MER/casos de uso/secuencia, recuperación de contraseña, Swagger (`/api/docs/`), factura en PDF, reportes en Excel, límites del plan conectados al panel (productos, usuarios, POS), Docker para desarrollo | `fb5947e` … `a8488fd` |
| danalejo12 | Ranking «Más vendidos», tareas periódicas unificadas (`tareas_periodicas`), compra unificada para varios negocios, cobro de planes con la cuenta de Wompi de Intersoft, bodegas o sedes con stock por bodega y traslados | `9f1e425` … `af28f79` |
| Unión | Merge sin conflictos, más una corrección en `docker/entrypoint.sh` | `1aef588` y siguientes |

### Hallazgos del análisis

1. **Corregido: el scheduler de producción no habría corrido.** El nuevo `Dockerfile` usa `ENTRYPOINT ["/app/entrypoint.sh"]` y ese script ignoraba el comando del contenedor. En `compose.prod.yml` el servicio `scheduler` habría arrancado gunicorn en vez de `tareas_periodicas`, y las reservas, los cobros de planes y las alertas no se habrían procesado. Ahora el entrypoint ejecuta el comando que recibe.
2. **Hay dos configuraciones de Docker que se pisan.** `docker-compose.yml` (desarrollo: `DEBUG=True`, `PASARELA_SIMULADA=True`, contraseña y `SECRET_KEY` por defecto escritas en el archivo, sin scheduler ni nginx) y `compose.prod.yml` (producción). Hay que dejar claro cuál se usa para qué y quitar los secretos por defecto. → Prompt 5.
3. **Bajó la versión de Python**: el `Dockerfile` pasó de 3.14 a 3.12. Las pruebas locales corren en 3.14. Hay que elegir una sola versión y fijarla también en el CI.
4. **Swagger (`/api/docs/`) es público.** Muestra toda la API a cualquiera. En producción conviene limitarlo al personal o desactivarlo.
5. **El reporte de cobertura (90 %) es anterior a la unión.** No incluye bodegas, cobros de planes, órdenes ni tareas periódicas. Hay que regenerarlo. → Prompt 6.
6. **Los documentos ADSO no tienen los modelos nuevos**: `Bodega`, `Existencia`, `Orden`, `CobroSuscripcion` y `EjecucionTarea`, ni sus casos de uso. → Prompt 6.
7. **Se cruzan dos controles de plan**: los límites de miguel (POS, productos, usuarios) y los de danalejo12 (multisede para bodegas, cobro antes de activar un plan pago). Funcionan juntos, pero conviene que la pantalla de planes explique en un solo lugar qué incluye cada uno.
8. **La DIAN sigue en espera, por decisión del equipo.** El botón «Emitir DIAN» usa el simulador y marca las facturas como ACEPTADAS con un CUFE ficticio. **No se toca hasta decidir el proveedor antes del despliegue.** Ver el punto de la sección 4.

---

## 2. Reglas para trabajar sin pisarnos

- Antes de empezar: `git checkout main && git pull`. Cada prompt va en **su propia rama**, con el nombre que se indica.
- Cada persona toca **solo los archivos de su prompt**. Si necesitas cambiar algo de la zona del otro, avísale primero.
- Antes de subir: `python intersoft/manage.py test`, `python intersoft/manage.py check` y `python intersoft/manage.py makemigrations --check`, todo en verde.
- **Migraciones**: si los dos crean migraciones en `core` el mismo día, quien suba de segundo debe hacer `git pull` y regenerar la suya (`makemigrations --merge` o renumerar) antes de subir.
- Commits en español con prefijo (`feat(...)`, `fix(...)`, `docs(...)`) y un PR o merge a `main` por prompt.
- **No tocar la DIAN** (`core/facturacion_electronica.py` ni la nómina electrónica).

| Prompt | Responsable | Rama | Zona principal |
|---|---|---|---|
| 1 | danalejo12 | `feature/plataforma-base` | app nueva `plataforma/` |
| 2 | danalejo12 | `feature/plataforma-cobros` | `plataforma/`, `suscripciones/` |
| 3 | miguel2007ortiz | `feature/pqrs` | app nueva `pqrs/` |
| 4 | miguel2007ortiz | `feature/errores-y-comentarios` | app nueva `soporte/` |
| 5 | danalejo12 | `chore/docker-unificado` | `Dockerfile`, compose, `docker/`, `settings.py` (solo seguridad) |
| 6 | miguel2007ortiz | `docs/adso-actualizacion` | `docs/`, pruebas |

Los prompts 3 y 4 crean pantallas que después se verán en la consola del prompt 1. Para no depender del otro, cada app expone su propia bandeja con `is_staff` y el prompt 1 solo agrega los enlaces en el menú.

---

## 3. Los 6 prompts

### Prompt 1: Consola de super administrador (danalejo12)

```text
Contexto: proyecto Django multiempresa Intersoft (repo actual). El panel de cada negocio vive en /panel/ y el
admin de Django en /admin/. Necesitamos una consola SOLO para el equipo dueño del software en /plataforma/.

Tarea: crea una app Django nueva `plataforma` con:
1. Acceso: solo usuarios con is_staff. Roles internos (modelo RolPlataforma o grupos): Dueño (todo),
   Finanzas (planes y cobros), Soporte (negocios, PQRS, errores; sin dinero), Desarrollador (operación).
   Un mixin `PlataformaMixin(permiso=...)` que devuelva 403 si no tiene el rol.
2. Auditoría: modelo AuditoriaPlataforma (actor, accion, objeto_tipo, objeto_id, detalle JSON sin secretos,
   ip, fecha) y una función registrar(...) que usen todas las acciones que cambian datos.
3. Inicio de la consola (/plataforma/): tarjetas con negocios activos, en prueba y con plan pago, cobros
   pendientes y en revisión, estado de las tareas periódicas (core.models.EjecucionTarea: última ejecución y
   fallos seguidos, en rojo si hay 3 o más).
4. Llaves de Wompi de Intersoft desde la pantalla: hoy están en settings SUSCRIPCIONES_WOMPI_*. Crea un modelo
   ConfiguracionCobroPlataforma (singleton) con las llaves cifradas usando core/cifrado.py, igual que
   core.models.ConfiguracionPagos de los negocios: los campos nunca devuelven el secreto, solo los últimos 4
   caracteres. Botón «Verificar» que reutilice core/pasarela_negocio.verificar_llaves. Cambia
   suscripciones/cobros.credenciales_intersoft() para leer primero de este modelo y, si no hay, de settings.
   Solo el rol Dueño puede editarlas, y cada cambio queda en la auditoría (sin valores).
5. Menú lateral de la consola con enlaces a: Inicio, Negocios, Planes y cobros, PQRS, Errores, Comentarios
   y Operación. Las secciones que aún no existen muestran «Próximamente».
6. Pruebas en plataforma/tests.py: acceso denegado a no-staff y a staff sin rol; auditoría registrada; las
   llaves no aparecen en el HTML; credenciales_intersoft prefiere la base de datos sobre settings.

Restricciones: no toques core/facturacion_electronica.py (DIAN en espera). Reutiliza el CSS del panel
(core/static/core/css/app.css). Español en código y textos. Deja todas las pruebas del proyecto en verde.
Al final dame un resumen de lo que hiciste y cómo probarlo a mano.
```

### Prompt 2: Planes, cobros y métricas en la consola (danalejo12, después del 1)

```text
Contexto: ya existe la app `plataforma` (/plataforma/) con roles internos y auditoría. Los cobros de planes
están en suscripciones/cobros.py y suscripciones.models.CobroSuscripcion.

Tarea:
1. Editor de planes (rol Finanzas o Dueño): precios mensual y anual, límites (productos, usuarios; null =
   ilimitado), features (lista con casillas: marketplace, pos, multisede, etc.), comisión y activo. Validar
   que el plan «gratis» siga existiendo y con precio 0. Cada cambio queda en la auditoría.
2. Cobros: lista filtrable por estado, plan y negocio. Bandeja «Requiere revisión» con dos acciones:
   «Reconsultar en Wompi» (cobros.sincronizar_cobro con forzar=True) y «Aplicar manualmente», que exige un
   motivo, usa cambiar_plan y marca el cobro como aprobado con detalle «Aplicado manualmente por <usuario>».
   Ambas quedan en la auditoría.
3. Cortesías: dar N días gratis o un plan de cortesía a un negocio (HistorialSuscripcion con el motivo).
4. Fundadores: ver cuántos cupos van de CUPOS_FUNDADOR y permitir cambiar el cupo desde la consola
   (moverlo a configuración en la base de datos).
5. Métricas: MRR (suma de suscripciones activas pagas normalizadas a mes, con descuento), ARR, negocios
   en prueba, conversión de prueba a pago en los últimos 30 días, vencimientos de los próximos 7 días e
   ingresos cobrados por mes (CobroSuscripcion aprobados). Gráfica simple de los últimos 6 meses.
6. Pruebas de cada acción, incluyendo permisos por rol y el cálculo del MRR con descuento de fundador.

Restricciones: no actives ningún plan sin dejar rastro en HistorialSuscripcion y en la auditoría. No toques
la DIAN. Pruebas en verde.
```

### Prompt 3: PQRS en dos flujos (miguel2007ortiz)

```text
Contexto: Intersoft es un marketplace + SaaS multiempresa en Colombia. Necesitamos PQRS (peticiones, quejas,
reclamos, sugerencias) en dos flujos:
  A) Negocio → Intersoft (sobre el software), desde el panel /panel/.
  B) Comprador → negocio (sobre una compra del marketplace), desde la página del pedido; la recibe el negocio
     en su panel y, si no responde a tiempo, se escala a Intersoft.

Tarea: crea una app `pqrs` con:
1. Modelo PQRS: radicado único legible (PQRS-AAAA-00001, consecutivo seguro con select_for_update), tipo,
   flujo (A/B), empresa, pedido opcional, autor, asunto, descripción, adjuntos (imágenes o PDF, máximo 5 MB,
   validar extensión), estado (radicada, en_tramite, respondida, cerrada, escalada), prioridad, asignado_a,
   fecha límite calculada en días hábiles (sin sábados, domingos ni festivos de Colombia; deja los festivos
   en una lista fácil de actualizar), y una encuesta de satisfacción al cerrar (1 a 5).
2. Conversación: MensajePQRS (autor, texto, adjunto, interno: sí/no). Las notas internas no las ve el
   ciudadano.
3. Vistas: el comprador radica y sigue sus PQRS en /pqrs/; el negocio ve y responde las suyas en
   /panel/pqrs/ (nuevo permiso «pqrs.gestionar» en core/permisos.py y en los roles base que corresponda);
   la bandeja de Intersoft en /plataforma/pqrs/ es solo para is_staff y muestra todas, las escaladas
   primero.
4. Semáforo de vencimiento (verde, amarillo cuando faltan 2 días hábiles o menos, rojo si venció) y una
   tarea periódica que escale las del flujo B vencidas. Regístrala en core/tareas.py (TAREAS) con un
   comando nuevo.
5. Correos en cada cambio de estado y respuesta (usa core/notificaciones.py como modelo).
6. Aislamiento: un negocio nunca ve las PQRS de otro (pruebas con 404) y un comprador solo ve las suyas.
7. Pruebas completas: radicado único con concurrencia, días hábiles, escalamiento, permisos y adjuntos
   inválidos.

Nota legal: deja los plazos configurables en settings (PQRS_DIAS_RESPUESTA=15 por defecto) y escribe en el
README que deben validarse con un abogado. No toques la DIAN. Pruebas en verde.
```

### Prompt 4: Errores y comentarios (miguel2007ortiz)

```text
Contexto: Intersoft (Django). Queremos ver los errores reales y recibir comentarios de los negocios sin
depender de servicios externos (Sentry ya es opcional en settings.py y puede seguir).

Tarea: crea una app `soporte` con:
1. Errores automáticos: un middleware o got_request_exception que guarde cada error 500 en ErrorRegistrado,
   AGRUPADO por huella (tipo de excepción + archivo + línea de la última trama propia), con contador,
   primera y última vez, URL, método, empresa y usuario (si hay), y la traza SIN datos sensibles (reutiliza
   el filtro core.cifrado.FiltroSecretosPago y nunca guardes el cuerpo del POST). Estados: nuevo,
   investigando, resuelto, ignorado. Si uno resuelto vuelve a ocurrir, se reabre. Al aparecer una huella
   nueva se envía un correo a ADMINS una sola vez.
2. Reportes de usuarios: botón «Reportar un problema» en el panel (base.html) que abre un formulario corto y
   adjunta automáticamente la URL, el navegador, la hora y la empresa; el usuario solo escribe qué pasó y
   puede subir una captura.
3. Comentarios: widget 👍/👎 con comentario opcional, que guarda la pantalla de origen; encuesta NPS (0 a 10)
   que se muestra como mucho una vez cada 90 días por usuario; e «Ideas» con votos: los negocios proponen y
   votan (un voto por usuario) y el equipo cambia el estado (en evaluación, planeada, lanzada, descartada).
4. Bandejas para is_staff en /plataforma/errores/, /plataforma/comentarios/ e /plataforma/ideas/, con
   filtros y métricas (NPS actual, errores nuevos de los últimos 7 días, ideas más votadas).
5. Pruebas: agrupación por huella, reapertura, que la traza no contenga secretos, límite de 1 NPS cada 90
   días, voto único y permisos.

Restricciones: el registro de errores nunca debe provocar otro error (envuélvelo en try/except y escribe en
el log). No toques la DIAN. Pruebas en verde.
```

### Prompt 5: Docker unificado y endurecimiento para producción (danalejo12)

```text
Contexto: el repo tiene Dockerfile (ENTRYPOINT docker/entrypoint.sh, que ahora ejecuta "$@" si recibe un
comando), docker-compose.yml (desarrollo) y compose.prod.yml (producción con nginx y scheduler). Se pisan y
docker-compose.yml trae secretos por defecto.

Tarea:
1. Deja dos archivos claros: compose.dev.yml (desarrollo: DEBUG, pasarela simulada, puerto 8000, sin nginx,
   CON scheduler) y compose.prod.yml (producción). Renombra o elimina docker-compose.yml y actualiza el
   README.
2. Quita los valores por defecto de DJANGO_SECRET_KEY y DB_PASSWORD en los compose: deben venir del .env, y
   el compose falla con un mensaje claro si faltan (${VAR:?mensaje}).
3. En producción solo un contenedor ejecuta migrate y collectstatic (web); el scheduler no migra.
   Comprueba que `docker compose -f compose.prod.yml config` sea válido.
4. Elige UNA versión de Python (3.12 o 3.14), úsala en el Dockerfile y en .github/workflows/pruebas.yml, y
   documéntala.
5. Swagger: /api/docs/ y /api/schema/ solo para is_staff cuando DEBUG=False (SERVE_PERMISSIONS de
   drf-spectacular).
6. `python intersoft/manage.py check --deploy` con variables de producción: sin errores; documenta las
   advertencias que queden.
7. Agrega un healthcheck HTTP (/salud/ que responda 200 si la base de datos contesta) y úsalo en compose.

No toques la DIAN. Pruebas en verde.
```

### Prompt 6: Documentación ADSO y cobertura al día (miguel2007ortiz)

```text
Contexto: docs/adso/ y docs/diagramas/ se hicieron antes de unir el trabajo de danalejo12. Faltan los
modelos y flujos nuevos: core.Bodega, core.Existencia, core.Orden, core.EjecucionTarea,
suscripciones.CobroSuscripcion y los campos bodega en Pedido, Factura, TurnoCaja y MovimientoInventario.

Tarea:
1. Actualiza el diccionario de datos, el MER y el diagrama de clases con esos modelos (campos, tipos,
   restricciones, relaciones). Léelos del código, no los supongas.
2. Casos de uso y diagramas de secuencia nuevos: compra unificada en varios negocios, pago de un plan con
   Wompi (retorno, webhook y conciliación), traslado entre bodegas, venta POS desde una bodega y tareas
   periódicas.
3. Manual de usuario: secciones de Bodegas, Comprar todo, Pagar un plan y Más vendidos.
4. Regenera el reporte de cobertura con coverage sobre todo el proyecto (core + suscripciones), en MD y PDF,
   y agrega pruebas a los módulos que bajen del 85 %. Excluye poblar_datos_demo de la medición o agrégale
   una prueba de humo.
5. Regenera los PDF y el .docx de diagramas con la misma herramienta que usaste antes.

No cambies lógica de negocio salvo para agregar pruebas. No toques la DIAN.
```

---

## 4. Más ideas para los siguientes días (banco de prompts)

### Consola y negocio SaaS
- «Entrar como» un negocio para dar soporte: franja roja visible, solo lectura opcional, todo en la auditoría.
- Cupones de descuento para planes (porcentaje o valor, vigencia, usos máximos).
- Interruptores de funciones: activar algo nuevo solo para algunos negocios.
- Anuncios en el panel de todos los negocios (mantenimientos, novedades).
- Verificación en dos pasos (TOTP) obligatoria para el personal de la consola.
- Página pública de precios generada desde los planes de la base de datos.
- Recordatorios por correo 7, 3 y 1 día antes de que venza un plan, con el enlace de pago.

### Inventario y bodegas
- Compras del ERP con bodega destino (hoy entran a la Principal).
- Alertas de stock mínimo por bodega, además de la del total.
- Traslados «en tránsito»: el despacho y la recepción se confirman por separado.
- Conteo físico por bodega con hoja imprimible y ajuste masivo.
- Importar productos y stock desde Excel (ya tenemos openpyxl).
- Etiquetas con código de barras y lectura con la cámara en el POS.

### Marketplace y POS
- Ticket POS en PDF y envío por WhatsApp o correo.
- POS sin conexión (PWA) que sincronice al volver la red, con la idempotencia que ya existe.
- Seguimiento de envío para el comprador con línea de tiempo.
- Favoritos y «volver a comprar».
- Reportes por bodega y por caja (ventas, márgenes, rotación).

### Calidad y operación
- Exigir en el CI una cobertura mínima (falla si baja del 85 %).
- Copias de seguridad automáticas de PostgreSQL con restauración probada.
- Límite de peticiones en el login, la API y los webhooks.
- Pruebas de carga del checkout y del POS.
- Revisión de accesibilidad (contraste, teclado, lectores de pantalla) en tienda y POS.

### Pendiente de decisión (sin prompt todavía)
- **DIAN**: elegir proveedor tecnológico (Alegra, Siigo, Facture u otro), resolución de numeración y
  ambiente de habilitación. Hasta entonces el simulador debe quedar limitado a desarrollo **antes de
  desplegar**. Reunión de 30 minutos para decidir.
- Política de reembolsos y de devoluciones del marketplace (texto legal y flujo).
