# Informe de pruebas de calidad: caja negra y caja blanca

**Proyecto:** InterSoft (marketplace + SaaS multiempresa + POS + ERP)
**Fecha:** 24 de noviembre de 2026
**Versión probada:** `main` en `a6e9da6`, igual a GitHub, sin cambios locales
**Entorno:** Windows 11 · Python 3.14 · Django 6.1.2 · PostgreSQL · servidor de desarrollo local

---

## 1. Resultado general

| Indicador | Resultado |
|---|---|
| Pruebas automatizadas del proyecto | **578 de 578 pasan** |
| Pruebas nuevas de esta evaluación | **23**: 21 pasan y 2 documentan defectos (*expected failure*) |
| Pruebas de comportamiento del buscador global (JavaScript, navegador simulado) | **17 de 17 pasan** |
| Cobertura de código (líneas **y ramas**) | **89 %**; el CI exige 85 % |
| Vulnerabilidades conocidas en dependencias | **0** (11 paquetes) |
| Revisión de despliegue (`check --deploy` con configuración de producción) | Sin errores. 2 avisos opcionales de HSTS |
| Consultas N+1 en las 7 páginas medidas | **Ninguna** |
| Defectos encontrados | **3 de severidad media** y **2 de severidad baja**. Ninguno crítico |

**Conclusión:** los recorridos principales funcionan de punta a punta: crear un negocio, vender en línea, pagar, facturar, vender en el punto de venta, atender PQRS y entrar a la consola con 2FA. Las protecciones básicas de seguridad están en su lugar. Antes de desplegar conviene corregir **QA-01** y **QA-02** (límite de peticiones) y decidir **QA-03** (aportes de nómina).

---

## 2. Caja blanca: revisión con el código a la vista

### 2.1 Cobertura de líneas y ramas

Se midió con `coverage --branch` sobre la suite completa: 9.055 sentencias y 2.090 ramas.

| Módulo con menos cobertura | Cobertura | Qué queda sin probar |
|---|---|---|
| `core/erp_services.py` | 77 % | Mensajes de error al recibir compras, aprobar nómina y completar producción |
| `core/forms.py` | 77 % | Validaciones de fotos y algunos controles de producto |
| `pqrs/services.py` | 79 % | Cambios de estado y escalamiento |
| `suscripciones/permissions.py` | 82 % | Permisos de la API para casos sin empresa |
| `soporte/errores.py` | 82 % | Rutas de error interno del propio registro de errores |

Los demás módulos están entre 83 % y 100 %.

### 2.2 Análisis estático (ruff: reglas F, E9, B, DJ)

- **Ningún error real**: no hay nombres sin definir, código inalcanzable ni errores típicos de Django.
- 53 avisos de mantenimiento (ver **QA-04**). La mitad son reexportaciones intencionales en `core/models/__init__.py`.

### 2.3 Seguridad del código (bandit, severidad media o alta)

| Hallazgo | Veredicto |
|---|---|
| B310 `urlopen` en `pagos.py`, `pasarela_negocio.py`, `notificaciones.py` y `poblar_datos_demo.py` | **Falso positivo**: las direcciones son fijas y `https` (Wompi, WhatsApp, imágenes de demostración) |
| B104 `0.0.0.0` en `ratelimit.py` | **Falso positivo** como "puerto abierto"; al revisarlo apareció **QA-01** |

### 2.4 Dependencias (pip-audit)

Sin vulnerabilidades conocidas en `requirements.txt`, y `pip check` no encontró dependencias rotas.

### 2.5 Complejidad (radon)

- **Complejidad promedio: A (3,65).**
- Funciones difíciles de mantener (ver **QA-05**):

| Función | Complejidad |
|---|---|
| `DetalleERP.post` (`core/views_erp.py`) | **E (34)** |
| `importar_productos_excel` (`core/importaciones.py`) | D (28) |
| `otorgar_cortesia` (`suscripciones/services.py`) | D (25) |
| `registrar_venta` (`core/caja.py`) | D (24) |
| `VenderView.post` (`core/views_pos.py`) | D (24) |
| `Command.handle` (`poblar_datos_demo`) | D (22) |
| `ListaERP` (`core/views_erp.py`) | D (21) |

