"""Calidad del código (ISO/IEC 25010 · Mantenibilidad · Analizabilidad): documentación obligatoria.

Todo módulo, toda clase y toda función con lógica propia debe tener docstring (PEP 257). Se exceptúan los
métodos estándar de Django cuyo nombre ya explica lo que hacen (get, post, get_queryset, form_valid, __str__…)
y las funciones de una sola sentencia sin ramas. Si esta prueba falla, documenta lo que indica el mensaje.
"""
import ast
from pathlib import Path

from django.conf import settings
from django.test import SimpleTestCase

APPS = ("core", "plataforma", "pqrs", "soporte", "suscripciones", "intersoft")
# Facturación electrónica DIAN: en espera de decisión del equipo antes del despliegue (no se modifica).
EXCLUIDOS = {Path("core/facturacion_electronica.py")}
GANCHOS_DJANGO = {
    "get", "post", "put", "patch", "delete", "dispatch", "get_queryset", "get_context_data", "form_valid",
    "form_invalid", "get_object", "get_success_url", "get_initial", "get_form_kwargs", "get_form", "save",
    "clean", "__str__", "__init__", "__call__", "has_add_permission", "has_change_permission",
    "has_delete_permission", "ready", "handle", "add_arguments", "get_readonly_fields",
}


def _es_trivial(nodo):
    cuerpo = [n for n in nodo.body if not (isinstance(n, ast.Expr) and isinstance(n.value, ast.Constant))]
    ramas = (ast.If, ast.For, ast.While, ast.Try, ast.With)
    return len(cuerpo) <= 1 and not any(isinstance(n, ramas) for n in cuerpo)


def huecos_de_documentacion():
    raiz = Path(settings.BASE_DIR)
    huecos = []
    for app in APPS:
        for ruta in sorted((raiz / app).rglob("*.py")):
            rel = ruta.relative_to(raiz)
            if ("migrations" in rel.parts or ruta.name.startswith("tests") or ruta.name.startswith("testing_")
                    or rel in EXCLUIDOS):
                continue
            texto = ruta.read_text(encoding="utf-8")
            if not texto.strip():
                continue
            arbol = ast.parse(texto)
            if not ast.get_docstring(arbol):
                huecos.append(f"{rel}: módulo sin docstring")
            for padre in ast.walk(arbol):
                for nodo in ast.iter_child_nodes(padre):
                    if isinstance(nodo, ast.ClassDef):
                        if nodo.name != "Meta" and not ast.get_docstring(nodo):
                            huecos.append(f"{rel}:{nodo.lineno} clase {nodo.name}")
                    elif isinstance(nodo, (ast.FunctionDef, ast.AsyncFunctionDef)):
                        if (ast.get_docstring(nodo) or nodo.name in GANCHOS_DJANGO
                                or nodo.name.startswith("clean_") or _es_trivial(nodo)):
                            continue
                        huecos.append(f"{rel}:{nodo.lineno} función {nodo.name}")
    return huecos


class DocumentacionTests(SimpleTestCase):
    def test_todo_el_codigo_esta_documentado(self):
        huecos = huecos_de_documentacion()
        self.assertEqual(huecos, [], "Falta documentación (PEP 257):\n" + "\n".join(huecos))
