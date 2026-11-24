# Cumplimiento de la Ley 1581 de 2012 (protección de datos personales) — InterSoft

**Fecha:** 24 de noviembre de 2026 · **Normas:** Ley 1581 de 2012, Decreto 1377 de 2013 (compilado en el Decreto 1074 de 2015, capítulos 25 y 26)

La ley tiene dos partes:

- **La parte técnica**, que hace el software. Este documento dice dónde está cada una.
- **La parte legal y administrativa**, que hace la empresa. Ningún programa puede hacerla por ella. Está en la sección 3.

> Este documento no reemplaza la revisión de un abogado. Los textos de la política y de los avisos deben revisarse antes de salir a producción.

---

## 1. Qué hace el software (lista de verificación)

| Exigencia legal | Artículo | Cómo lo cumple InterSoft | Dónde está |
|---|---|---|---|
| Autorización **previa, expresa e informada** | Ley 1581 art. 9; Decreto 1377 art. 5 y 7 | El registro tiene una casilla obligatoria que **no viene marcada**, con enlace a la política. Sin marcarla no se crea la cuenta. | `core/forms_tienda.py` (`acepta_datos`) |
| **Prueba** de la autorización | Decreto 1377 art. 8 | Se guarda la versión de la política, las finalidades aceptadas, la fecha, la IP real, el navegador y el medio. Nunca se borra ni se edita, ni siquiera desde el admin. | `datos_personales/models.py` (`AutorizacionDatos`) |
| Volver a pedir la autorización si cambia la política | Decreto 1377 art. 5 | Al cambiar `VERSION_POLITICA`, a cada persona se le pide aceptar de nuevo al ingresar. Las cuentas creadas antes de esta función también deben aceptar. | `datos_personales/middleware.py` |
| **Política de tratamiento** con su contenido mínimo | Decreto 1377 art. 13 | `/privacidad/` incluye responsable, datos tratados, finalidades, encargados, derechos, procedimiento y plazos, área responsable, menores, seguridad, cookies, vigencia y versión. | `core/templates/core/tienda/legal/privacidad.html` |
| **Aviso de privacidad** donde se recogen datos | Decreto 1377 art. 14-15 | Aviso corto en el registro, en el pago (datos de envío) y en las PQRS. | `registro.html`, `datos_envio_campos.html`, `comprador_nueva.html` |
| Derecho a **conocer** y acceso gratuito | Ley 1581 art. 8 a) y e) | «Mis datos personales» → **Descargar mis datos** (archivo JSON con cuenta, pedidos, opiniones, PQRS, autorizaciones y solicitudes). | `/mis-datos/`, `services.exportar_datos` |
| Derecho a **prueba de la autorización** | art. 8 b) | La página muestra el historial de autorizaciones (fecha, versión, medio y estado). | `/mis-datos/` |
| Derecho a **actualizar y rectificar** | art. 8 a) | Enlace a «Mi perfil» y solicitud formal «Corregir datos inexactos». | `/perfil/`, `/mis-datos/` |
| Derecho a **revocar** y **suprimir** | art. 8 e); art. 15 | Solicitud con radicado. El equipo la atiende en la consola con el botón «Responder y suprimir datos». | `/plataforma/datos-personales/` |
| **Plazos**: consultas en 10 días hábiles, reclamos en 15 | Ley 1581 art. 14 y 15 | Cada solicitud recibe un radicado `HD-AAAA-00001` y una fecha límite en días hábiles (sin festivos de Colombia). Las vencidas se marcan en rojo en la consola. | `services.radicar_solicitud`, `pqrs/dias_habiles.py` |
| Acuse de recibo y respuesta por escrito | art. 14-15 | Correo al titular con el radicado y la fecha límite; correo con la respuesta; aviso al responsable. | `services.py` |
| Supresión **sin violar** la retención legal | art. 15; Código de Comercio art. 60; Estatuto Tributario art. 632 | Se anonimizan la cuenta y los datos de envío. Se borran opiniones, favoritos y encuestas. Las facturas y los pedidos se conservan como soporte contable, sin datos que identifiquen a la persona. | `services.suprimir_datos_titular` |
| No dejar un negocio sin administrador | — | La supresión se detiene si la persona es la única administradora de un negocio activo, y se le explica qué hacer. | `SupresionNoPermitida` |
| Datos de **menores** | Ley 1581 art. 7; Decreto 1377 art. 12 | Casilla obligatoria «Declaro que soy mayor de 18 años». La política lo explica. | `mayor_edad` |
| **Seguridad** | Ley 1581 art. 4 g) y 17 d) | HTTPS, contraseñas con huella, llaves de pago cifradas, 2FA en la consola, bloqueo por intentos, aislamiento entre negocios, bitácora de auditoría y copias de seguridad. | ver `ISO-25010-calidad-del-codigo.md` §2.6 |
| Responsabilidad demostrada | Decreto 1377 art. 26 | Toda acción sobre solicitudes queda en la bitácora de la consola (quién, cuándo, desde qué IP). | `plataforma/auditoria.py` |
| Datos de los clientes de cada negocio (POS) | Ley 1581 art. 17 | El negocio es responsable de esos datos. La ficha del cliente tiene «autorizó el tratamiento de datos» y guarda la fecha del registro. | `Cliente.autoriza_datos`, `autoriza_datos_en` |
| Encargados (Wompi, correo, nube, negocio vendedor) | Decreto 1377 art. 25 | La política los lista y explica para qué recibe datos cada uno. | `datos_personales/politica.py` (`ENCARGADOS`) |

