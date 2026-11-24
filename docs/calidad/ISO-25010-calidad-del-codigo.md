# Calidad del software según ISO/IEC 25010 — InterSoft

**Fecha:** 24 de noviembre de 2026 · **Versión:** `main` posterior a `a6e9da6`

ISO/IEC 25010 define 8 características de calidad del producto de software. Este documento cuenta, para cada una, qué hace InterSoft y con qué evidencia se puede verificar. La sección 3 reúne las **normas de código** que el equipo sigue a partir de hoy.

---

## 1. Resumen de la limpieza y documentación del código

| Indicador | Antes | Después |
|---|---|---|
| Módulos con docstring | 84 % (111/131) | **100 %** (131/131) |
| Clases con docstring | 40 % (151/369) | **99 %** (367/369)¹ |
| Funciones con lógica propia sin docstring | 534 | **0**² |
| Advertencias de estilo (ruff, reglas del proyecto) | 154 | **0** |
| Errores lógicos detectables (ruff F) | 53 avisos | **0** |
| Complejidad ciclomática promedio | A (3,65) | **A (3,61)** |
| Funciones con complejidad D o peor | 7 (una con E 34) | **6** (ninguna E o F) |
| Pruebas automatizadas | 578 | **642** |

¹ Las 2 restantes están en `core/facturacion_electronica.py` (DIAN), que no se modifica hasta que el equipo decida el proveedor antes del despliegue.
² Por la norma de la sección 3.2: no se exige docstring a los métodos estándar de Django ni a funciones de una sola sentencia sin ramas. El 45 % de funciones con docstring cuenta también esas funciones, que no lo necesitan.

---

## 2. Las 8 características de ISO/IEC 25010 en InterSoft

### 2.1 Adecuación funcional (completitud, corrección y pertinencia)
- Cada módulo funcional (marketplace, compra, pagos, POS, inventario por bodegas, ERP, PQRS, consola) tiene pruebas automáticas de sus casos de uso. Son 642 pruebas en total.
- Recorridos completos de principio a fin en `core/tests_calidad_e2e.py`: crear negocio → vender → pagar → facturar → despachar; caja POS; PQRS; consola con 2FA.
- Corrección de cálculos: IVA con redondeo único (`core/impuestos.py`), aportes de nómina (`core/tests_nomina_aportes.py`), arqueo de caja y partida doble contable.

### 2.2 Eficiencia de desempeño (tiempo, recursos y capacidad)
- Sin consultas N+1 en las páginas clave (`core/tests_calidad_consultas.py`): el número de consultas no crece con la cantidad de datos.
- `select_related`/`prefetch_related` en listas, subconsultas para el ranking del marketplace y caché Redis en producción.
- Tiempos medidos en el servidor: las páginas públicas responden en 0,03–0,20 s.

### 2.3 Compatibilidad (coexistencia e interoperabilidad)
- API REST documentada con OpenAPI/Swagger (`/api/docs/`).
- Integración con Wompi: checkout firmado, webhooks verificados y consulta de transacciones.
- Exportación a PDF (facturas) y Excel (reportes, pedidos, turnos); importación de productos desde Excel.
- Base de datos PostgreSQL 16; despliegue en contenedores (Docker Compose).

### 2.4 Usabilidad (aprendizaje, operabilidad, protección contra errores, accesibilidad)
- Buscador global (Ctrl + K), menú agrupado por tareas, inicio con «Para hoy» y guía de primeros pasos.
- Protección contra errores: confirmación en acciones delicadas, validaciones con mensajes claros y carrito que se corrige solo si cambia el stock.
- Accesibilidad: etiquetas en todos los campos (verificado por `plataforma/tests_revision_ui.py`), navegación por teclado y modo día y noche.

### 2.5 Fiabilidad (madurez, disponibilidad, tolerancia a fallos, recuperabilidad)
- Transacciones atómicas y bloqueo de filas (`select_for_update`) en ventas, reservas, pagos y bodegas; idempotencia en pagos, POS y tesorería.
- Tareas periódicas con registro, reintento y alerta tras 3 fallos (`core/tareas.py`).
- Registro automático de errores 500 agrupados (`soporte/errores.py`), copias de seguridad de PostgreSQL (`deploy/backup_postgres.sh`) y panel de salud en Operación.

