# Informe de pruebas de caja negra por técnica — InterSoft

| | |
|---|---|
| **Aplicativo** | InterSoft |
| **Fecha** | 26 de noviembre de 2026 |
| **Tipo de prueba** | Caja negra: funcional, a través de la interfaz web (HTTP), sin mirar el código |
| **Técnicas** | Partición de equivalencia (PE), valores límite (VL), flujo positivo (FP) y flujo negativo (FN) |
| **Casos de uso** | Registrar usuario, iniciar sesión y acceso, registrar empresa, registrar producto |
| **Pruebas automáticas** | `intersoft/core/tests_caja_negra.py`: 42 pruebas con **169 casos** |
| **Resultado final** | **169 de 169 casos cumplen.** Se hallaron y corrigieron 2 defectos nuevos. |

Para repetir las pruebas:
```bash
cd intersoft
python manage.py test core.tests_caja_negra
```

---

## 1. Resumen por técnica

| Caso de uso | PE | VL | FP | FN | Total |
|---|---:|---:|---:|---:|---:|
| Registrar usuario | 36 | 18 | 1 | 1 | 56 |
| Iniciar sesión y acceso | 5 | — | — | 6 | 11 |
| Registrar empresa | 27 | 14 | 1 | 1 | 43 |
| Registrar producto | 24 | 30 | 1 | 4 | 59 |
| **Total** | **92** | **62** | **3** | **12** | **169** |

---

## 2. Registrar usuario (`/registro/`)

### 2.1 Particiones de equivalencia
| Campo | Clases válidas | Clases inválidas | Resultado |
|---|---|---|---|
| Nombres y apellidos | «Ana María» (tildes y espacio), «José Ñañez» | vacío, solo espacios, con números («Ana1»), solo símbolo («@»), con guion, con guion bajo | Cumple |
| Correo | «ana.ruiz@correo.com.co» | vacío, sin @, dominio sin punto, con espacio, sin usuario, repetido, repetido en mayúsculas | Cumple |
| Contraseña | «Torta#Fresa-2026» | solo números, común en inglés («password»), común en español («contraseña», «Colombia2026»), un carácter repetido («@@@@@@@@»), secuencia («abcdefgh9»), parecida al correo, confirmación distinta | Cumple |
| Autorización de datos y mayoría de edad | marcadas | sin marcar | Cumple |

### 2.2 Valores límite
| Campo | Valores probados | Resultado |
|---|---|---|
| Nombres y apellidos (1 a 150) | 1 ✔, 2 ✔, 149 ✔, 150 ✔, 151 ✘ | Cumple |
| Correo: parte antes de la @ (máx. 64) | 64 ✔, 65 ✘ | **Defecto CN-02, corregido** |
| Correo: largo total (máx. 150) | 150 ✔, 151 ✘ | Cumple |
| Contraseña (mín. 8) | 7 ✘, 8 ✔, 9 ✔, 128 ✔ | Cumple |

### 2.3 Flujos
- **FP:** el registro completo crea la cuenta con sus nombres y deja la sesión iniciada. Cumple.
- **FN:** un registro inválido no crea ningún usuario. Cumple.

---

## 3. Iniciar sesión y acceso

- **PE:** datos correctos ✔; correo en mayúsculas ✔; contraseña errada ✘; correo no registrado ✘; campos vacíos ✘. Cumple.
- **FN:** sin sesión, el panel, los productos, «Mis pedidos» y «Mis datos» llevan al inicio de sesión. Cumple.
- **FN:** un enlace de inicio de sesión que intenta redirigir a otro sitio (`?next=https://sitio-malo.com/`) no lo sigue. Cumple.

---

## 4. Registrar empresa (`/negocio/registrar/`)

### 4.1 Particiones de equivalencia
| Campo | Clases válidas | Clases inválidas | Resultado |
|---|---|---|---|
| Nombre del negocio | «Pastelería Dulce & Café», «Tienda 24» | vacío, solo espacios, solo símbolos («=@») | Cumple |
| NIT | «900.123.456-7», «900123457» | vacío, «=», sin números, con «*», repetido, repetido escrito con puntos | Cumple |
| Correo (opcional) | vacío, «hola@pasteleria.co» | dominio sin punto | Cumple |
| Teléfono | «601 234 5678», «+57 300-123-4567» | vacío, con letras, «+» en medio | Cumple |
| Dirección | «Carrera 7 # 45-10» | vacía, un carácter, sin número («Bogotá»), sin letras («123456») | Cumple |