**Pruebas automáticas:** `datos_personales/tests.py` tiene 30 pruebas: consentimiento obligatorio, prueba guardada, nueva aceptación al cambiar de versión, contenido de la política, descarga, plazos en días hábiles, aislamiento entre titulares, supresión que conserva las facturas, permisos de la consola y auditoría.

---

## 2. Configuración antes de salir a producción

En el `.env` del servidor:

```
DATOS_RESPONSABLE_RAZON_SOCIAL=...
DATOS_RESPONSABLE_NIT=...
DATOS_RESPONSABLE_DIRECCION=...
DATOS_RESPONSABLE_CORREO=...      # correo exclusivo para datos personales, p. ej. datos@dominio.co
DATOS_RESPONSABLE_TELEFONO=...
PROTECCION_DATOS_EXIGIR_AUTORIZACION=True
```

Mientras falte alguno, la política y la consola lo muestran **en rojo**. El software no inventa datos de la empresa.

Si cambia el texto de la política, hay que subir `VERSION_POLITICA` en `datos_personales/politica.py`. Así se vuelve a pedir la autorización a todos.

---

## 3. Lo que debe hacer la empresa (no lo hace el software)

| Tarea | Norma | Responsable |
|---|---|---|
| Revisar con un abogado la política, los avisos y los textos de autorización. | — | Gerencia |
| Inscribir las bases de datos en el **Registro Nacional de Bases de Datos (RNBD)** de la SIC, si la empresa está obligada (sociedades y entidades sin ánimo de lucro con activos totales superiores a 100.000 UVT, y personas jurídicas de naturaleza pública). Actualizarlo cuando haya cambios sustanciales y cada año. | Decreto 090 de 2018; Decreto 1074 de 2015 | Gerencia y oficial de datos |
| Designar a la persona o el área **responsable de la protección de datos** (oficial de protección de datos) y publicar su correo. | Decreto 1377 art. 23 | Gerencia |
| Elaborar el **manual interno de políticas y procedimientos** (cómo se atienden las solicitudes, quién aprueba una supresión, qué hacer ante un incidente). | Decreto 1377 art. 13 y 26 | Oficial de datos |
| Firmar **contratos de transmisión** con los encargados (Wompi, proveedor de correo, nube) y con cada negocio vendedor (InterSoft como encargado de los datos de sus clientes). | Decreto 1377 art. 25 | Gerencia y abogado |
| Revisar la **transferencia internacional** si el alojamiento o el correo están fuera de Colombia. | Ley 1581 art. 26; Circular Externa 005 de 2017 de la SIC | Abogado |
| Reportar a la SIC los **incidentes de seguridad** (fugas de datos) dentro de los 15 días hábiles siguientes a detectarlos. | Ley 1581 art. 17 n); RNBD | Oficial de datos |
| Capacitar al equipo que atiende soporte y PQRS. | Decreto 1377 art. 26 | Oficial de datos |
| Atender las solicitudes dentro del plazo. El software avisa, pero alguien debe responder. | Ley 1581 art. 14-15 | Equipo de soporte |
| Pedir a cada negocio que use la casilla de autorización de sus clientes del POS y que guarde el soporte. | Ley 1581 art. 9 | Cada negocio |
| Si algún día se envía publicidad: pedir una autorización aparte y ofrecer la opción de darse de baja. | Ley 1581 art. 9 | Mercadeo |

---

## 4. Límites conocidos

- La prórroga del plazo (5 días hábiles para consultas y 8 para reclamos) se comunica respondiendo al titular. No hay un botón de «prorrogar».
- La rectificación se hace a mano en el panel. La solicitud deja constancia y el plazo.
- La supresión no borra copias de seguridad ya tomadas. Esas copias se eliminan cuando vence su periodo de retención, como explica la política.
- Facturación electrónica DIAN: sigue pendiente de decisión y no se tocó.
