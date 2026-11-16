# Verificación de pagos por negocio

Validación local del 15 de noviembre de 2026.

| Comprobación | Resultado |
| --- | --- |
| Suite general `manage.py test core --noinput --parallel 4` | 414 pruebas aprobadas |
| Suite específica después de actualizar `cryptography` | 71 pruebas aprobadas |
| Cobertura de cifrado, formularios, configuración, credenciales y tarifas | 92 % (383 sentencias) |
| `manage.py check` | Sin incidencias |
| `manage.py makemigrations --check --dry-run` | Sin cambios pendientes |
| Ruff: errores de sintaxis, nombres, imports y variables importadas sin usar en los módulos de pagos | Aprobado |
| `pip-audit -r requirements.txt`, incluidas dependencias transitivas | Sin vulnerabilidades conocidas |
| `git diff --check` | Aprobado |
| Migración local 0021 y sincronización de permisos | Aplicadas |

La suite específica cubre separación de negocios, rechazo de cobros sin pasarela, tarifas propias, firma y repetición de avisos, referencia alterada, retorno por ID sin prueba de comercio, rotación de cifrado y migración de credenciales históricas. También comprueba que un reporte de excepción no exponga un secreto sintético.

Se completaron revisiones independientes de código, seguridad y Python. Se corrigieron los hallazgos de autenticación en el retorno, saneamiento de reportes, verificaciones concurrentes, caché, orden de precios y renovación de pedidos históricos.

La cobertura indicada corresponde a `core.cifrado`, `core.forms_pagos`, `core.views_pagos`, `core.pasarelas`, `core.pasarela_negocio` y `core.tarifas`; no es la cobertura global del proyecto. La suite específica se ejecutó con `cryptography==50.0.2`.

No se realizaron cargos reales ni un despliegue. `check --deploy` detecta la configuración local de desarrollo (correo de consola, DEBUG y opciones HTTPS), por lo que esta validación no certifica una instalación de producción. Las pruebas de Wompi utilizan respuestas simuladas; cada comercio debe completar un pago de sandbox con sus llaves y su URL pública antes de activar producción.

Los precios y el cobro de membresías quedan diferidos por decisión del usuario.