### 2.6 Seguridad (confidencialidad, integridad, no repudio, responsabilidad, autenticidad)
- **Confidencialidad:** aislamiento estricto entre negocios (cada consulta se filtra por empresa) y llaves de pago cifradas (Fernet, con rotación).
- **Integridad:** CSRF, CSP sin scripts en línea, firma de Wompi verificada con `hmac.compare_digest` y monto y moneda validados en el servidor.
- **Autenticidad:** bloqueo por intentos (django-axes), 2FA (TOTP) en la consola y límite de peticiones que no se deja engañar (QA-01 y QA-02 corregidos).
- **No repudio y responsabilidad:** bitácora de auditoría de la consola, con IP confiable; auditoría de cambios de pagos y del historial de suscripciones.
- 0 vulnerabilidades conocidas en las dependencias (pip-audit).

### 2.7 Mantenibilidad (modularidad, reusabilidad, analizabilidad, modificabilidad, capacidad de prueba)
- **Modularidad:** 6 aplicaciones Django separadas (`core`, `suscripciones`, `plataforma`, `pqrs`, `soporte`, `datos_personales`) y servicios de dominio separados de las vistas (`services.py`, `bodegas.py`, `cobros.py`…).
- **Analizabilidad:** todo el código documentado con docstrings que explican qué hace cada parte y por qué. Lo exige `core/tests_documentacion.py`.
- **Modificabilidad:** complejidad promedio A. La función más compleja (`DetalleERP.post`, E 34) se dividió en un método por acción (A 5).
- **Capacidad de prueba:** 642 pruebas, cobertura de líneas y ramas del 89 % (el CI exige 85 %).

### 2.8 Portabilidad (adaptabilidad, instalabilidad, reemplazabilidad)
- Toda la configuración por variables de entorno (`.env`, `python-decouple`), sin valores fijos en el código.
- Instalación reproducible con `requirements.txt` fijado, `Dockerfile` y `compose.prod.yml`.
- Funciona en Windows (desarrollo) y Linux (contenedores); la PWA se puede instalar en celular y computador.

---

## 3. Normas de código del proyecto

### 3.1 Estilo
- Se valida con **ruff** usando `intersoft/ruff.toml`: errores lógicos, espacios, sintaxis moderna, simplificaciones, buenas prácticas de Django y rendimiento. Debe dar «All checks passed!».
- Largo de línea: **120 caracteres** para el código nuevo. Hay 564 líneas heredadas más largas, que se corrigen al tocar cada archivo para no generar conflictos.
- Nombres descriptivos en español, como el dominio del negocio. Nada de `l`, `x` ni `tmp`.

### 3.2 Documentación (PEP 257)
- **Todo módulo** empieza con un docstring que dice para qué existe.
- **Toda clase** tiene docstring. En las vistas se indica qué hace, su ruta y el permiso que exige.
- **Toda función con lógica propia** tiene docstring: qué hace, qué devuelve y qué excepción lanza, si importa.
- No necesitan docstring los métodos estándar de Django cuyo nombre ya lo explica (`get`, `post`, `get_queryset`, `form_valid`, `clean_*`, `__str__`…) ni las funciones de una sola sentencia sin ramas.
- Los comentarios (`#`) explican **por qué**, no qué. Ejemplo: `# En orden de producto para evitar bloqueos cruzados`.
- `core/tests_documentacion.py` hace fallar la suite si algo nuevo queda sin documentar.

### 3.3 Reglas de diseño
- La lógica de negocio va en servicios (`*services.py`, `bodegas.py`, `cobros.py`…), no en las vistas ni en las plantillas.
- Toda consulta del panel se filtra por `request.empresa`; solo `core/marketplace.py` cruza negocios, y solo con lo publicado.
- Operaciones con dinero o stock: `transaction.atomic()` y `select_for_update()`, en un orden fijo de bloqueo (productos y luego empresa).
- Dinero siempre en `Decimal`, nunca `float`.
- Secretos: nunca en el código ni en los registros. Se guardan cifrados y se muestran solo con sus últimos 4 caracteres.

### 3.4 Antes de subir un cambio
```bash
cd intersoft
ruff check .                       # estilo: «All checks passed!»
python manage.py check             # configuración de Django
python manage.py makemigrations --check
python manage.py test              # incluye la prueba de documentación
```

---

## 4. Deuda técnica conocida
- 6 funciones con complejidad D: `importar_productos_excel`, `otorgar_cortesia`, `registrar_venta`, `VenderView.post`, `ListaERP` y el comando `poblar_datos_demo`. Se pueden dividir como se hizo con `DetalleERP.post`.
- 564 líneas de más de 120 caracteres heredadas.
- Facturación electrónica DIAN pendiente de decisión (ver el informe de pruebas).
