(function () {
  try {
    var temaGlobal = localStorage.getItem("intersoft-tema");
    if (temaGlobal === "oscuro") {
      document.documentElement.dataset.tema = "dark";
    } else if (temaGlobal === "claro") {
      document.documentElement.dataset.tema = "light";
    }
  } catch (e) {}
})();
