"""Vuelve a cifrar los secretos de pago de todos los negocios con la clave principal.

Uso al rotar: en PAGOS_CLAVES_CIFRADO pon la clave nueva primero y la anterior después,
ejecuta este comando y, cuando termine, quita la clave anterior del .env.
"""
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from core.cifrado import SecretoIlegible, recifrar
from core.models import ConfiguracionPagos, Pago
from core.models.pagos import CAMPOS_SECRETOS


class Command(BaseCommand):
    """Comando `python manage.py rotar_secretos_pago`: Recifra las llaves de Wompi de cada negocio con la clave
    principal de PAGOS_CLAVES_CIFRADO.
    """
    help = "Recifra las llaves de Wompi de cada negocio con la clave principal de PAGOS_CLAVES_CIFRADO."

    def add_arguments(self, parser):
        parser.add_argument("--desde-secret-key", action="store_true",
                            help="Migra datos cifrados con la derivación de SECRET_KEY a la clave maestra nueva.")

    def handle(self, *args, **options):
        total = 0
        with transaction.atomic():
            for config in ConfiguracionPagos.objects.select_for_update():
                columnas = list(CAMPOS_SECRETOS.values())
                try:
                    for columna in columnas:
                        setattr(config, columna, recifrar(getattr(config, columna),
                                                         incluir_clave_derivada=options["desde_secret_key"]))
                except SecretoIlegible as error:
                    raise CommandError(
                        f"No se pudo descifrar la configuración del negocio {config.empresa_id}. "
                        "¿Quitaste la clave anterior antes de rotar? No se cambió nada."
                    ) from error
                config.save(update_fields=columnas)
                total += 1
            for pago in Pago.objects.select_for_update().exclude(credenciales_cifradas=""):
                try:
                    pago.credenciales_cifradas = recifrar(pago.credenciales_cifradas,
                                                         incluir_clave_derivada=options["desde_secret_key"])
                except SecretoIlegible as error:
                    raise CommandError(f"No se pudo recifrar el pago {pago.pk}. No se cambió nada.") from error
                pago.save(update_fields=["credenciales_cifradas"])
        self.stdout.write(self.style.SUCCESS(f"Recifradas {total} configuraciones de pago."))
