(function () {
  try {
    if (localStorage.getItem("intersoft-dock") !== "cerrado") {
      document.documentElement.classList.add("dock-abierto");
    }
  } catch (e) {
    document.documentElement.classList.add("dock-abierto");
  }
})();
