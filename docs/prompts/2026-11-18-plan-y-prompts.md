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

| Prompt | Responsable | Rama | Zona principal | Estado (18-nov) |
|---|---|---|---|---|
| 1 | danalejo12 | `feature/plataforma-base` | app nueva `plataforma/` | **Hecho** (`plataforma` + roles + auditoría + llaves Wompi) |
| 2 | danalejo12 | `feature/plataforma-cobros` | `plataforma/`, `suscripciones/` | **Hecho** (editor de planes, cobros, cortesías, fundadores, métricas) |
| 3 | miguel2007ortiz | `feature/pqrs` | app nueva `pqrs/` | **Hecho** (`pqrs` flujos A/B, días hábiles, semáforo, escalamiento, correos) |
| 4 | miguel2007ortiz | `feature/errores-y-comentarios` | app nueva `soporte/` | **Hecho** (`soporte` errores 500 por huella, reportes, 👍/👎, NPS, ideas) |
| 5 | danalejo12 | `chore/docker-unificado` | `Dockerfile`, compose, `docker/`, `settings.py` | **Hecho** (`compose.dev.yml`, `compose.prod.yml`, Python 3.14, `/salud/`, Swagger staff) |
| 6 | miguel2007ortiz | `docs/adso-actualizacion` | `docs/`, pruebas | **Hecho** (diccionario, MER, UML, secuencia, manual, PDFs/DOCX, 92% cobertura, 525 tests en verde) |

Los prompts 3 y 4 crean pantallas que después se verán en la consola del prompt 1. Para no depender del otro, cada app expone su propia bandeja con `is_staff` y el prompt 1 solo agrega los enlaces en el menú.

---

## 3. Los 6 prompts

### Prompt 1: Consola de super administrador (danalejo12) — **Completado**

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

### Prompt 2: Planes, cobros y métricas en la consola (danalejo12, después del 1) — **Completado**

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

### Prompt 3: PQRS en dos flujos (miguel2007ortiz) — **Completado**

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

### Prompt 4: Errores y comentarios (miguel2007ortiz) — **Completado**

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

### Prompt 5: Docker unificado y endurecimiento para producción (danalejo12) — **Completado**

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

### Prompt 6: Documentación ADSO y cobertura al día (miguel2007ortiz) — **Completado**

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

## 4. Más ideas para los siguientes días (banco de prompts listos para usar)

### Consola y negocio SaaS

#### Prompt 7: «Entrar como» un negocio + anuncios globales
```text
Contexto: ya existe la app `plataforma` (/plataforma/) con roles internos (Dueño, Soporte) y AuditoriaPlataforma.

Tarea:
1. En /plataforma/negocios/ (crea la bandeja completa reemplazando «Próximamente»), lista los negocios con su
   plan, estado de suscripción y botón «Entrar como» (solo roles Dueño y Soporte).
2. Al activar «Entrar como» sobre una empresa, guarda en sesión el modo soporte (solo lectura opcional por
   defecto) y muestra en core/templates/core/base.html una franja roja fija visible en todo /panel/ con el
   nombre del negocio y un botón «Salir de soporte».
3. Toda entrada y salida queda registrada en AuditoriaPlataforma con actor, empresa, IP y modo (lectura/escritura).
4. Agrega anuncios globales desde /plataforma/ (título, mensaje, vigencia, tipo) visibles como aviso en /panel/.

Restricciones: no toques core/facturacion_electronica.py. Pruebas de aislamiento, solo lectura y auditoría en verde.
```

