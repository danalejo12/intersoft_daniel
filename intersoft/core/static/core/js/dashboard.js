(function () {
  var elMeses = document.getElementById("datos-meses");
  var elDias = document.getElementById("datos-dias");
  var lienzo = document.getElementById("grafica-ventas");
  if (!elMeses || !elDias || !lienzo || typeof Chart === "undefined") return;

  var meses = JSON.parse(elMeses.textContent);
  var dias = JSON.parse(elDias.textContent);
  var sinAnimacion = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
  var verde = "#7bd66b";

  // Formato corto de dinero: 1.250.000 -> $1,3M · 45.000 -> $45K
  var corto = function (v) {
    return v >= 1e6 ? "$" + (v / 1e6).toFixed(1) + "M" : v >= 1e3 ? "$" + Math.round(v / 1e3) + "K" : "$" + v;
  };

  // Gráfica principal: línea suave con relleno degradado
  var ctx = lienzo.getContext("2d");
  var relleno = ctx.createLinearGradient(0, 0, 0, 300);
  relleno.addColorStop(0, "rgba(123, 214, 107, 0.35)");
  relleno.addColorStop(1, "rgba(123, 214, 107, 0)");

  new Chart(lienzo, {
    type: "line",
    data: {
      labels: meses.etiquetas,
      datasets: [{
        data: meses.valores,
        borderColor: verde,
        borderWidth: 3,
        backgroundColor: relleno,
        fill: true,
        tension: 0.45,
        pointRadius: 0,
        pointHoverRadius: 6,
        pointHoverBackgroundColor: verde,
      }],
    },
    options: {
      animation: sinAnimacion ? false : { duration: 1200 },
      maintainAspectRatio: false,
      plugins: {
        legend: { display: false },
        tooltip: { callbacks: { label: function (c) { return " $ " + c.parsed.y.toLocaleString("es-CO"); } } },
      },
      scales: {
        x: { grid: { display: false }, ticks: { color: "rgba(244,242,238,.45)" }, border: { display: false } },
        y: {
          beginAtZero: true,
          grid: { color: "rgba(255,255,255,.07)" },
          ticks: { color: "rgba(244,242,238,.45)", callback: corto, maxTicksLimit: 5 },
          border: { display: false },
        },
      },
    },
  });

  // Sparkline de la tarjeta de ventas (últimos 7 días)
  var sparkline = document.getElementById("sparkline-ventas");
  if (sparkline) {
    new Chart(sparkline, {
      type: "line",
      data: {
        labels: dias.etiquetas,
        datasets: [{ data: dias.valores, borderColor: "#5b8cff", borderWidth: 2.5, tension: 0.45, pointRadius: 0, fill: false }],
      },
      options: {
        animation: sinAnimacion ? false : { duration: 900 },
        maintainAspectRatio: false,
        plugins: { legend: { display: false }, tooltip: { enabled: false } },
        scales: { x: { display: false }, y: { display: false, beginAtZero: true } },
      },
    });
  }
})();
