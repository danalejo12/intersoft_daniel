(function () {
  var tema;
  try {
    tema = localStorage.getItem("intersoft-tema");
  } catch (e) {}
  if (tema !== "claro" && tema !== "oscuro") {
    tema = window.matchMedia("(prefers-color-scheme: dark)").matches ? "oscuro" : "claro";
  }
  document.documentElement.setAttribute("data-tema", tema);
})();
