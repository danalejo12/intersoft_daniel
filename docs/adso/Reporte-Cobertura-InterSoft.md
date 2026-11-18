# Reporte de Cobertura de Pruebas (Coverage) — InterSoft
## Evidencia de Calidad de Software (ADSO — SENA)

> **Cobertura global del proyecto (`core` + `suscripciones`, excluyendo `poblar_datos_demo.py` y `facturacion_electronica.py`): 92%** (6.183 sentencias analizadas, 525 pruebas ejecutadas, 0 fallidas).

```text
﻿Name                                                                          Stmts   Miss  Cover   Missing
-----------------------------------------------------------------------------------------------------------
intersoft\core\__init__.py                                                        0      0   100%
intersoft\core\acceso.py                                                          3      0   100%
intersoft\core\admin.py                                                         102      0   100%
intersoft\core\apps.py                                                            6      0   100%
intersoft\core\backends.py                                                       17      2    88%   11, 13
intersoft\core\bienvenida.py                                                     20      1    95%   29
intersoft\core\bodegas.py                                                       135      9    93%   29-30, 44, 106, 129, 133, 182, 188, 212
intersoft\core\caja.py                                                          157     19    88%   45-46, 69-70, 77, 93, 99, 103, 117, 131, 134-135, 141, 143, 149, 161, 170-171, 173
intersoft\core\carrito.py                                                        76      0   100%
intersoft\core\cifrado.py                                                        61      5    92%   78, 82, 88-89, 96
intersoft\core\compras.py                                                       129      3    98%   58, 129, 208
intersoft\core\contabilidad_automatica.py                                       114     10    91%   53, 68, 91, 95, 160, 190-191, 209, 230, 232
intersoft\core\context_processors.py                                             10      0   100%
intersoft\core\erp_forms.py                                                      44      0   100%
intersoft\core\erp_services.py                                                  157     26    83%   34, 37, 68, 71, 73, 77, 79, 92, 94, 96, 106, 115, 124, 126, 132, 143, 146, 148, 152, 154, 167, 180-182, 184, 200
intersoft\core\exportaciones.py                                                 111     12    89%   160-166, 221, 223, 231, 240-241
intersoft\core\forms.py                                                         230     40    83%   26-29, 35-36, 40-53, 69-71, 83-88, 97-109, 138, 165, 172, 341, 347, 399, 401, 436, 445, 451, 483
intersoft\core\forms_equipo.py                                                  113     12    89%   42, 66-69, 113, 123, 129, 136-137, 181-182, 196
intersoft\core\forms_pagos.py                                                    83      3    96%   55, 77, 108
intersoft\core\forms_tienda.py                                                   55      0   100%
intersoft\core\impuestos.py                                                       6      0   100%
intersoft\core\management\__init__.py                                             0      0   100%
intersoft\core\management\commands\__init__.py                                    0      0   100%
intersoft\core\management\commands\liberar_pedidos_vencidos.py                   11      0   100%
intersoft\core\management\commands\procesar_reservas_y_alertas.py                26      0   100%
intersoft\core\management\commands\rotar_secretos_pago.py                        28      4    86%   30-31, 41-42
intersoft\core\management\commands\sincronizar_permisos.py                       11      0   100%
intersoft\core\management\commands\tareas_periodicas.py                          21      2    90%   33-34
intersoft\core\marketplace.py                                                    57      1    98%   125
intersoft\core\middleware.py                                                     29      0   100%
intersoft\core\mixins.py                                                         22      0   100%
intersoft\core\models\__init__.py                                                12      0   100%
intersoft\core\models\base.py                                                    16      0   100%
intersoft\core\models\caja.py                                                    43      2    95%   38, 71
intersoft\core\models\clientes.py                                                23      0   100%
intersoft\core\models\empresas.py                                                40      0   100%
intersoft\core\models\erp.py                                                    211      5    98%   30, 112, 210, 216, 233
intersoft\core\models\inventario.py                                             110      3    97%   129, 161, 213
intersoft\core\models\pagos.py                                                   90      3    97%   62, 112, 133
intersoft\core\models\pedidos.py                                                136      3    98%   179, 199, 207
intersoft\core\models\tareas.py                                                  15      1    93%   24
intersoft\core\models\usuarios.py                                                63      4    94%   37, 52, 94, 99
intersoft\core\models\ventas.py                                                  79      2    97%   79, 113
intersoft\core\negocios.py                                                       23      0   100%
intersoft\core\notificaciones.py                                                 97      8    92%   17, 26-28, 83, 180-182
intersoft\core\pagos.py                                                         289     30    90%   89, 93-96, 114, 122, 160-161, 201, 205, 208, 215-216, 257, 268, 274-275, 285, 296-297, 334-336, 355, 385, 388-389, 406, 413
intersoft\core\pasarela_negocio.py                                               74      8    89%   74-75, 91, 95-99
intersoft\core\pasarelas.py                                                      34      5    85%   42-43, 48, 51-52
intersoft\core\permisos.py                                                       24      2    92%   154-155
intersoft\core\primeros_pasos.py                                                 18      0   100%
intersoft\core\pruebas.py                                                         6      0   100%
intersoft\core\redirecciones.py                                                   6      0   100%
intersoft\core\reservas.py                                                      105      7    93%   45, 52, 94, 132, 164, 166, 169
intersoft\core\services.py                                                      102     10    90%   41, 44, 63, 68, 184, 191-193, 237, 239
intersoft\core\tareas.py                                                         49      0   100%
intersoft\core\tarifas.py                                                        14      0   100%
intersoft\core\testing_pagos.py                                                  11      0   100%
intersoft\core\urls.py                                                            8      0   100%
intersoft\core\views.py                                                         179     12    93%   218, 244-246, 286-295, 305
intersoft\core\views_bodegas.py                                                  68      3    96%   54-55, 59
intersoft\core\views_compra.py                                                  246     19    92%   54-59, 70, 91, 93-94, 144, 150-152, 166-167, 187-188, 213-214
intersoft\core\views_equipo.py                                                  111     15    86%   16, 25, 42, 98-99, 124-125, 135-137, 149-150, 158, 169-170
intersoft\core\views_erp.py                                                     282     35    88%   74, 113, 133-136, 139-144, 204-205, 274, 284-286, 298-299, 302, 311, 313, 329, 333-334, 340-342, 345, 349, 356-358, 397, 406
intersoft\core\views_facturas.py                                                219     33    85%   133-135, 138-162, 165, 176, 213, 217-218, 223, 240, 259-260, 324-325, 331, 351-352, 370-371
intersoft\core\views_inventario.py                                              180      8    96%   64, 121, 125, 202, 260-261, 265, 268
intersoft\core\views_pagos.py                                                   117      6    95%   41, 88, 100-102, 132
intersoft\core\views_pedidos_panel.py                                            96     11    89%   37, 57, 59, 131-132, 147-148, 164-165, 173-174
intersoft\core\views_pos.py                                                     233     17    93%   35, 98, 139, 152, 215, 218, 244-245, 276-277, 284, 290-292, 305, 353-354
intersoft\core\views_salud.py                                                    10      0   100%
intersoft\core\views_tienda.py                                                   98      1    99%   108
intersoft\suscripciones\__init__.py                                               0      0   100%
intersoft\suscripciones\admin.py                                                 47      1    98%   43
intersoft\suscripciones\apps.py                                                   7      0   100%
intersoft\suscripciones\cobros.py                                               140     18    87%   59-60, 93, 117, 156, 162, 182-185, 195, 203, 205, 208, 212-213, 222-223
intersoft\suscripciones\exceptions.py                                            42      1    98%   50
intersoft\suscripciones\management\__init__.py                                    0      0   100%
intersoft\suscripciones\management\commands\__init__.py                           0      0   100%
intersoft\suscripciones\management\commands\conciliar_cobros_suscripcion.py       7      0   100%
intersoft\suscripciones\management\commands\verificar_suscripciones.py            7      0   100%
intersoft\suscripciones\models.py                                               123      8    93%   128, 133, 193-194, 238, 260, 274-275
intersoft\suscripciones\permissions.py                                           42      5    88%   22, 34, 44, 71, 74
intersoft\suscripciones\serializers.py                                           36      2    94%   64, 67
intersoft\suscripciones\services.py                                             187     17    91%   86, 181, 274, 278, 323, 325, 333-334, 369, 373, 375, 403-406, 420-421, 431
intersoft\suscripciones\signals.py                                                9      0   100%
intersoft\suscripciones\urls.py                                                   4      0   100%
intersoft\suscripciones\views.py                                                 55      8    85%   71-81, 119-120
intersoft\suscripciones\views_panel.py                                          106     13    88%   52, 112, 138-140, 154, 169-170, 174, 177, 180-181, 190
-----------------------------------------------------------------------------------------------------------
TOTAL                                                                          6183    475    92%
```
