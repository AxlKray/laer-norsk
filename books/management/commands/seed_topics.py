from django.core.management.base import BaseCommand

from books.models import Genre

# Thema -> Unterthemen. The Physik split follows the usual library classification
# (Dewey 530-539, 520 Astronomie); extend freely in the admin.
TOPICS = {
    "Physik": [
        "Mechanik", "Strömung", "Akustik", "Wellen und Schwingungen", "Optik", "Wärmelehre",
        "Energie", "Elektrizität", "Magnetismus", "Elektrodynamik", "Atomphysik", "Kernphysik",
        "Teilchenphysik", "Quantenphysik", "Relativitätstheorie", "Festkörperphysik", "Astronomie",
        "Astrophysik", "Kosmologie", "Geophysik und Meteorologie", "Messtechnik",
        "Mathematische Methoden", "Didaktik", "Geschichte", "Aufgaben", "Praktikum", "Experimente",
        "Lehrbuch", "Formelsammlung", "Nachschlagewerk", "Populärwissenschaft", "Biographien",
    ],
    "Mathematik": [], "Chemie": [], "Informatik": [], "Biologie": [],
}


def seed():
    """Standardthemen anlegen (mehrfach ausführbar). Gibt die Zahl neuer Einträge zurück."""
    new = 0
    for parent_name, children in TOPICS.items():
        parent, made = Genre.objects.get_or_create(name=parent_name)
        new += made
        if parent.is_tag:  # ein früher von Hand angelegtes Schlagwort gleichen Namens wird zum Thema
            parent.is_tag = False
            parent.save(update_fields=["is_tag"])
        for name in children:
            child, made = Genre.objects.get_or_create(name=name, defaults={"parent": parent})
            if not child.parent_id and child != parent:
                child.parent = parent
                child.is_tag = False
                child.save(update_fields=["parent", "is_tag"])
            new += made
    return new


def ensure_topics():
    """Gibt es noch kein Thema, werden die Standardthemen automatisch angelegt."""
    if not Genre.objects.filter(parent__isnull=True, is_tag=False).exists():
        seed()


class Command(BaseCommand):
    help = "Create the standard topics (Thema -> Unterthema). Safe to run again."

    def handle(self, *args, **opts):
        self.stdout.write(f"{seed()} neue Themen angelegt.")
