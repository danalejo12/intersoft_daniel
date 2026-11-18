# Plan de mejoras técnicas (Interior y Exterior) — InterSoft
**Fecha:** 18 de noviembre de 2026  
**Base:** `main` (tras la extracción inicial de CSS/JS, mejoras de NPS, `/mis-pedidos/`, `/panel/pedidos/`, `/panel/negocio/pagos/` y adaptación móvil).

---

## 1. Resumen de prioridades

| Prioridad | Frente | Objetivo | Zona principal |
| --- | --- | --- | --- |
| 1 | **Interior (Calidad)** | Subir cobertura de `pqrs` (`views.py` 41 %, `services.py` 64 %, `forms.py` 76 %) y `core/importaciones.py` (75 %) por encima del 85 % | `pqrs/tests.py`, `core/tests_cobertura.py` |
| 2 | **Interior (Operación)** | Soporte de Redis para caché compartida (rate limiting / DRF throttling entre workers) y monitoreo del `scheduler` | `intersoft/settings.py`, `compose.prod.yml`, `compose.dev.yml` |
| 3 | **Exterior (Seguridad / CSP)** | Eliminar atributos `style="..."` y eventos inline (`onchange=`, `onclick=`, `onsubmit=`) restantes en plantillas del panel y tienda | `core/templates/`, `plataforma/templates/`, `core/static/core/` |
| 4 | **Exterior (UX / Móvil)** | Adaptación móvil de tablas densas (`/panel/erp/reportes/`, `/panel/bodegas/conteo/`, `/plataforma/planes-cobros/`) y estados de carga en botones | `core/static/core/css/`, `core/static/core/js/` |

---

## 2. Prompts listos para ejecutar

### Plan A — Interior: Cobertura >= 85 % en `pqrs` y `core/importaciones.py` — **Completado**
```text
Contexto: la cobertura global del proyecto está en 89 %, pero pqrs/views.py (41 %), pqrs/services.py (64 %),
pqrs/forms.py (76 %) y core/importaciones.py (75 %) siguen por debajo del 85 %.

Tarea:
1. En pqrs/tests.py agrega pruebas completas de vistas y flujos reales:
   - Radicación y seguimiento del comprador en /pqrs/ (flujo B), incluyendo notas internas ocultas al ciudadano
     y encuesta de satisfacción al cerrar.
   - Gestión de PQRS en /panel/pqrs/ (cambio de estado, asignación, respuesta con adjunto válido e inválido > 5 MB
     o extensión prohibida).
   - Bandeja de Intersoft en /plataforma/pqrs/ (acceso exclusivo is_staff, orden con escaladas primero).
2. En core/tests_cobertura.py agrega pruebas de importaciones.py:
   - Archivo .xlsx con filas válidas, filas con errores (código duplicado, precio negativo, stock inválido)
     y resumen de errores por fila sin abortar las filas válidas.
3. Ejecuta `coverage run --rcfile=.coveragerc manage.py test core suscripciones plataforma pqrs soporte --noinput`
   y verifica que cada módulo nuevo quede >= 85 %.

Restricciones: no toques core/facturacion_electronica.py. Pruebas y coverage en verde.
```

---

### Plan B — Interior: Caché compartida con Redis para Gunicorn + Rate Limiting — **Completado**
```text
Contexto: RateLimitMiddleware (core/ratelimit.py) y el throttling de DRF usan django.core.cache.cache. Con varios
workers de Gunicorn en producción, LocMemCache no comparte contadores entre procesos.

Tarea:
1. Agrega soporte opcional de Redis en intersoft/settings.py usando REDIS_URL:
   - Si REDIS_URL está definido, configura CACHES["default"] con RedisCache (django.core.cache.backends.redis.RedisCache
     o redis-py según requirements.txt).
   - Si REDIS_URL está vacío (dev/tests), mantiene LocMemCache sin romper pruebas locales.
2. Agrega el servicio `redis` en compose.prod.yml (con healthcheck) y pasa REDIS_URL al contenedor `web`.
3. Documenta REDIS_URL en .env.example y README.md.
4. Agrega una prueba en core/tests_cobertura.py verificando la configuración de CACHES con y sin REDIS_URL.

Restricciones: no toques la DIAN. `docker compose -f compose.prod.yml config`, `check` y pruebas en verde.
```

---

### Plan C — Exterior: Limpieza de `style="..."` y eventos inline (`onchange`/`onclick`/`onsubmit`) — **Completado**
```text
Contexto: ya se extrajeron todos los <style> y <script> embebidos, pero aún quedan atributos `style="..."`
y eventos inline (`onchange=`, `onclick=`, `onsubmit=`) en plantillas antiguas (detalle.html, planes_cobros.html,
lista.html, conteo.html, cerrar.html, reportes.html, pedido.html, base.html).

Tarea:
1. Reemplaza todos los atributos `onchange=`, `onclick=` y `onsubmit=` en plantillas HTML por atributos `data-*`
   y listeners en archivos JS dentro de core/static/core/js/ (o plataforma/static/plataforma/js/).
2. Mueve los `style="..."` repetidos de detalle.html, planes_cobros.html, lista.html, suscripcion.html y pedido.html
   a clases CSS reutilizables en core/static/core/css/.
3. Verifica con Select-String / grep que queden 0 coincidencias de `onchange=|onclick=|onsubmit=` en *.html.
4. Ejecuta `manage.py check` y toda la suite de pruebas.

Restricciones: no cambies lógica de negocio ni toques core/facturacion_electronica.py. Pruebas en verde.
```

---

### Plan D — Exterior: Adaptación móvil de tablas restantes y feedback de envío — **Completado**
```text
Contexto: /panel/pedidos/, /panel/negocio/pagos/, /mis-pedidos/ y el widget NPS ya están adaptados a celular,
pero faltan las tablas densas de /panel/erp/reportes/, /panel/bodegas/conteo/ y /plataforma/planes-cobros/,
además de protección contra doble clic en formularios lentos.

Tarea:
1. Añade contenedores desplazables horizontales (`.tabla-wrap` con `overflow-x: auto`) y reglas `@media (max-width: 720px)`
   para reportes.html, conteo.html y planes_cobros.html sin romper la vista de escritorio.
2. En core/static/core/js/app.js agrega un manejador global opcional (`data-una-vez` o prevención de doble submit)
   para deshabilitar botones de envío mientras procesan acciones lentas (envío de ticket por correo, verificación Wompi,
   importación Excel).
3. Agrega pruebas de humo de renderizado y ejecuta `manage.py check` + pruebas.

Restricciones: no toques la DIAN. Pruebas en verde.
```

---

## 3. Pendiente de decisión de negocio (fuera de código)
- **DIAN:** elegir proveedor tecnológico (Alegra, Siigo, Facture u otro), resolución de numeración y ambiente de habilitación.
- **Legal:** validar plazos de PQRS (`PQRS_DIAS_RESPUESTA=15`) y texto de política de reembolsos/devoluciones del marketplace.
