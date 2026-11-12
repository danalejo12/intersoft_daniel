(() => {
  const sinAnimacion = window.matchMedia("(prefers-reduced-motion: reduce)").matches;

  // 1. Efecto spotlight que sigue el cursor sobre tarjetas ERP, KPIs y Roles
  if (!sinAnimacion) {
    document.querySelectorAll(".erp-modulo-card, .kpi, .rol-card").forEach((el) => {
      el.addEventListener("pointermove", (ev) => {
        const rect = el.getBoundingClientRect();
        el.style.setProperty("--mx", `${ev.clientX - rect.left}px`);
        el.style.setProperty("--my", `${ev.clientY - rect.top}px`);
      });
    });
  }

  // 2. Efecto ripple al pulsar botones y enlaces con clase .boton
  if (!sinAnimacion) {
    document.addEventListener("click", (ev) => {
      const btn = ev.target.closest("button, .boton");
      if (
        !btn ||
        btn.classList.contains("dock-salir") ||
        btn.classList.contains("mensaje-cerrar") ||
        btn.classList.contains("erp-chip") ||
        btn.classList.contains("boton-hamburguesa") ||
        btn.disabled
      ) {
        return;
      }
      const rect = btn.getBoundingClientRect();
      const diametro = Math.max(rect.width, rect.height);
      const onda = document.createElement("span");
      onda.className = "ripple-efecto";
      onda.style.width = `${diametro}px`;
      onda.style.height = `${diametro}px`;
      onda.style.left = `${ev.clientX - rect.left - diametro / 2}px`;
      onda.style.top = `${ev.clientY - rect.top - diametro / 2}px`;
      btn.querySelectorAll(".ripple-efecto").forEach((n) => n.remove());
      btn.appendChild(onda);
      window.setTimeout(() => onda.remove(), 600);
    });
  }

  // 3. Feedback de carga al enviar formularios POST (evita doble envío)
  document.addEventListener("submit", (ev) => {
    const form = ev.target;
    if (!(form instanceof HTMLFormElement) || ev.defaultPrevented) return;
    if ((form.method || "get").toLowerCase() !== "post") return;
    const disparador = ev.submitter || form.querySelector('button[type="submit"]:not(.dock-salir)');
    if (!disparador || disparador.classList.contains("dock-salir")) return;
    if (disparador.classList.contains("cargando")) {
      ev.preventDefault();
      return;
    }
    disparador.classList.add("cargando");
  });

  // 4. Botón para cerrar mensajes flash informativos
  document.querySelectorAll(".mensaje").forEach((msg) => {
    if (msg.getAttribute("role") === "alert") return;
    const btn = document.createElement("button");
    btn.type = "button";
    btn.className = "mensaje-cerrar";
    btn.setAttribute("aria-label", "Cerrar aviso");
    btn.textContent = "×";
    btn.addEventListener("click", () => {
      msg.classList.add("saliendo");
      window.setTimeout(() => msg.remove(), 240);
    });
    msg.appendChild(btn);
  });

  // 5. Filtro instantáneo por categoría y búsqueda en Gestión ERP
  const erpGrid = document.getElementById("erp-grid");
  if (erpGrid) {
    const tarjetas = Array.from(erpGrid.querySelectorAll(".erp-modulo-card"));
    const chips = Array.from(document.querySelectorAll(".erp-chip"));
    const buscador = document.getElementById("erp-buscar-modulos");
    const estadoVacio = document.getElementById("erp-sin-resultados");
    let categoriaActiva = "todas";

    const aplicarFiltro = () => {
      const q = (buscador ? buscador.value : "").trim().toLowerCase();
      let visibles = 0;
      tarjetas.forEach((card) => {
        const cat = card.dataset.categoria || "";
        const texto = (card.dataset.texto || "").toLowerCase();
        const coincideCat = categoriaActiva === "todas" || cat === categoriaActiva;
        const coincideTxt = !q || texto.includes(q);
        const mostrar = coincideCat && coincideTxt;
        card.hidden = !mostrar;
        if (mostrar) visibles += 1;
      });
      if (estadoVacio) estadoVacio.hidden = visibles > 0;
    };

    chips.forEach((chip) => {
      chip.addEventListener("click", () => {
        chips.forEach((c) => {
          c.classList.remove("activo");
          c.setAttribute("aria-pressed", "false");
        });
        chip.classList.add("activo");
        chip.setAttribute("aria-pressed", "true");
        categoriaActiva = chip.dataset.categoria || "todas";
        aplicarFiltro();
      });
    });

    if (buscador) {
      buscador.addEventListener("input", aplicarFiltro);
    }
  }

  // 6. Menú hamburguesa en cuadros de Roles y Permisos (colapsa/expande sin saturar la vista)
  const alternarGaveta = (btn, forzarEstado) => {
    const idGaveta = btn.getAttribute("aria-controls");
    const gaveta = idGaveta ? document.getElementById(idGaveta) : null;
    if (!gaveta) return;
    const abrir = typeof forzarEstado === "boolean" ? forzarEstado : gaveta.hidden;
    gaveta.hidden = !abrir;
    btn.setAttribute("aria-expanded", abrir ? "true" : "false");
    const contenedor = btn.closest(".rol-card, .equipo-permiso-grupo");
    if (contenedor) {
      contenedor.classList.toggle("abierto", abrir);
    }
  };

  document.addEventListener("click", (ev) => {
    const btnHamb = ev.target.closest("[data-hamburguesa]");
    if (btnHamb) {
      ev.preventDefault();
      alternarGaveta(btnHamb);
      return;
    }

    const cabeceraGrupo = ev.target.closest(".equipo-grupo-cabecera");
    if (cabeceraGrupo && !ev.target.closest("button")) {
      const btn = cabeceraGrupo.querySelector("[data-hamburguesa]");
      if (btn) alternarGaveta(btn);
      return;
    }

    const btnTodos = ev.target.closest("[data-toggle-todos]");
    if (btnTodos) {
      const selector = btnTodos.dataset.toggleTodos;
      const botones = Array.from(document.querySelectorAll(selector));
      const algunoCerrado = botones.some((b) => b.getAttribute("aria-expanded") !== "true");
      botones.forEach((b) => alternarGaveta(b, algunoCerrado));
      btnTodos.textContent = algunoCerrado ? "Contraer todos" : "Expandir todos";
      return;
    }

    const btnMarcar = ev.target.closest("[data-marcar-modulo]");
    if (btnMarcar) {
      const grupo = btnMarcar.closest(".equipo-permiso-grupo");
      if (!grupo) return;
      const checks = Array.from(grupo.querySelectorAll('input[type="checkbox"][name="permisos"]'));
      const todosMarcados = checks.every((c) => c.checked);
      checks.forEach((c) => {
        c.checked = !todosMarcados;
      });
      actualizarContadorGrupo(grupo);
    }
  });

  // 7. Contador en vivo de permisos seleccionados por módulo en Crear/Editar Rol
  const actualizarContadorGrupo = (grupo) => {
    const checks = Array.from(grupo.querySelectorAll('input[type="checkbox"][name="permisos"]'));
    const marcados = checks.filter((c) => c.checked).length;
    const badge = grupo.querySelector("[data-contador-permisos]");
    if (badge) {
      badge.textContent = `${marcados} / ${checks.length}`;
      badge.className = `badge ${marcados > 0 ? "info" : "neutro"}`;
    }
  };

  document.querySelectorAll(".equipo-permiso-grupo").forEach((grupo) => {
    actualizarContadorGrupo(grupo);
    grupo.addEventListener("change", () => actualizarContadorGrupo(grupo));
  });
})();