#### Prompt 8: Cupones de descuento, página pública de precios y recordatorios de vencimiento
```text
Contexto: los cobros de planes están en suscripciones/cobros.py y suscripciones/services.py.

Tarea:
1. Crea el modelo CuponPlan (código único, porcentaje o valor fijo, vigencia, usos_maximos, usos_actuales,
   activo) e intégralo en cobros.cotizar() y en /panel/suscripcion/. Gestión desde /plataforma/planes-cobros/.
2. Crea una página pública /precios/ generada dinámicamente desde Plan.objects.filter(activo=True) mostrando
   precios mensual/anual, límites y features.
3. Registra una tarea periódica en core/tareas.py que envíe recordatorios por correo 7, 3 y 1 día antes de
   vencer un Trial o suscripción paga (idempotente por día/suscripción), con enlace directo a /panel/suscripcion/.
4. Agrega interruptor de funciones (FeatureFlag por negocio) y 2FA/TOTP obligatorio para personal de /plataforma/.

Restricciones: no toques la DIAN. Pruebas en verde.
```

### Inventario y bodegas

#### Prompt 9: Compras con bodega destino, alertas por bodega y conteo físico
```text
Contexto: existen core.Bodega, core.Existencia y core.bodegas.py; hoy las compras del ERP entran a la Principal.

Tarea:
1. Agrega un selector de bodega destino en Compra (core/erp_services.py y vistas ERP), usando la Principal por
   defecto para compatibilidad.
2. Extiende las alertas de stock mínimo (core/notificaciones.py y comando procesar_reservas_y_alertas) para
   alertar también cuando una bodega activa quede por debajo de su mínimo.
3. Implementa traslados «en tránsito» (estado enviado / recibido con confirmación en la bodega destino) y un
   módulo de conteo físico por bodega con hoja imprimible y ajuste masivo auditado en MovimientoInventario.
4. Agrega importación masiva de productos y stock inicial desde Excel (.xlsx con openpyxl) validando errores por fila.

Restricciones: no toques la DIAN. Pruebas de concurrencia e inventario en verde.
```

### Marketplace y POS

#### Prompt 10: Ticket POS en PDF, seguimiento de envío y favoritos
```text
Contexto: el marketplace está en core/views_tienda.py y core/views_compra.py; el POS en core/views_pos.py.

Tarea:
1. Genera el ticket POS en PDF (reportlab) descargable desde /panel/pos/ticket/<uuid:pk>/pdf/ y con opción de
   envío por correo al cliente.
2. En la página del pedido del comprador (/pedidos/<uuid:pk>/), muestra una línea de tiempo visual con el
   seguimiento de envío (pendiente → preparando → enviado con guía → entregado).
3. Agrega «Favoritos» y botón «Volver a comprar» (recarga los ítems disponibles del pedido al carrito).
4. Agrega reportes de ventas, márgenes y rotación desglosados por bodega y por turno de caja en /panel/erp/reportes/.

Restricciones: no toques la DIAN. Pruebas en verde.
```

### Calidad y operación

#### Prompt 11: Umbral de cobertura en CI, rate limiting y respaldos automáticos
```text
Contexto: el CI está en .github/workflows/pruebas.yml y el reporte de cobertura en docs/adso/Reporte-Cobertura-InterSoft.md.

Tarea:
1. Actualiza .github/workflows/pruebas.yml para ejecutar coverage sobre core, suscripciones, plataforma, pqrs y
   soporte y fallar el build si la cobertura total baja del 85 % (`coverage report --fail-under=85`).
2. Agrega rate limiting (limitación de peticiones) en API DRF, webhooks de Wompi y endpoints públicos críticos.
3. Crea un script y documentación operativa en deploy/ para copias de seguridad automáticas de PostgreSQL
   (pg_dump) con verificación periódica de restauración en base temporal.
4. Ejecuta una revisión de accesibilidad (contraste, foco por teclado y atributos aria-*) en tienda y POS.

Restricciones: no toques la DIAN. Pruebas y CI en verde.
```

### Pendiente de decisión (sin prompt todavía)
- **DIAN**: elegir proveedor tecnológico (Alegra, Siigo, Facture u otro), resolución de numeración y
  ambiente de habilitación. Hasta entonces el simulador debe quedar limitado a desarrollo **antes de
  desplegar**. Reunión de 30 minutos para decidir.
- Política de reembolsos y de devoluciones del marketplace (texto legal y flujo).
