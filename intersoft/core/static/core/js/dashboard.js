(function () {
  var elMeses = document.getElementById("datos-meses");
  var elDias = document.getElementById("datos-dias");
  var lienzo = document.getElementById("grafica-ventas");
  if (!elMeses || !elDias || !lienzo || typeof Chart === "undefined") return;

  var meses = JSON.parse(elMeses.textContent);
  var dias = JSON.parse(elDias.textContent);
  var sinAnimacion = window.matchMedia("(prefers-reduced-motion: reduce)").matches;

  var leerColores = function () {
    var estilos = getComputedStyle(document.documentElement);
    var esOscuro = document.documentElement.getAttribute("data-tema") === "oscuro";
    var texto = (estilos.getPropertyValue("--is-ink-muted") || "").trim() || (esOscuro ? "#94a3b8" : "#64748b");
    var rejilla = (estilos.getPropertyValue("--is-border") || "").trim() || (esOscuro ? "#1f2937" : "#e2e8f0");
    var verde = (estilos.getPropertyValue("--is-success") || "").trim() || (esOscuro ? "#34d399" : "#059669");
    var azul = (estilos.getPropertyValue("--is-brand") || "").trim() || (esOscuro ? "#3b82f6" : "#2563eb");
    return {
      texto: texto,
      rejilla: rejilla,
      verde: verde,
      azul: azul,
      rellenoInicio: esOscuro ? "rgba(52, 211, 153, 0.28)" : "rgba(5, 150, 105, 0.20)",
      rellenoFin: esOscuro ? "rgba(52, 211, 153, 0)" : "rgba(5, 150, 105, 0)",
    };
  };

  // Formato corto de dinero: 1.250.000 -> $1,3M · 45.000 -> $45K
  var corto = function (v) {
    return v >= 1e6 ? "$" + (v / 1e6).toFixed(1) + "M" : v >= 1e3 ? "$" + Math.round(v / 1e3) + "K" : "$" + v;
  };

  var c = leerColores();
  var ctx = lienzo.getContext("2d");
  var crearRelleno = function (col) {
    var grad = ctx.createLinearGradient(0, 0, 0, 280);
    grad.addColorStop(0, col.rellenoInicio);
    grad.addColorStop(1, col.rellenoFin);
    return grad;
  };

  var graficaVentas = new Chart(lienzo, {
    type: "line",
    data: {
      labels: meses.etiquetas,
      datasets: [{
        data: meses.valores,
        borderColor: c.verde,
        borderWidth: 2.5,
        backgroundColor: crearRelleno(c),
        fill: true,
        tension: 0.4,
        pointRadius: 3,
        pointBackgroundColor: c.verde,
        pointHoverRadius: 6,
        pointHoverBackgroundColor: c.verde,
      }],
    },
    options: {
      animation: sinAnimacion ? false : { duration: 900 },
      maintainAspectRatio: false,
      plugins: {
        legend: { display: false },
        tooltip: { callbacks: { label: function (item) { return " $ " + item.parsed.y.toLocaleString("es-CO"); } } },
      },
      scales: {
        x: { grid: { display: false }, ticks: { color: c.texto }, border: { display: false } },
        y: {
          beginAtZero: true,
          grid: { color: c.rejilla },
          ticks: { color: c.texto, callback: corto, maxTicksLimit: 5 },
          border: { display: false },
        },
      },
    },
  });

  // Sparkline de la tarjeta de ventas (últimos 7 días)
  var sparkline = document.getElementById("sparkline-ventas");
  var graficaSpark = null;
  if (sparkline) {
    graficaSpark = new Chart(sparkline, {
      type: "line",
      data: {
        labels: dias.etiquetas,
        datasets: [{ data: dias.valores, borderColor: c.azul, borderWidth: 2.5, tension: 0.4, pointRadius: 0, fill: false }],
      },
      options: {
        animation: sinAnimacion ? false : { duration: 700 },
        maintainAspectRatio: false,
        plugins: { legend: { display: false }, tooltip: { enabled: false } },
        scales: { x: { display: false }, y: { display: false, beginAtZero: true } },
      },
    });
  }

  // Re-pintar ejes y colores al cambiar entre modo Claro y Oscuro
  if (typeof MutationObserver !== "undefined") {
    new MutationObserver(function () {
      var n = leerColores();
      graficaVentas.data.datasets[0].borderColor = n.verde;
      graficaVentas.data.datasets[0].pointBackgroundColor = n.verde;
      graficaVentas.data.datasets[0].pointHoverBackgroundColor = n.verde;
      graficaVentas.data.datasets[0].backgroundColor = crearRelleno(n);
      graficaVentas.options.scales.x.ticks.color = n.texto;
      graficaVentas.options.scales.y.ticks.color = n.texto;
      graficaVentas.options.scales.y.grid.color = n.rejilla;
      graficaVentas.update("none");
      if (graficaSpark) {
        graficaSpark.data.datasets[0].borderColor = n.azul;
        graficaSpark.update("none");
      }
    }).observe(document.documentElement, { attributes: true, attributeFilter: ["data-tema"] });
  }
})();
