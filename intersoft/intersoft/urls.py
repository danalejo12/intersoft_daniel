"""
URL configuration for intersoft project.

The `urlpatterns` list routes URLs to views. For more information please see:
    https://docs.djangoproject.com/en/6.1/topics/http/urls/
Examples:
Function views
    1. Add an import:  from my_app import views
    2. Add a URL to urlpatterns:  path('', views.home, name='home')
Class-based views
    1. Add an import:  from other_app.views import Home
    2. Add a URL to urlpatterns:  path('', Home.as_view(), name='home')
Including another URLconf
    1. Import the include() function: from django.urls import include, path
    2. Add a URL to urlpatterns:  path('blog/', include('blog.urls'))
"""
from django.conf import settings
from django.conf.urls.static import static
from django.contrib import admin
from django.urls import include, path
from django.views.i18n import JavaScriptCatalog

from core.views_salud import salud_view, sw_view
from suscripciones.views_panel import PreciosPublicosView

urlpatterns = [
    path('admin/', admin.site.urls),
    path("salud/", salud_view, name="salud"),
    path("i18n/", include("django.conf.urls.i18n")),
    path("jsi18n/", JavaScriptCatalog.as_view(), name="javascript-catalog"),
    path("sw.js", sw_view, name="sw_js"),
    path("precios/", PreciosPublicosView.as_view(), name="precios_publicos"),
    path("plataforma/", include("plataforma.urls")),
    path("pqrs/", include("pqrs.urls")),
    path("soporte/", include("soporte.urls")),
    path("api/", include("suscripciones.urls")),
    path("", include("core.urls")),
] + static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)  # static() solo actúa con DEBUG=True
