/* Punto de venta. El navegador solo arma la venta; el servidor recalcula precios, IVA y total. */
(function () {
  "use strict";

  var raiz = document.querySelector("[data-pos]");
  if (!raiz) {
    return;
  }
  var csrf = raiz.querySelector("input[name=csrfmiddlewaretoken]").value;
  var catalogo = {};   // id -> datos del producto
  var venta = [];      // [{id, cantidad}]
  var cliente = null;  // {id, nombre} o null para consumidor final
  var operacionActual = null; // UUID único por intento de venta para evitar duplicados ante reintentos
  var MONTOS_RAPIDOS = [1000000, 2000000, 5000000, 10000000];  // en centavos: 10.000, 20.000, 50.000, 100.000

  function nuevaOperacion() {
    if (window.crypto && typeof window.crypto.randomUUID === "function") {
      return window.crypto.randomUUID();
    }
    return "xxxxxxxx-xxxx-4xxx-yxxx-xxxxxxxxxxxx".replace(/[xy]/g, function (c) {
      var r = (Math.random() * 16) | 0;
      var v = c === "x" ? r : (r & 0x3) | 0x8;
      return v.toString(16);
    });
  }

  JSON.parse(document.getElementById("pos-frecuentes").textContent).forEach(function (p) {
    catalogo[p.id] = p;
  });

  function $(id) { return document.getElementById(id); }

  // ---------- Dinero en centavos enteros: sin errores de redondeo ----------
  function centavos(precio) { return Math.round(parseFloat(precio) * 100); }

  function ivaCentavos(base, porcentaje) {
    // Mitad hacia arriba, igual que core/impuestos.calcular_iva
    var puntos = Math.round(parseFloat(porcentaje) * 100);
    return Math.floor((2 * base * puntos + 10000) / 20000);
  }

  function pesos(valor) {
    var entero = Math.floor(Math.abs(valor) / 100);
    var decimales = Math.abs(valor) % 100;
    var texto = String(entero).replace(/\B(?=(\d{3})+(?!\d))/g, ".");
    return (valor < 0 ? "-$" : "$") + texto + (decimales ? "," + String(decimales).padStart(2, "0") : "");
  }

  function leerMonto(texto) {
    // Acepta 50000, 50.000, 50.000,50 y 50000.50
    texto = (texto || "").trim().replace(/[\s$]/g, "");
    if (!texto) {
      return 0;
    }
    if (texto.indexOf(",") >= 0) {
      texto = texto.replace(/\./g, "").replace(",", ".");
    } else if (/^\d{1,3}(\.\d{3})+$/.test(texto)) {
      texto = texto.replace(/\./g, "");
    }
    if (!/^\d+(\.\d{1,2})?$/.test(texto)) {
      return NaN;
    }
    var partes = texto.split(".");
    return parseInt(partes[0], 10) * 100 + (partes[1] ? parseInt((partes[1] + "0").slice(0, 2), 10) : 0);
  }

  function paraServidor(valor) {
    return Math.floor(valor / 100) + "." + String(valor % 100).padStart(2, "0");
  }

  // ---------- Avisos ----------
  var temporizadorAviso = null;
  function avisar(texto, error) {
    var aviso = $("pos-aviso");
    aviso.textContent = texto;
    aviso.classList.toggle("pos-aviso-error", Boolean(error));
    window.clearTimeout(temporizadorAviso);
    temporizadorAviso = window.setTimeout(function () { aviso.textContent = ""; }, 3500);
  }

  // ---------- La venta ----------
  function agregar(producto, cantidad) {
    cantidad = cantidad || 1;
    catalogo[producto.id] = producto;
    var linea = venta.find(function (l) { return l.id === producto.id; });
    var actual = linea ? linea.cantidad : 0;
    if (actual + cantidad > producto.stock) {
      avisar(producto.stock > 0 ? "Solo hay " + producto.stock + " de " + producto.nombre + "." : producto.nombre + " está agotado.", true);
      return;
    }
    if (linea) {
      linea.cantidad += cantidad;
    } else {
      venta.push({ id: producto.id, cantidad: cantidad });
    }
    operacionActual = null;
    avisar("Agregado: " + producto.nombre);
    pintar();
  }

  function cambiarCantidad(id, cantidad) {
    var linea = venta.find(function (l) { return l.id === id; });
    if (!linea) {
      return;
    }
    if (!cantidad || cantidad < 1) {
      venta = venta.filter(function (l) { return l.id !== id; });
    } else if (cantidad > catalogo[id].stock) {
      avisar("Solo hay " + catalogo[id].stock + " de " + catalogo[id].nombre + ".", true);
      linea.cantidad = catalogo[id].stock;
    } else {
      linea.cantidad = cantidad;
    }
    operacionActual = null;
    pintar();
  }

  function totales() {
    var subtotal = 0;
    var iva = 0;
    venta.forEach(function (l) {
      var p = catalogo[l.id];
      var base = centavos(p.precio) * l.cantidad;
      subtotal += base;
      iva += ivaCentavos(base, p.iva);
    });
    return { subtotal: subtotal, iva: iva, total: subtotal + iva };
  }

  function pintar() {
    var lista = $("pos-lineas");
    lista.innerHTML = "";
    venta.forEach(function (l) {
      var p = catalogo[l.id];
      var base = centavos(p.precio) * l.cantidad;
      var li = document.createElement("li");
      li.className = "pos-linea";

      var nombre = document.createElement("span");
      nombre.className = "pos-linea-nombre";
      nombre.textContent = p.nombre;  // textContent: el nombre nunca se interpreta como HTML

      var controles = document.createElement("span");
      controles.className = "pos-cantidad";
      var menos = document.createElement("button");
      menos.type = "button";
      menos.textContent = "−";
      menos.setAttribute("aria-label", "Una unidad menos de " + p.nombre);
      menos.addEventListener("click", function () { cambiarCantidad(l.id, l.cantidad - 1); });
      var campo = document.createElement("input");
      campo.type = "number";
      campo.min = "1";
      campo.value = l.cantidad;
      campo.setAttribute("aria-label", "Cantidad de " + p.nombre);
      campo.addEventListener("change", function () { cambiarCantidad(l.id, parseInt(campo.value, 10)); });
      var mas = document.createElement("button");
      mas.type = "button";
      mas.textContent = "+";
      mas.setAttribute("aria-label", "Una unidad más de " + p.nombre);
      mas.addEventListener("click", function () { cambiarCantidad(l.id, l.cantidad + 1); });
      controles.append(menos, campo, mas);

      var total = document.createElement("strong");
      total.className = "pos-linea-total";
      total.textContent = pesos(base + ivaCentavos(base, p.iva));

      var quitar = document.createElement("button");
      quitar.type = "button";
      quitar.className = "pos-quitar";
      quitar.textContent = "×";
      quitar.setAttribute("aria-label", "Quitar " + p.nombre);
      quitar.addEventListener("click", function () { cambiarCantidad(l.id, 0); });

      li.append(nombre, controles, total, quitar);
      lista.appendChild(li);
    });

    var t = totales();
    $("pos-subtotal").textContent = pesos(t.subtotal);
    $("pos-iva").textContent = pesos(t.iva);
    $("pos-total").textContent = pesos(t.total);
    $("pos-vacio").hidden = venta.length > 0;
    $("pos-cobrar").disabled = venta.length === 0;
  }

  // ---------- Buscador de productos (también recibe el lector de código de barras) ----------
  var buscador = $("pos-buscar");
  var resultados = $("pos-resultados");
  var encontrados = [];
  var activo = -1;
  var esperaBusqueda = null;

  function buscar(texto) {
    return fetch(raiz.dataset.urlProductos + "?q=" + encodeURIComponent(texto), { credentials: "same-origin" })
      .then(function (r) { return r.json(); });
  }

  function mostrarResultados(lista) {
    encontrados = lista;
    activo = lista.length ? 0 : -1;
    resultados.innerHTML = "";
    lista.forEach(function (p, i) {
      var li = document.createElement("li");
      li.setAttribute("role", "option");
      li.className = "pos-resultado" + (i === 0 ? " activo" : "");
      var nombre = document.createElement("span");
      nombre.textContent = p.nombre + " · " + p.codigo;
      var detalle = document.createElement("small");
      detalle.textContent = pesos(centavos(p.precio) + ivaCentavos(centavos(p.precio), p.iva)) + " · " + (p.stock > 0 ? p.stock + " en stock" : "agotado");
      li.append(nombre, detalle);
      li.addEventListener("mousedown", function (e) { e.preventDefault(); elegir(i); });
      resultados.appendChild(li);
    });
    resultados.hidden = lista.length === 0;
  }

  function elegir(i) {
    if (encontrados[i]) {
      agregar(encontrados[i]);
    }
    buscador.value = "";
    resultados.hidden = true;
    buscador.focus();
  }

  buscador.addEventListener("input", function () {
    window.clearTimeout(esperaBusqueda);
    var texto = buscador.value.trim();
    if (!texto) {
      resultados.hidden = true;
      return;
    }
    esperaBusqueda = window.setTimeout(function () {
      buscar(texto).then(function (datos) {
        if (buscador.value.trim() === texto) {
          mostrarResultados(datos.productos);
        }
      });
    }, 200);
  });

  buscador.addEventListener("keydown", function (e) {
    if (e.key === "ArrowDown" || e.key === "ArrowUp") {
      if (!encontrados.length) {
        return;
      }
      e.preventDefault();
      activo = (activo + (e.key === "ArrowDown" ? 1 : -1) + encontrados.length) % encontrados.length;
      Array.prototype.forEach.call(resultados.children, function (li, i) { li.classList.toggle("activo", i === activo); });
    } else if (e.key === "Escape") {
      resultados.hidden = true;
    } else if (e.key === "Enter") {
      e.preventDefault();
      window.clearTimeout(esperaBusqueda);
      var texto = buscador.value.trim();
      if (!texto) {
        return;
      }
      if (!resultados.hidden && activo >= 0) {
        elegir(activo);
        return;
      }
      // El lector escribe el código y pulsa Enter: se busca de inmediato el código exacto
      buscar(texto).then(function (datos) {
        if (datos.exacto) {
          agregar(datos.exacto);
          buscador.value = "";
          resultados.hidden = true;
        } else if (datos.productos.length === 1) {
          encontrados = datos.productos;
          elegir(0);
        } else if (datos.productos.length) {
          mostrarResultados(datos.productos);
        } else {
          avisar("No encontramos «" + texto + "».", true);
        }
      });
    }
  });

  buscador.addEventListener("blur", function () {
    window.setTimeout(function () { resultados.hidden = true; }, 150);
  });

  document.querySelectorAll("[data-agregar]").forEach(function (boton) {
    boton.addEventListener("click", function () {
      agregar(catalogo[boton.dataset.agregar]);
      buscador.focus();
    });
  });

  // ---------- Cliente ----------
  var buscadorCliente = $("pos-cliente-buscar");
  var listaClientes = $("pos-clientes");
  var esperaCliente = null;

  function elegirCliente(c) {
    cliente = c;
    operacionActual = null;
    $("pos-cliente-nombre").textContent = c ? c.nombre + " · " + c.documento : "Consumidor final";
    $("pos-cliente-quitar").hidden = !c;
    buscadorCliente.value = "";
    listaClientes.hidden = true;
  }

  buscadorCliente.addEventListener("input", function () {
    window.clearTimeout(esperaCliente);
    var texto = buscadorCliente.value.trim();
    if (!texto) {
      listaClientes.hidden = true;
      return;
    }
    esperaCliente = window.setTimeout(function () {
      fetch(raiz.dataset.urlClientes + "?q=" + encodeURIComponent(texto), { credentials: "same-origin" })
        .then(function (r) { return r.json(); })
        .then(function (datos) {
          listaClientes.innerHTML = "";
          datos.clientes.forEach(function (c) {
            var li = document.createElement("li");
            li.className = "pos-resultado";
            li.setAttribute("role", "option");
            li.textContent = c.nombre + " · " + c.documento;
            li.addEventListener("mousedown", function (e) { e.preventDefault(); elegirCliente(c); });
            listaClientes.appendChild(li);
          });
          if (!datos.clientes.length) {
            var vacio = document.createElement("li");
            vacio.className = "pos-resultado";
            vacio.textContent = "Sin resultados. Créalo en Clientes.";
            listaClientes.appendChild(vacio);
          }
          listaClientes.hidden = false;
        });
    }, 250);
  });
  buscadorCliente.addEventListener("blur", function () {
    window.setTimeout(function () { listaClientes.hidden = true; }, 150);
  });
  $("pos-cliente-quitar").addEventListener("click", function () { elegirCliente(null); });

  $("pos-vaciar").addEventListener("click", function () {
    if (venta.length && window.confirm("¿Vaciar la venta actual?")) {
      venta = [];
      elegirCliente(null);
      pintar();
      buscador.focus();
    }
  });

  // ---------- Cobro ----------
  var dialogoCobro = $("pos-cobro");
  var campos = {
    efectivo: $("pos-efectivo"),
    tarjeta: $("pos-tarjeta"),
    transferencia: $("pos-transferencia"),
  };

  function estadoCobro() {
    var total = totales().total;
    var tarjeta = leerMonto(campos.tarjeta.value);
    var transferencia = leerMonto(campos.transferencia.value);
    var efectivo = leerMonto(campos.efectivo.value);
    var resultado = { total: total, tarjeta: tarjeta, transferencia: transferencia, efectivo: efectivo, valido: false, texto: "" };
    if (isNaN(tarjeta) || isNaN(transferencia) || isNaN(efectivo)) {
      resultado.texto = "Revisa los montos: escribe solo números.";
      return resultado;
    }
    var otros = tarjeta + transferencia;
    if (otros > total) {
      resultado.texto = "Tarjeta y transferencia superan el total. El cambio solo se da en efectivo.";
      return resultado;
    }
    resultado.falta = total - otros;
    if (resultado.falta === 0) {
      resultado.valido = efectivo === 0;
      resultado.texto = efectivo ? "El total ya está cubierto: deja el efectivo en 0." : "Pago completo.";
      return resultado;
    }
    if (efectivo < resultado.falta) {
      resultado.texto = "Falta " + pesos(resultado.falta - efectivo) + " por recibir.";
      return resultado;
    }
    resultado.valido = true;
    resultado.texto = "Cambio: " + pesos(efectivo - resultado.falta);
    return resultado;
  }

  function actualizarCobro() {
    var estado = estadoCobro();
    var texto = $("pos-estado-pago");
    texto.textContent = estado.texto;
    texto.classList.toggle("pos-estado-ok", estado.valido);
    $("pos-confirmar").disabled = !estado.valido;
  }

  function pintarRapidos() {
    var contenedor = $("pos-rapidos");
    contenedor.innerHTML = "";
    var falta = totales().total - (leerMonto(campos.tarjeta.value) || 0) - (leerMonto(campos.transferencia.value) || 0);
    var exacto = document.createElement("button");
    exacto.type = "button";
    exacto.className = "boton secundario";
    exacto.textContent = "Exacto";
    exacto.addEventListener("click", function () {
      campos.efectivo.value = falta > 0 ? pesos(falta).replace("$", "") : "";
      actualizarCobro();
    });
    contenedor.appendChild(exacto);
    MONTOS_RAPIDOS.forEach(function (valor) {
      var boton = document.createElement("button");
      boton.type = "button";
      boton.className = "boton secundario";
      boton.textContent = pesos(valor);
      boton.addEventListener("click", function () {
        campos.efectivo.value = pesos(valor).replace("$", "");
        actualizarCobro();
      });
      contenedor.appendChild(boton);
    });
  }

  function abrirCobro() {
    if (!venta.length) {
      return;
    }
    if (!operacionActual) {
      operacionActual = nuevaOperacion();
    }
    $("pos-cobro-total").textContent = pesos(totales().total);
    Object.keys(campos).forEach(function (k) { campos[k].value = ""; });
    $("pos-tarjeta-ref").value = "";
    $("pos-transferencia-ref").value = "";
    $("pos-error-cobro").hidden = true;
    pintarRapidos();
    actualizarCobro();
    dialogoCobro.showModal();
    campos.efectivo.focus();
  }

  Object.keys(campos).forEach(function (k) {
    campos[k].addEventListener("input", function () {
      if (k !== "efectivo") {
        pintarRapidos();
      }
      actualizarCobro();
    });
  });

  $("pos-cobrar").addEventListener("click", abrirCobro);
  $("pos-volver").addEventListener("click", function () { dialogoCobro.close(); });
  document.addEventListener("keydown", function (e) {
    if (e.key === "F2" && !dialogoCobro.open) {
      e.preventDefault();
      abrirCobro();
    }
  });

  $("pos-form-cobro").addEventListener("submit", function (e) {
    e.preventDefault();
    var estado = estadoCobro();
    if (!estado.valido) {
      return;
    }
    var pagos = [];
    if (estado.tarjeta) {
      pagos.push({ metodo: "tarjeta", monto: paraServidor(estado.tarjeta), referencia: $("pos-tarjeta-ref").value });
    }
    if (estado.transferencia) {
      pagos.push({ metodo: "transferencia", monto: paraServidor(estado.transferencia), referencia: $("pos-transferencia-ref").value });
    }
    if (estado.falta > 0) {
      pagos.push({ metodo: "efectivo", recibido: paraServidor(estado.efectivo) });
    }
    if (!operacionActual) {
      operacionActual = nuevaOperacion();
    }
    var boton = $("pos-confirmar");
    boton.disabled = true;
    boton.textContent = "Registrando…";

    fetch(raiz.dataset.urlVender, {
      method: "POST",
      credentials: "same-origin",
      headers: { "Content-Type": "application/json", "X-CSRFToken": csrf },
      body: JSON.stringify({
        operacion: operacionActual,
        lineas: venta.map(function (l) { return { producto: l.id, cantidad: l.cantidad }; }),
        cliente: cliente && cliente.id,
        pagos: pagos,
      }),
    }).then(function (r) {
      return r.json();
    }).then(function (datos) {
      if (!datos.ok) {
        operacionActual = nuevaOperacion();
        var error = $("pos-error-cobro");
        error.textContent = datos.error;
        error.hidden = false;
        return;
      }
      operacionActual = null;
      dialogoCobro.close();
      $("pos-listo-numero").textContent = datos.numero;
      $("pos-listo-cambio").textContent = pesos(centavos(datos.cambio));
      $("pos-imprimir").href = datos.ticket + "?imprimir=1";
      $("pos-listo").showModal();
      $("pos-nueva").focus();
    }).catch(function () {
      var error = $("pos-error-cobro");
      error.textContent = "No pudimos comunicarnos con el servidor. Revisa la conexión e inténtalo de nuevo.";
      error.hidden = false;
    }).finally(function () {
      boton.disabled = false;
      boton.textContent = "Confirmar venta";
    });
  });

  // Una venta nueva recarga la página: así el stock y los más vendidos quedan al día
  $("pos-nueva").addEventListener("click", function () { window.location.reload(); });
  $("pos-listo").addEventListener("cancel", function () { window.location.reload(); });

  pintar();
})();