### 2.6 Rendimiento: consultas a la base de datos

Prueba `core/tests_calidad_consultas.py`. Cada página se carga con 3 registros y con 30, y se cuentan las consultas.

- Páginas medidas: marketplace, tienda del negocio, inicio del panel, productos, pedidos web, facturas y negocios de la consola.
- **Resultado:** ninguna supera la tolerancia de 4 consultas extra. No hay problema N+1.

### 2.7 Configuración

- `check --deploy` con `DEBUG=False`, clave segura, dominio, correo y clave de cifrado propia: sin errores.
- Solo quedan avisos opcionales de HSTS: `SECURE_HSTS_INCLUDE_SUBDOMAINS` y `SECURE_HSTS_PRELOAD`.
- Migraciones: ninguna pendiente y ninguna por crear.

### 2.8 Revisión manual de la función más compleja (`DetalleERP.post`)

- Cada acción exige el permiso `<módulo>.gestionar`, y contabilizar exige además `contabilidad.gestionar`. Todo corre dentro de una transacción con bloqueo de fila.
- Se encontró **QA-03** en la acción «Calcular aportes».

---

## 3. Caja negra: comportamiento visto desde afuera

Prueba `core/tests_calidad_e2e.py`:
- solo usa HTTP, como una persona con el navegador;
- lo único simulado es Wompi, que es un sistema externo.

### 3.1 Recorridos completos

| Recorrido | Resultado |
|---|---|
| **Negocio y compra en línea**: registro → crear negocio → categoría → producto con stock → se ve en el marketplace → carrito sin cuenta → registro sin perder el carrito → datos de envío → reserva de stock → pago en Wompi, sin exponer el secreto → pedido pagado → factura por el mismo total → kardex → opinión con «Compra verificada» → la dueña despacha con guía → una persona ajena recibe 404 | ✅ |
| **Caja POS**: abrir con base → vender con cambio → ticket → rechazar ventas con cantidad 0, negativa, mayor al stock o pago insuficiente → cerrar con arqueo a ciegas y diferencia correcta → stock descontado | ✅ |
| **PQRS**: el comprador radica (radicado `PQRS-AAAA-NNNNN`) → el negocio responde → el comprador ve la respuesta → califica y la PQRS queda cerrada | ✅ |
| **Consola de plataforma**: sin sesión va al login → activa el 2FA con un código real (rechaza uno falso) → entra → ejecuta una tarea desde Operación | ✅ |

### 3.2 Particiones de equivalencia y valores límite

| Entrada | Casos | Resultado |
|---|---|---|
| Cantidad en el carrito, con stock 3 | −1, 0, 1, 3, 4, «abc», vacío | ✅ Se ajusta a 1…3 |
| Precio del producto | −1, 0, 0,01, «abc», 9.999.999.999,99, 99.999.999.999 | ✅ Acepta solo los válidos y en rango |
| Código de producto repetido en el mismo negocio | — | ✅ Rechazado |
| Datos de envío | correo inválido, teléfono, dirección o nombre vacíos | ✅ No se crea pedido |
| Stock que cambia justo al pagar | — | ✅ Vuelve al carrito sin crear pedido |

### 3.3 Seguridad desde afuera

| Ataque o control | Resultado |
|---|---|
| Entrar al panel o a la consola sin sesión | ✅ Redirige al login |
| Ver, editar o mover productos de otro negocio | ✅ 404 |
| Enviar formularios sin token CSRF | ✅ 403 |
| HTML o `<script>` en el nombre de un producto | ✅ Se muestra como texto |
| `next=` hacia un sitio externo al iniciar sesión | ✅ No redirige afuera |
| Cabeceras de seguridad | ✅ CSP sin `unsafe-inline` en scripts, `X-Frame-Options: DENY`, `nosniff` |
| 5 claves erradas y luego la correcta | ✅ Bloqueado |
| Más de 10 registros por minuto desde una IP | ✅ Responde 429 |
| Evadir el límite cambiando `X-Forwarded-For` | ❌ **QA-01** |
| Límite al registrar negocios | ❌ **QA-02** |

