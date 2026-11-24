"""
Configuración de Intersoft (Django 6.1).

Todo lo que cambia entre entornos se lee de variables de entorno o del archivo .env
(ver .env.example). Los valores por defecto son los seguros: DEBUG=False.
https://docs.djangoproject.com/en/6.1/ref/settings/
"""

from datetime import timedelta
from pathlib import Path
import sys

from decouple import AutoConfig, Csv

BASE_DIR = Path(__file__).resolve().parent.parent

# Un solo cargador: primero las variables del sistema y, si faltan, el archivo .env de BASE_DIR
config = AutoConfig(search_path=str(BASE_DIR))


# ---------------------------------------------------------------
# Lo básico
# ---------------------------------------------------------------
SECRET_KEY = config("DJANGO_SECRET_KEY")  # obligatoria: sin ella el proyecto no arranca
DEBUG = config("DEBUG", default=False, cast=bool)
# Con DEBUG=True y la lista vacía, Django acepta localhost y 127.0.0.1
ALLOWED_HOSTS = config("ALLOWED_HOSTS", default="", cast=Csv())
CSRF_TRUSTED_ORIGINS = config("CSRF_TRUSTED_ORIGINS", default="", cast=Csv())


# ---------------------------------------------------------------
# Aplicación
# ---------------------------------------------------------------
INSTALLED_APPS = [
    'django.contrib.admin',
    'django.contrib.auth',
    'django.contrib.contenttypes',
    'django.contrib.sessions',
    'django.contrib.messages',
    'django.contrib.staticfiles',
    'rest_framework',
    'drf_spectacular',
    'axes',
    'core',
    'suscripciones',
    'plataforma',
    'pqrs',
    'soporte',
    'datos_personales',
]
AUTH_USER_MODEL = 'core.Usuario'
AUTHENTICATION_BACKENDS = [
    "axes.backends.AxesStandaloneBackend",  # primero: rechaza a quien está bloqueado
    "core.backends.EmailBackend",
]

MIDDLEWARE = [
    'django.middleware.security.SecurityMiddleware',
    'core.ratelimit.RateLimitMiddleware',
    'django.contrib.sessions.middleware.SessionMiddleware',
    'django.middleware.common.CommonMiddleware',
    'django.middleware.csrf.CsrfViewMiddleware',
    'django.contrib.auth.middleware.AuthenticationMiddleware',
    'django.contrib.messages.middleware.MessageMiddleware',
    'django.middleware.clickjacking.XFrameOptionsMiddleware',
    'core.middleware.ContentSecurityPolicyMiddleware',
    'core.middleware.TenantMiddleware',
    'datos_personales.middleware.ExigirAutorizacionDatosMiddleware',  # Ley 1581: autorización vigente
    'axes.middleware.AxesMiddleware',  # al final, como pide django-axes
]

ROOT_URLCONF = 'intersoft.urls'

TEMPLATES = [
    {
        'BACKEND': 'django.template.backends.django.DjangoTemplates',
        'DIRS': [],
        'APP_DIRS': True,
        'OPTIONS': {
            'context_processors': [
                'django.template.context_processors.request',
                'django.contrib.auth.context_processors.auth',
                'django.contrib.messages.context_processors.messages',
                'core.context_processors.carrito',
                'core.bienvenida.bienvenida',
                'soporte.context_processors.soporte_feedback',
            ],
        },
    },
]

WSGI_APPLICATION = 'intersoft.wsgi.application'

# Las pruebas usan HTTP: este ejecutor apaga solo para ellas la redirección a HTTPS
TEST_RUNNER = "core.pruebas.EjecutorPruebas"


# ---------------------------------------------------------------
# Base de datos
# ---------------------------------------------------------------
DATABASES = {
    'default': {
        'ENGINE': 'django.db.backends.postgresql',
        'NAME': config('DB_NAME', default='intersoft'),
        'USER': config('DB_USER', default='postgres'),
        'PASSWORD': config('DB_PASSWORD'),
        'HOST': config('DB_HOST', default='localhost'),
        'PORT': config('DB_PORT', default=''),
    }
}


