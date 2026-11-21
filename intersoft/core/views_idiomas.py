"""Sección Idiomas: permite elegir el idioma de toda la interfaz (español o inglés)."""
from django.conf import settings
from django.utils.http import url_has_allowed_host_and_scheme
from django.utils.translation import get_language, get_language_info
from django.views.generic import TemplateView

# Bandera y región de cada idioma ofrecido en LANGUAGES
DETALLE_IDIOMAS = {
    "es-co": {"bandera": "🇨🇴", "region": "Colombia"},
    "en": {"bandera": "🇺🇸", "region": "United States"},
}


class IdiomasView(TemplateView):
    """Lista los idiomas disponibles; el cambio lo procesa la vista set_language de Django."""

    template_name = "core/idiomas.html"

    def _destino_seguro(self) -> str:
        destino = self.request.GET.get("next", "")
        if destino and url_has_allowed_host_and_scheme(
            destino, allowed_hosts={self.request.get_host()}, require_https=self.request.is_secure()
        ):
            return destino
        return self.request.path

    def get_context_data(self, **kwargs):
        contexto = super().get_context_data(**kwargs)
        actual = get_language()
        idiomas = []
        for codigo, _nombre in settings.LANGUAGES:
            info = get_language_info(codigo)
            detalle = DETALLE_IDIOMAS.get(codigo, {})
            idiomas.append({
                "codigo": codigo,
                "nombre_local": info["name_local"],
                "nombre_traducido": info["name_translated"],
                "bandera": detalle.get("bandera", ""),
                "region": detalle.get("region", ""),
                "activo": codigo == actual,
            })
        contexto["idiomas"] = idiomas
        contexto["destino"] = self._destino_seguro()
        contexto["plantilla_base"] = (
            "core/base.html" if getattr(self.request, "empresa", None) else "core/tienda/base.html"
        )
        return contexto