### 3.4 Pruebas contra el servidor real

- **17 rutas públicas** respondieron con el código esperado, en **0,03 a 0,20 s**.
- Rutas inexistentes: 404. Método no permitido: 405. POST sin CSRF: 403.
- `/manifest.webmanifest` en la raíz da 404, pero **no es defecto**: las páginas lo enlazan en `/static/core/manifest.webmanifest`, que responde 200.
- `/api/docs/` abre sin sesión porque el entorno local tiene `DEBUG=True`. En producción exige usuario del personal: **no es defecto**.

### 3.5 Buscador global (Ctrl + K)

- Se cargó el JavaScript real en un navegador simulado (jsdom) y se probaron 17 comportamientos.
- Entre ellos: abrir con Ctrl+K y con «/», buscar sin tildes y por sinónimos, flechas, Enter, Esc, recientes, búsqueda con `?q=` y cambio de tema.
- **17 de 17 pasan.**

---

## 4. Defectos

| ID | Severidad | Tipo | Descripción | Evidencia |
|---|---|---|---|---|
| **QA-01** | Media | Seguridad | El límite de peticiones toma la IP del **primer valor de `X-Forwarded-For`**, que el cliente puede inventar. Cambiando ese valor en cada petición se evade el límite en registro, recuperación de contraseña, checkout, PQRS públicas y webhooks. El ingreso sigue protegido por django-axes. | `core/ratelimit.py:18-23` · prueba `test_limite_no_se_evade_cambiando_x_forwarded_for` |
| **QA-02** | Media | Seguridad / configuración | Dos reglas del límite apuntan a rutas que no existen: `/registrar-negocio/` (la real es `/negocio/registrar/`) y `/plataforma/login/`. **Registrar negocios no tiene límite.** | `core/ratelimit.py:9,11` · prueba `test_registrar_negocios_tiene_limite` |
| **QA-03** | Media | Lógica de negocio (requiere decisión) | «Calcular aportes» de la nómina envía el campo **adicionales** como **auxilio de transporte**, que no aporta a salud ni pensión. Si los adicionales son salariales (horas extra, comisiones), las deducciones quedan por debajo. Ejemplo: base $1.300.000 + $200.000 → hoy deduce $104.000; debería deducir $120.000. | `core/views_erp.py`, acción `calcular_aportes` → `calcular_aportes_nomina_colombia(auxilio_transporte=obj.adicionales)` |
| **QA-04** | Baja | Mantenimiento | 53 avisos estáticos: importaciones sin uso, la variable `estilo_titulo` sin usar en `core/exportaciones.py:38` y la variable de bucle `nombre` sin usar en `core/erp_forms.py:14`. | Salida de ruff |
| **QA-05** | Baja | Mantenibilidad | 7 funciones con complejidad D o E (ver 2.5); `DetalleERP.post` tiene 34 caminos. | Salida de radon |

### Corrección sugerida

- **QA-01**: usar `REMOTE_ADDR`, que nginx fija con `X-Real-IP`, o tomar de `X-Forwarded-For` solo el valor que agrega el proxy de confianza (el último), según un ajuste `RATELIMIT_PROXIES_DE_CONFIANZA`.
- **QA-02**: corregir las rutas de las reglas a `/negocio/registrar/` y quitar `/plataforma/login/`, o derivarlas con `reverse()` para que no vuelvan a desalinearse. Cuando se corrijan QA-01 y QA-02, quitar el `@expectedFailure` de sus pruebas.
- **QA-03**: definir si «adicionales» es salarial. Si lo es, pasar `adicionales_salariales=obj.adicionales`; si se necesitan ambos conceptos, separar el auxilio de transporte en otro campo.
- **QA-05**: dividir `DetalleERP.post` en un método por acción, por ejemplo con un diccionario `acción → función`.