# ---------------------------------------------------------------
# Seguridad en producción (solo con DEBUG=False)
# ---------------------------------------------------------------
if not DEBUG:
    SECURE_SSL_REDIRECT = config("SECURE_SSL_REDIRECT", default=True, cast=bool)
    SESSION_COOKIE_SECURE = True
    CSRF_COOKIE_SECURE = True
    SECURE_HSTS_SECONDS = config("SECURE_HSTS_SECONDS", default=31536000, cast=int)
    # Ambas afectan a todos los subdominios y el preload es difícil de revertir: se activan a propósito
    SECURE_HSTS_INCLUDE_SUBDOMAINS = config("SECURE_HSTS_INCLUDE_SUBDOMAINS", default=False, cast=bool)
    SECURE_HSTS_PRELOAD = config("SECURE_HSTS_PRELOAD", default=False, cast=bool)
    # Solo es seguro detrás de un proxy que siempre reescribe este encabezado (Nginx, el balanceador, etc.)
    SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")


# ---------------------------------------------------------------
# Contraseñas
# ---------------------------------------------------------------
AUTH_PASSWORD_VALIDATORS = [
    {'NAME': 'django.contrib.auth.password_validation.UserAttributeSimilarityValidator'},
    {'NAME': 'django.contrib.auth.password_validation.MinimumLengthValidator'},
    {'NAME': 'django.contrib.auth.password_validation.CommonPasswordValidator'},
    {'NAME': 'django.contrib.auth.password_validation.NumericPasswordValidator'},
]


# ---------------------------------------------------------------
# Idioma y zona horaria
# ---------------------------------------------------------------
LANGUAGE_CODE = 'es-co'
TIME_ZONE = 'America/Bogota'
USE_I18N = True
USE_TZ = True


# ---------------------------------------------------------------
# Archivos
# ---------------------------------------------------------------
STATIC_URL = 'static/'
STATIC_ROOT = BASE_DIR / 'staticfiles'
# Archivos que suben los usuarios (fotos de productos). media/ no se sube a git.
MEDIA_URL = 'media/'
MEDIA_ROOT = BASE_DIR / 'media'


# ---------------------------------------------------------------
# Correo: SMTP en producción si se configura EMAIL_HOST; consola como respaldo
# ---------------------------------------------------------------
def _construir_mailers(
    *,
    host="",
    port=587,
    username="",
    password="",
    use_tls=True,
    use_ssl=False,
):
    """Configuración del correo: SMTP si hay EMAIL_HOST; si no, la consola (desarrollo)."""
    if host:
        return {
            "default": {
                "BACKEND": "django.core.mail.backends.smtp.EmailBackend",
                "OPTIONS": {
                    "host": host,
                    "port": port,
                    "username": username,
                    "password": password,
                    "use_tls": use_tls,
                    "use_ssl": use_ssl,
                },
            },
        }
    return {
        "default": {
            "BACKEND": "django.core.mail.backends.console.EmailBackend",
        },
    }


DEFAULT_FROM_EMAIL = config("DEFAULT_FROM_EMAIL", default="no-responder@intersoft.local")
SERVER_EMAIL = config("SERVER_EMAIL", default=DEFAULT_FROM_EMAIL)

MAILERS = _construir_mailers(
    host=config("EMAIL_HOST", default=""),
    port=config("EMAIL_PORT", default=587, cast=int),
    username=config("EMAIL_HOST_USER", default=""),
    password=config("EMAIL_HOST_PASSWORD", default=""),
    use_tls=config("EMAIL_USE_TLS", default=True, cast=bool),
    use_ssl=config("EMAIL_USE_SSL", default=False, cast=bool),
)

# Reciben por correo los avisos critical (reembolsos, cobros duplicados). Separados por coma.
ADMINS = config("ADMINS", default="", cast=Csv())


# ---------------------------------------------------------------
# Registros: consola y archivo rotativo
# ---------------------------------------------------------------
LOG_DIR = Path(config("LOG_DIR", default=str(BASE_DIR / "logs")))
LOG_DIR.mkdir(parents=True, exist_ok=True)

LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "formatters": {
        "detallado": {"format": "{asctime} {levelname} {name}: {message}", "style": "{"},
    },
    "handlers": {
        "consola": {"class": "logging.StreamHandler", "formatter": "detallado"},
        "archivo": {
            "class": "logging.handlers.RotatingFileHandler",
            "filename": str(LOG_DIR / "intersoft.log"),
            "maxBytes": 5 * 1024 * 1024,  # 5 MB por archivo
            "backupCount": 10,
            "encoding": "utf-8",
            "delay": True,
            "formatter": "detallado",
        },
        # Sin ADMINS no envía nada; con el correo de desarrollo, lo muestra en la consola
        "correo_admins": {"class": "django.utils.log.AdminEmailHandler", "level": "CRITICAL"},
    },
    "loggers": {
        "django": {"handlers": ["consola", "archivo"], "level": "WARNING", "propagate": False},
        "core": {"handlers": ["consola", "archivo"], "level": "INFO", "propagate": False},
        # Aquí están los avisos de dinero: reembolsos, montos distintos y cobros duplicados
        "core.pagos": {"handlers": ["consola", "archivo", "correo_admins"], "level": "INFO", "propagate": False},
        "core.reservas": {"handlers": ["consola", "archivo", "correo_admins"], "level": "INFO", "propagate": False},
    },
}

# ---------------------------------------------------------------
# Límite de intentos de ingreso (django-axes)
# ---------------------------------------------------------------
AXES_FAILURE_LIMIT = 5
AXES_COOLOFF_TIME = timedelta(minutes=15)
# Se bloquea la combinación correo + IP: un atacante no puede dejar sin acceso a toda una oficina
AXES_LOCKOUT_PARAMETERS = [["username", "ip_address"]]
# El login no distingue mayúsculas: ANA@correo.co y ana@correo.co cuentan como el mismo intento
AXES_USERNAME_CALLABLE = "core.acceso.correo_del_intento"
AXES_RESET_ON_SUCCESS = True
AXES_LOCKOUT_TEMPLATE = "core/tienda/bloqueado.html"

LOGIN_URL = "login"
LOGIN_REDIRECT_URL = "despues_login"  # dueños al panel, compradores al marketplace
LOGOUT_REDIRECT_URL = "marketplace"


# ---------------------------------------------------------------
# Wompi
# ---------------------------------------------------------------
WOMPI_PUBLIC_KEY = config("WOMPI_PUBLIC_KEY", default="")
WOMPI_INTEGRITY_SECRET = config("WOMPI_INTEGRITY_SECRET", default="")
WOMPI_EVENTS_SECRET = config("WOMPI_EVENTS_SECRET", default="")
WOMPI_PRIVATE_KEY = config("WOMPI_PRIVATE_KEY", default="")  # Solo para consultar transacciones
WOMPI_CHECKOUT_URL = "https://checkout.wompi.co/p/"
# Cuenta de Wompi de INTERSOFT para cobrar los planes (no la de los negocios ni las WOMPI_* históricas).
# Sin la llave pública, los planes pagos no se pueden contratar desde el panel.
SUSCRIPCIONES_WOMPI_PUBLIC_KEY = config("SUSCRIPCIONES_WOMPI_PUBLIC_KEY", default="")
SUSCRIPCIONES_WOMPI_INTEGRITY_SECRET = config("SUSCRIPCIONES_WOMPI_INTEGRITY_SECRET", default="")
SUSCRIPCIONES_WOMPI_EVENTS_SECRET = config("SUSCRIPCIONES_WOMPI_EVENTS_SECRET", default="")
SUSCRIPCIONES_WOMPI_PRIVATE_KEY = config("SUSCRIPCIONES_WOMPI_PRIVATE_KEY", default="")
# Cifra las llaves de Wompi de cada negocio. Varias separadas por comas: la primera cifra.
PAGOS_CLAVES_CIFRADO = config("PAGOS_CLAVES_CIFRADO", default="")
DEFAULT_EXCEPTION_REPORTER_FILTER = "core.cifrado.FiltroSecretosPago"
# Solo para desarrollo: pagos.pasarela_simulada() además exige DEBUG=True
PASARELA_SIMULADA = config("PASARELA_SIMULADA", default=False, cast=bool)

