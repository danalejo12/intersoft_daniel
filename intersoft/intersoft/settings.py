"""
Configuración de Intersoft (Django 6.1).

Todo lo que cambia entre entornos se lee de variables de entorno o del archivo .env
(ver .env.example). Los valores por defecto son los seguros: DEBUG=False.
https://docs.djangoproject.com/en/6.1/ref/settings/
"""

from pathlib import Path

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
    'core',
]
AUTH_USER_MODEL = 'core.Usuario'
AUTHENTICATION_BACKENDS = ["core.backends.EmailBackend"]

MIDDLEWARE = [
    'django.middleware.security.SecurityMiddleware',
    'django.contrib.sessions.middleware.SessionMiddleware',
    'django.middleware.common.CommonMiddleware',
    'django.middleware.csrf.CsrfViewMiddleware',
    'django.contrib.auth.middleware.AuthenticationMiddleware',
    'django.contrib.messages.middleware.MessageMiddleware',
    'django.middleware.clickjacking.XFrameOptionsMiddleware',
    'core.middleware.TenantMiddleware',
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
# Archivos que suben los usuarios (fotos de productos). media/ no se sube a git.
MEDIA_URL = 'media/'
MEDIA_ROOT = BASE_DIR / 'media'


# ---------------------------------------------------------------
# Correo (se configura en el Sprint 2)
# ---------------------------------------------------------------
MAILERS = {
    'default': {
        'BACKEND': 'django.core.mail.backends.console.EmailBackend',
    },
}

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
# Solo para desarrollo: pagos.pasarela_simulada() además exige DEBUG=True
PASARELA_SIMULADA = config("PASARELA_SIMULADA", default=False, cast=bool)


# ---------------------------------------------------------------
# Pedidos del marketplace
# ---------------------------------------------------------------
PEDIDO_MINUTOS_RESERVA = config("PEDIDO_MINUTOS_RESERVA", default=30, cast=int)
PEDIDO_MINUTOS_MINIMOS_PAGO = config("PEDIDO_MINUTOS_MINIMOS_PAGO", default=5, cast=int)
PEDIDO_MAX_RENOVACIONES = config("PEDIDO_MAX_RENOVACIONES", default=2, cast=int)
# Tiempo extra, contado desde el vencimiento, para una transacción que Wompi tiene en PENDING
PEDIDO_MAX_ESPERA_PENDIENTE_MINUTOS = config("PEDIDO_MAX_ESPERA_PENDIENTE_MINUTOS", default=120, cast=int)