---

## 4.1 Estado tras la corrección (mismo día)

| ID | Estado | Qué se hizo | Prueba que lo protege |
|---|---|---|---|
| **QA-01** | ✅ Corregido | La IP del límite ya no sale del primer valor de `X-Forwarded-For`. Nuevo ajuste `RATELIMIT_PROXIES_DE_CONFIANZA`: con 0 (local) se usa `REMOTE_ADDR`; con 1 (detrás de nginx, ya configurado en `compose.prod.yml`) se toma la IP que agregó nginx, contando desde la derecha. django-axes usa la misma regla en producción. | `core/tests_ratelimit.py` y `test_limite_no_se_evade_cambiando_x_forwarded_for`, que ya pasa sin `expectedFailure` |
| **QA-02** | ✅ Corregido | La regla de registro de negocios apunta a `/negocio/registrar/` y se quitó `/plataforma/login/`. | `test_cada_regla_apunta_a_una_ruta_que_existe` y `test_registrar_negocios_tiene_limite` |
| **QA-03** | ✅ Corregido | La nómina tiene un campo opcional **«Auxilio de transporte»**, que se paga pero no aporta a salud ni pensión. Los **adicionales** pasan a ser **salariales** y aportan. El neto y la cuenta por pagar incluyen el auxilio. Migración `core/0030`. | `core/tests_nomina_aportes.py`: el ejemplo del informe ahora deduce $120.000 |
| **QA-04** | ✅ Corregido | Se completó `__all__` en `core/models/__init__.py` y en `core/views.py`. Se eliminaron las importaciones sin uso, el estilo PDF sin usar y la variable de bucle sin usar. ruff: «All checks passed!» | ruff `--select F,E9,B,DJ` |
| **QA-05** | ✅ Corregido en lo más grave · ⚠️ deuda pendiente | `DetalleERP.post` pasó de **E (34)** a **A (5)**: una tabla `(módulo, acción) → método`, con cada acción en su propio método de complejidad A o B. Las otras 6 funciones con nota D siguen siendo deuda técnica para un próximo ciclo. | Las 33 pruebas del ERP y la nómina siguen pasando |

**Resultado tras corregir:** 610 de 610 pruebas pasan (578 anteriores + 32 nuevas) y ninguna queda marcada como *expected failure*.

---

## 5. Riesgos conocidos fuera de este alcance

- **Facturación electrónica DIAN**: sigue en espera por decisión del equipo. El botón «Emitir DIAN» usa el simulador y marca las facturas como ACEPTADAS con un CUFE ficticio. **Debe resolverse antes del despliegue.**
- El webhook de Wompi no se probó contra un dominio público real; en local se confirma consultando la transacción.
- No se hicieron pruebas de carga ni de navegador real (Selenium/Playwright).

---

## 6. Cómo repetir las pruebas

```bash
cd intersoft
# Suite completa con cobertura de ramas (igual que el CI, más ramas)
pip install coverage
coverage run --rcfile=.coveragerc --branch manage.py test --noinput
coverage report --rcfile=.coveragerc

# Solo las pruebas nuevas de esta evaluación
python manage.py test core.tests_calidad_e2e core.tests_calidad_consultas

# Análisis estático, seguridad, complejidad y dependencias
pip install ruff bandit radon pip-audit
ruff check . --select F,E9,B,DJ --exclude "*/migrations/*"
bandit -r . -ll -x "*/tests*.py,*/migrations"
radon cc . -nd -s -e "*/migrations/*,*tests*"
pip-audit -r ../requirements.txt

# Revisión de despliegue con variables de producción
DEBUG=False DJANGO_SECRET_KEY=... ALLOWED_HOSTS=... python manage.py check --deploy
```
