from django.core.management.base import BaseCommand

from campeonatos.servicios import validar_vencidos


class Command(BaseCommand):
    help = "Valida los resultados provisorios cuyo plazo de carga ya venció (correr una vez por día)."

    def handle(self, *args, **options):
        n = validar_vencidos()
        self.stdout.write(self.style.SUCCESS(f"{n} resultado(s) validado(s)."))
