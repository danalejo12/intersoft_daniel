# Reporte de Cobertura de Pruebas (Coverage) — InterSoft
## Evidencia de Calidad de Software (ADSO — SENA)

> **Cobertura global del proyecto (\core\ + \suscripciones\ + \plataforma\ + \pqrs\ + \soporte\, excluyendo \poblar_datos_demo.py\ y \acturacion_electronica.py\): 89%** (8.684 sentencias analizadas, 541 pruebas ejecutadas, 0 fallidas).

\\	ext
Name                                                                    Stmts   Miss  Cover   Missing
-----------------------------------------------------------------------------------------------------
core\__init__.py                                                            0      0   100%
core\acceso.py                                                              3      0   100%
core\admin.py                                                             102      0   100%
core\apps.py                                                                6      0   100%
core\backends.py                                                           17      2    88%   11, 13
core\bienvenida.py                                                         20      1    95%   29
core\bodegas.py                                                           183     13    93%   29-30, 44, 106, 129, 133, 182, 188, 212, 225, 229, 272, 316
core\caja.py                                                              157     19    88%   45-46, 69-70, 77, 93, 99, 103, 117, 131, 134-135, 141, 143, 149, 161, 170-171, 173
core\carrito.py                                                            76      0   100%
core\cifrado.py                                                            61      5    92%   78, 82, 88-89, 96
core\compras.py                                                           129      3    98%   58, 129, 208
core\contabilidad_automatica.py                                           114     10    91%   53, 68, 91, 95, 160, 190-191, 209, 230, 232
core\context_processors.py                                                 11      0   100%
core\erp_forms.py                                                          46      0   100%
core\erp_services.py                                                      159     26    84%   34, 37, 72, 75, 77, 81, 83, 96, 98, 100, 110, 119, 128, 130, 136, 147, 150, 152, 156, 158, 171, 184-186, 188, 204
core\exportaciones.py                                                     140     16    89%   160-166, 221, 223, 231, 240-241, 304-307
core\forms.py                                                             230     40    83%   26-29, 35-36, 40-53, 69-71, 83-88, 97-109, 138, 165, 172, 341, 347, 399, 401, 436, 445, 451, 483
core\forms_equipo.py                                                      113     12    89%   42, 66-69, 113, 123, 129, 136-137, 181-182, 196
core\forms_pagos.py                                                        83      3    96%   55, 77, 108
core\forms_tienda.py                                                       55      0   100%
core\importaciones.py                                                     113     28    75%   20, 23-24, 35-36, 38, 53-54, 61, 67, 87, 94, 96, 98, 101, 111-113, 118-121, 125-127, 131-133
core\impuestos.py                                                           6      0   100%
core\management\__init__.py                                                 0      0   100%
core\management\commands\__init__.py                                        0      0   100%
core\management\commands\liberar_pedidos_vencidos.py                       11      0   100%
core\management\commands\procesar_reservas_y_alertas.py                    31      0   100%
core\management\commands\rotar_secretos_pago.py                            28      4    86%   30-31, 41-42
core\management\commands\sincronizar_permisos.py                           11      0   100%
core\management\commands\tareas_periodicas.py                              21      2    90%   33-34
core\marketplace.py                                                        57      1    98%   125
core\middleware.py                                                         65      4    94%   71-72, 76-77
core\mixins.py                                                             22      0   100%
core\models\__init__.py                                                    12      0   100%
core\models\base.py                                                        16      0   100%
core\models\caja.py                                                        43      2    95%   38, 71
core\models\clientes.py                                                    23      0   100%
core\models\empresas.py                                                    40      0   100%
core\models\erp.py                                                        212      5    98%   30, 120, 218, 224, 241
core\models\inventario.py                                                 153      5    97%   130, 162, 215, 246, 266
core\models\pagos.py                                                       90      3    97%   62, 112, 133
core\models\pedidos.py                                                    146      4    97%   179, 199, 207, 230
core\models\tareas.py                                                      15      1    93%   24
core\models\usuarios.py                                                    63      4    94%   37, 52, 94, 99
core\models\ventas.py                                                      79      2    97%   79, 113
core\negocios.py                                                           23      0   100%
core\notificaciones.py                                                    101      8    92%   17, 26-28, 84, 187-189
core\pagos.py                                                             289     30    90%   89, 93-96, 114, 122, 160-161, 201, 205, 208, 215-216, 257, 268, 274-275, 285, 296-297, 334-336, 355, 385, 388-389, 406, 413
core\pasarela_negocio.py                                                   74      8    89%   74-75, 91, 95-99
core\pasarelas.py                                                          34      5    85%   42-43, 48, 51-52
core\permisos.py                                                           24      2    92%   154-155
core\primeros_pasos.py                                                     18      0   100%
core\pruebas.py                                                             6      0   100%
core\ratelimit.py                                                          47      5    89%   22, 29, 37-39
core\redirecciones.py                                                       6      0   100%
core\reservas.py                                                          105      7    93%   45, 52, 94, 132, 164, 166, 169
core\services.py                                                          102     10    90%   41, 44, 63, 68, 184, 191-193, 237, 239
core\tareas.py                                                             49      0   100%
core\tarifas.py                                                            14      0   100%
core\testing_pagos.py                                                      11      0   100%
core\urls.py                                                                8      0   100%
core\views.py                                                             179     12    93%   218, 244-246, 286-295, 305
core\views_bodegas.py                                                     141     19    87%   55-56, 60, 130-133, 156-157, 186-188, 191-192, 202-204, 217-218, 224, 242
core\views_compra.py                                                      286     25    91%   54-59, 70, 91, 93-94, 144, 150-152, 166-167, 187-188, 213-214, 404-405, 425-426, 435, 438
core\views_equipo.py                                                      111     15    86%   16, 25, 42, 98-99, 124-125, 135-137, 149-150, 158, 169-170
core\views_erp.py                                                         300     35    88%   74, 113, 133-136, 139-144, 204-205, 274, 284-286, 298-299, 302, 311, 313, 329, 333-334, 340-342, 345, 349, 356-358, 470, 479
core\views_facturas.py                                                    219     33    85%   133-135, 138-162, 165, 176, 213, 217-218, 223, 240, 259-260, 324-325, 331, 351-352, 370-371
core\views_inventario.py                                                  180      8    96%   64, 121, 125, 202, 260-261, 265, 268
core\views_pagos.py                                                       117      6    95%   41, 88, 100-102, 132
core\views_pedidos_panel.py                                                96     11    89%   37, 57, 59, 131-132, 147-148, 164-165, 173-174
core\views_pos.py                                                         269     21    92%   36, 99, 140, 153, 216, 219, 245-246, 277-278, 285, 291-293, 306, 354-355, 396, 420, 431-432
core\views_salud.py                                                        10      0   100%
core\views_tienda.py                                                       98      1    99%   108
plataforma\__init__.py                                                      0      0   100%
plataforma\admin.py                                                        26      0   100%
plataforma\apps.py                                                          5      0   100%
plataforma\auditoria.py                                                    21      2    90%   9, 24
plataforma\forms.py                                                       164     12    93%   78, 80, 88, 90, 94, 97, 113, 161, 172, 207, 246, 248
plataforma\metricas.py                                                     69      3    96%   37-38, 58
plataforma\mixins.py                                                       25      1    96%   18
plataforma\models.py                                                      134     13    90%   53, 64, 68, 70, 98, 142, 145, 168, 203, 214-215, 239-240
plataforma\totp.py                                                         39      2    95%   42, 45
plataforma\urls.py                                                          5      0   100%
plataforma\views.py                                                       355     98    72%   180, 208, 212-213, 233-237, 272-273, 288-289, 311-312, 350-351, 367-372, 407-409, 412-424, 448-450, 460-462, 489-496, 504, 507-564, 573-590, 593-607, 620, 639, 662-674, 692, 760, 795-808
pqrs\__init__.py                                                            0      0   100%
pqrs\admin.py                                                              16      0   100%
pqrs\apps.py                                                                5      0   100%
pqrs\dias_habiles.py                                                       43      4    91%   70, 78, 92, 96
pqrs\forms.py                                                              45     11    76%   33-35, 42-49
pqrs\management\__init__.py                                                 0      0   100%
pqrs\management\commands\__init__.py                                        0      0   100%
pqrs\management\commands\escalar_pqrs_vencidas.py                           7      0   100%
pqrs\models.py                                                            109      9    92%   21, 43, 55-56, 170, 176-177, 216-217
pqrs\notificaciones.py                                                     38      3    92%   7, 66, 76
pqrs\services.py                                                          118     43    64%   33, 36-39, 73, 93-98, 117-148, 161-162, 164, 201
pqrs\urls.py                                                                3      0   100%
pqrs\views.py                                                             168     99    41%   36-41, 50-57, 60-61, 64-82, 116-133, 143-148, 158, 161-175, 185-189, 203, 206-250, 275, 277, 298, 313-314, 317-371
soporte\__init__.py                                                         0      0   100%
soporte\admin.py                                                           26      0   100%
soporte\apps.py                                                             9      0   100%
soporte\context_processors.py                                              16      2    88%   19-20
soporte\errores.py                                                        123     19    85%   23, 32, 37-38, 53-54, 60, 77, 87-88, 117-118, 144-145, 155, 178-180, 185
soporte\forms.py                                                           32      0   100%
soporte\models.py                                                         112     13    88%   17-23, 75, 125, 155-156, 187, 227
soporte\urls.py                                                             3      0   100%
soporte\views.py                                                          166     30    82%   33, 42-44, 70, 96, 117, 127-131, 138, 150, 178, 180, 211-215, 218-237, 252, 254, 256, 291
suscripciones\__init__.py                                                   0      0   100%
suscripciones\admin.py                                                     47      1    98%   43
suscripciones\apps.py                                                       7      0   100%
suscripciones\cobros.py                                                   160     21    87%   60-61, 94, 125, 127, 142, 151, 190, 196, 220-223, 233, 241, 243, 246, 250-251, 260-261
suscripciones\exceptions.py                                                42      1    98%   50
suscripciones\management\__init__.py                                        0      0   100%
suscripciones\management\commands\__init__.py                               0      0   100%
suscripciones\management\commands\conciliar_cobros_suscripcion.py           7      0   100%
suscripciones\management\commands\enviar_recordatorios_vencimiento.py       7      0   100%
suscripciones\management\commands\verificar_suscripciones.py                7      0   100%
suscripciones\models.py                                                   172     14    92%   128, 133, 141-142, 202-203, 254, 276, 290-291, 321, 330, 332, 334
suscripciones\permissions.py                                               42      5    88%   22, 34, 44, 71, 74
suscripciones\serializers.py                                               36      2    94%   64, 67
suscripciones\services.py                                                 211     19    91%   92, 187, 280, 284, 329, 331, 339-340, 375, 379, 381, 409-412, 426-427, 437, 480, 492
suscripciones\signals.py                                                    9      0   100%
suscripciones\urls.py                                                       4      0   100%
suscripciones\views.py                                                     55      8    85%   71-81, 119-120
suscripciones\views_panel.py                                              117     13    89%   52, 112, 145-147, 161, 176-177, 181, 184, 187-188, 197
-----------------------------------------------------------------------------------------------------
TOTAL                                                                    8684    924    89%
\