# Compatibilidad de configuración antigua. Las ventas usan las tarifas guardadas por negocio.
WOMPI_COBRAR_TARIFA_AL_COMPRADOR = config("WOMPI_COBRAR_TARIFA_AL_COMPRADOR", default=True, cast=bool)
WOMPI_TARIFA_PORCENTAJE = config("WOMPI_TARIFA_PORCENTAJE", default="2.65")
WOMPI_TARIFA_FIJA = config("WOMPI_TARIFA_FIJA", default="700")
WOMPI_TARIFA_IVA = config("WOMPI_TARIFA_IVA", default="19")

# Aviso de pedido pagado por WhatsApp Cloud API (opcional). La plantilla debe estar aprobada
# por Meta, en español, con tres variables en el cuerpo: número de pedido, total y cliente.
WHATSAPP_TOKEN = config("WHATSAPP_TOKEN", default="")
WHATSAPP_TELEFONO_ID = config("WHATSAPP_TELEFONO_ID", default="")
WHATSAPP_PLANTILLA_PEDIDO = config("WHATSAPP_PLANTILLA_PEDIDO", default="")


# ---------------------------------------------------------------
# Pedidos del marketplace
# ---------------------------------------------------------------
PEDIDO_MINUTOS_RESERVA = config("PEDIDO_MINUTOS_RESERVA", default=30, cast=int)
PEDIDO_MINUTOS_MINIMOS_PAGO = config("PEDIDO_MINUTOS_MINIMOS_PAGO", default=5, cast=int)
PEDIDO_MAX_RENOVACIONES = config("PEDIDO_MAX_RENOVACIONES", default=2, cast=int)
# Tiempo extra, contado desde el vencimiento, para una transacción que Wompi tiene en PENDING
PEDIDO_MAX_ESPERA_PENDIENTE_MINUTOS = config("PEDIDO_MAX_ESPERA_PENDIENTE_MINUTOS", default=120, cast=int)


# ---------------------------------------------------------------
# Monitoreo opcional de errores (Sentry)
# ---------------------------------------------------------------
def _inicializar_monitoreo(*, dsn="", environment="production", traces_sample_rate=0.0):
    """Inicializa Sentry solo cuando SENTRY_DSN está definido y sentry-sdk está instalado."""
    dsn_limpio = (dsn or "").strip()
    if not dsn_limpio:
        return False
    try:
        import sentry_sdk
    except ImportError:
        import logging

        logging.getLogger("core").warning(
            "SENTRY_DSN está configurado pero el paquete 'sentry-sdk' no está instalado."
        )
        return False
    sentry_sdk.init(
        dsn=dsn_limpio,
        environment=environment,
        traces_sample_rate=traces_sample_rate,
        send_default_pii=False,
    )
    return True


SENTRY_DSN = config("SENTRY_DSN", default="")
SENTRY_ENVIRONMENT = config("SENTRY_ENVIRONMENT", default="production")
SENTRY_TRACES_SAMPLE_RATE = config("SENTRY_TRACES_SAMPLE_RATE", default=0.0, cast=float)
_inicializar_monitoreo(
    dsn=SENTRY_DSN,
    environment=SENTRY_ENVIRONMENT,
    traces_sample_rate=SENTRY_TRACES_SAMPLE_RATE,
)


# ---------------------------------------------------------------
# Django REST Framework
# ---------------------------------------------------------------
REST_FRAMEWORK = {
    "EXCEPTION_HANDLER": "suscripciones.exceptions.manejador_excepciones_suscripciones",
    "DEFAULT_SCHEMA_CLASS": "drf_spectacular.openapi.AutoSchema",
    "DEFAULT_THROTTLE_CLASSES": [
        "rest_framework.throttling.AnonRateThrottle",
        "rest_framework.throttling.UserRateThrottle",
    ],
    "DEFAULT_THROTTLE_RATES": {
        "anon": config("DRF_THROTTLE_ANON", default="60/min"),
        "user": config("DRF_THROTTLE_USER", default="300/min"),
    },
}

def construir_caches(redis_url: str = "") -> dict:
    """Usa Redis cuando REDIS_URL está definido; en otro caso mantiene LocMemCache."""
    url = (redis_url or "").strip()
    if url:
        return {
            "default": {
                "BACKEND": "django.core.cache.backends.redis.RedisCache",
                "LOCATION": url,
            }
        }
    return {
        "default": {
            "BACKEND": "django.core.cache.backends.locmem.LocMemCache",
        }
    }


