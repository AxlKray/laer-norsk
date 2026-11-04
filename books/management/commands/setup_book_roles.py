from django.contrib.auth.models import Group, Permission
from django.core.management.base import BaseCommand

PERMS = [
    ("books", ["add_book", "change_book", "delete_book", "add_author", "change_author",
               "add_publisher", "change_publisher", "add_genre", "change_genre", "change_comment", "delete_comment"]),
    ("book_loans", ["add_bookloan", "change_bookloan", "delete_bookloan"]),
]


class Command(BaseCommand):
    help = 'Legt die Gruppe "Buchadmin" mit allen Rechten für das Bücher-Modul an. Danach Personen im Admin dieser Gruppe zuordnen.'

    def handle(self, *args, **options):
        group, _ = Group.objects.get_or_create(name="Buchadmin")
        found = Permission.objects.filter(
            content_type__app_label__in=[a for a, _ in PERMS],
            codename__in=[c for _, codes in PERMS for c in codes],
        )
        group.permissions.set(found)
        self.stdout.write(self.style.SUCCESS(f'Gruppe "Buchadmin" mit {found.count()} Rechten bereit.'))
