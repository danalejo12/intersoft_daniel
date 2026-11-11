from django.core.management.base import BaseCommand

from core.models import Empresa
from core.permisos import crear_roles_base, sincronizar_catalogo_permisos


class Command(BaseCommand):
    help = "Sincroniza el catálogo de permisos y asegura los roles base en todas las empresas. Idempotente."

    def handle(self, *args, **options):
        permisos = sincronizar_catalogo_permisos()
        roles_creados = 0
        for empresa in Empresa.objects.all():
            roles_creados += len(crear_roles_base(empresa))
        self.stdout.write(
            f"Permisos activos: {len(permisos)} · Roles base nuevos: {roles_creados}"
        )