REDIS_URL = config("REDIS_URL", default="")
CACHES = construir_caches(REDIS_URL)

RATELIMIT_ACTIVO = config("RATELIMIT_ACTIVO", default=("test" not in sys.argv), cast=bool)
# Cuántos proxies de confianza hay delante de Django (nginx = 1). Con 0 se usa REMOTE_ADDR y se ignora
# X-Forwarded-For, que el cliente puede inventar. Nunca pongas más proxies de los que realmente hay.
RATELIMIT_PROXIES_DE_CONFIANZA = config("RATELIMIT_PROXIES_DE_CONFIANZA", default=0, cast=int)
if RATELIMIT_PROXIES_DE_CONFIANZA > 0:
    # django-axes (bloqueo por intentos) usa la misma regla: detrás de nginx toma la IP real del cliente
    # contando proxies desde la derecha, nunca el primer valor que el cliente puede inventar.
    AXES_IPWARE_PROXY_COUNT = RATELIMIT_PROXIES_DE_CONFIANZA
    AXES_IPWARE_META_PRECEDENCE_ORDER = ("HTTP_X_FORWARDED_FOR", "REMOTE_ADDR")

CSP_ACTIVA = config("CSP_ACTIVA", default=True, cast=bool)
CSP_POLITICA = config(
    "CSP_POLITICA",
    default=(
        "default-src 'self'; "
        "script-src 'self' https://cdn.jsdelivr.net https://checkout.wompi.co; "
        "style-src 'self' 'unsafe-inline' https://fonts.googleapis.com; "
        "font-src 'self' https://fonts.gstatic.com; "
        "img-src 'self' data: blob: https:; "
        "connect-src 'self' https://production.wompi.co https://sandbox.wompi.co; "
        "frame-src 'self' https://checkout.wompi.co; "
        "object-src 'none'; "
        "base-uri 'self'; "
        "frame-ancestors 'self'"
    ),
)

SPECTACULAR_SETTINGS = {
    "TITLE": "InterSoft API",
    "DESCRIPTION": "API REST multi-tenant de InterSoft (planes, suscripciones, límites y comisiones).",
    "VERSION": "1.0.0",
    "SERVE_INCLUDE_SCHEMA": False,
    "SERVE_PERMISSIONS": ["suscripciones.permissions.SwaggerPermitido"],
}


# ---------------------------------------------------------------
# PQRS (Peticiones, Quejas, Reclamos y Sugerencias)
# ---------------------------------------------------------------
# Plazo de respuesta en días hábiles (sin sábados, domingos ni festivos de Colombia).
# IMPORTANTE: validar este plazo con un abogado antes de salir a producción.
PQRS_DIAS_RESPUESTA = config("PQRS_DIAS_RESPUESTA", default=15, cast=int)


# ---------------------------------------------------------------
# Protección de datos personales (Ley 1581 de 2012 y Decreto 1377 de 2013)
# ---------------------------------------------------------------
# Identificación del responsable del tratamiento que se publica en la política (/privacidad/).
# Mientras falte alguno, la política lo muestra en rojo: no se inventan datos de la empresa.
DATOS_RESPONSABLE_RAZON_SOCIAL = config("DATOS_RESPONSABLE_RAZON_SOCIAL", default="")
DATOS_RESPONSABLE_NIT = config("DATOS_RESPONSABLE_NIT", default="")
DATOS_RESPONSABLE_DIRECCION = config("DATOS_RESPONSABLE_DIRECCION", default="")
DATOS_RESPONSABLE_CORREO = config("DATOS_RESPONSABLE_CORREO", default="")
DATOS_RESPONSABLE_TELEFONO = config("DATOS_RESPONSABLE_TELEFONO", default="")
# Pide la autorización vigente a quien inicia sesión. Se apaga en la suite de pruebas general
# (las pruebas de datos_personales la encienden) para no tener que aceptar en cada prueba.
PROTECCION_DATOS_EXIGIR_AUTORIZACION = config(
    "PROTECCION_DATOS_EXIGIR_AUTORIZACION", default="test" not in sys.argv, cast=bool
)