### 4.2 Valores límite
| Campo | Valores probados | Resultado |
|---|---|---|
| Nombre (1 a 150) | 1 ✔, 150 ✔, 151 ✘ | Cumple |
| NIT (1 a 20) | 1 ✔, 20 ✔, 21 ✘ | Cumple |
| Teléfono (7 a 20) | 6 ✘, 7 ✔, 20 ✔, 21 ✘ | Cumple |
| Dirección (6 a 200) | 5 ✘, 6 ✔, 200 ✔, 201 ✘ | Cumple |

### 4.3 Flujos
- **FP:** quien registra el negocio queda como administrador y entra a su panel. Cumple.
- **FN:** sin sesión no se crea el negocio; lo lleva a crear su cuenta y luego vuelve. Cumple.

---

## 5. Registrar producto (`/panel/productos/nuevo/`)

### 5.1 Particiones de equivalencia
| Campo | Clases válidas | Clases inválidas | Resultado |
|---|---|---|---|
| Código | «LAP-PRO-14», «A.1/2_b», mismo código en otro negocio | vacío, «=», «*», empieza con símbolo, repetido en el mismo negocio (aun en minúsculas) | Cumple |
| Nombre | «Torta de fresa x 10» | vacío, «=», «*» | Cumple |
| Precio | número válido | 3 decimales, texto, vacío | Cumple |
| IVA | 19 | texto | Cumple |
| Stock inicial, stock mínimo, peso | enteros | con decimales («2.5») | Cumple |
| Imagen | PNG real | texto disfrazado de .png, PDF | Cumple |

### 5.2 Valores límite
| Campo | Valores probados | Resultado |
|---|---|---|
| Código (1 a 30) | 1 ✔, 30 ✔, 31 ✘ | Cumple |
| Nombre (1 a 150) | 1 ✔, 150 ✔, 151 ✘ | Cumple |
| Descripción (0 a 5.000) | 0 ✔, 4.999 ✔, 5.000 ✔, 5.001 ✘ | Cumple |
| Precio (0 a 9.999.999.999,99) | −0,01 ✘, 0 ✔, 0,01 ✔, máximo ✔, máximo + 1 ✘ | Cumple |
| IVA (0 a 100) | −0,01 ✘, 0 ✔, 100 ✔, 100,01 ✘ | Cumple |
| Stock inicial (≥ 0) | −1 ✘, 0 ✔, 1 ✔ | Cumple |
| Stock mínimo (≥ 0) | −1 ✘, 0 ✔, 1 ✔ | **Defecto CN-01, corregido** |
| Peso en gramos (≥ 0) | −1 ✘, 0 ✔, 1 ✔ | Cumple |
| Imagen (máx. 5 MB) | exactamente 5 MB ✔, 5 MB + 1 byte ✘ | Cumple |

### 5.3 Flujos
- **FP:** un producto publicado con stock aparece en el marketplace con su precio. Cumple.
- **FN:** un producto no publicado no aparece en el marketplace. Cumple.
- **FN:** otro negocio no puede editar mis productos; recibe «no encontrado» y nada cambia. Cumple.
- **FN:** un comprador sin negocio no puede crear productos. Cumple.
- **FN:** una descripción de 1.000.000 de caracteres se rechaza con un mensaje, sin bloquear el sistema (era el CP-15 del informe anterior). Cumple.

---

## 6. Defectos encontrados

| ID | Técnica | Campo | Qué pasaba | Corrección | Estado |
|---|---|---|---|---|---|
| CN-01 | VL | Stock mínimo | Aceptaba −1 (stock mínimo negativo). | Validación «mínimo 0» en el modelo del producto. | Corregido |
| CN-02 | VL | Correo (usuario y empresa) | Aceptaba 65 o más caracteres antes de la @. El validador de Django no revisa ese límite. | Validación de máximo 64 caracteres antes de la @ (RFC 5321). | Corregido |

En los datos de prueba se ajustaron 3 casos que estaban mal planteados (no eran defectos del sistema):
- el dominio de correo de 150 caracteres tenía un tramo de más de 63, lo que prohíbe el estándar;
- una dirección de prueba no tenía número;
- el registro de empresa sin sesión redirige a «Crear cuenta», que también es correcto.

---

## 7. Conclusión

Los 169 casos de las cuatro técnicas cumplen.

- **Particiones de equivalencia:** el sistema distingue bien los datos válidos de los inválidos en todos los campos de texto, número, correo, teléfono e imagen.
- **Valores límite:** encontraron 2 defectos que no había detectado el informe anterior. Ambos quedaron corregidos.
- **Flujos positivos:** los caminos felices funcionan de principio a fin.
- **Flujos negativos:** el sistema impide el acceso sin sesión, la edición entre negocios, las redirecciones externas y la saturación por texto gigante.

La suite completa del proyecto queda en **706 pruebas, todas en verde**.
