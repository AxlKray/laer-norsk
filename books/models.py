from django.conf import settings
from django.core.exceptions import ValidationError
from django.core.validators import FileExtensionValidator, MaxValueValidator, MinValueValidator
from django.db import models
from django.urls import reverse


def validate_isbn13(value):
    """ISBN-13: 13 digits (no hyphens) with a valid check digit."""
    if len(value) != 13 or not value.isdigit():
        raise ValidationError("ISBN-13 must be exactly 13 digits (no hyphens).")
    total = sum(int(d) * (1 if i % 2 == 0 else 3) for i, d in enumerate(value))
    if total % 10 != 0:
        raise ValidationError("Invalid ISBN-13 check digit.")


class Author(models.Model):
    name = models.CharField(max_length=200, help_text="Format: Nachname, Vorname (e.g. Halliday, David).")
    bio = models.TextField(blank=True)

    class Meta:
        ordering = ["name"]

    def __str__(self):
        return self.name


class Publisher(models.Model):
    name = models.CharField(max_length=200, unique=True)
    place = models.CharField("place of publication", max_length=100, blank=True)
    website = models.URLField(blank=True)

    class Meta:
        ordering = ["name"]

    def __str__(self):
        return self.name


class Genre(models.Model):
    name = models.CharField(max_length=100, unique=True)
    is_tag = models.BooleanField("Tag", default=False, help_text="Freies Schlagwort (kein Thema/Unterthema).")
    parent = models.ForeignKey(
        "self", null=True, blank=True, on_delete=models.SET_NULL, related_name="children",
        help_text="Optional: makes this a sub-topic (shown as Thema → Unterthema).",
    )

    class Meta:
        ordering = ["name"]

    def __str__(self):
        return f"{self.parent.name} → {self.name}" if self.parent_id else self.name


class ActiveBookManager(models.Manager):
    """Normale Abfragen (Liste, Suche, Export, Ausleihe) sehen gelöschte Bücher nicht."""

    def get_queryset(self):
        return super().get_queryset().filter(is_deleted=False)


class Book(models.Model):
    class Format(models.TextChoices):
        HARDCOVER = "hardcover", "Hardcover"
        PAPERBACK = "paperback", "Paperback"
        EBOOK = "ebook", "E-book"
        AUDIOBOOK = "audiobook", "Audiobook"

    class AgeCategory(models.TextChoices):
        CHILDREN = "children", "Kinder"
        YOUTH = "youth", "Jugendliche"
        ADULT = "adult", "Erwachsene"

    class Medium(models.TextChoices):
        ANALOG = "analog", "Analog"
        DIGITAL = "digital", "Digital"
        BOTH = "both", "Analog + digital"

    class LoanStatus(models.TextChoices):
        LENDING = "lending", "Ausleihe"
        REFERENCE = "reference", "Präsenz"

    title = models.CharField(max_length=300)
    subtitle = models.CharField(max_length=300, blank=True)
    inventory_number = models.CharField(max_length=50, blank=True, db_index=True)
    authors = models.ManyToManyField(Author, related_name="books")
    isbn13 = models.CharField(
        "ISBN-13", max_length=13, unique=True, validators=[validate_isbn13],
        help_text="13 digits, no hyphens.",
    )
    isbn10 = models.CharField("ISBN-10", max_length=10, blank=True)
    publisher = models.ForeignKey(
        Publisher, null=True, blank=True, on_delete=models.SET_NULL, related_name="books"
    )
    publication_year = models.PositiveSmallIntegerField(null=True, blank=True)
    edition = models.CharField("edition (Ausgabe)", max_length=100, blank=True)
    statement_of_responsibility = models.CharField(
        "statement of responsibility (Verantwortliche)", max_length=300, blank=True
    )
    extent = models.CharField("extent (Umfang)", max_length=100, blank=True, help_text="e.g. XV, 1388 S. : Ill.")
    age_category = models.CharField(
        "age category", max_length=20, choices=AgeCategory.choices, blank=True
    )
    branch = models.CharField("branch (Zweigstelle)", max_length=100, blank=True)
    location2 = models.CharField("location 2 (Standort 2)", max_length=100, blank=True)
    media_group = models.CharField("media group (Mediengruppe)", max_length=100, blank=True)
    loan_status = models.CharField(max_length=20, choices=LoanStatus.choices, default=LoanStatus.LENDING)
    language = models.CharField(
        max_length=10, default="en", help_text="ISO 639-1 code, e.g. en, de, no."
    )
    page_count = models.PositiveIntegerField(null=True, blank=True)
    format = models.CharField(max_length=20, choices=Format.choices, default=Format.PAPERBACK)
    medium = models.CharField(max_length=10, choices=Medium.choices, default=Medium.ANALOG)
    pdf_file = models.FileField(
        "PDF file", upload_to="pdfs/", blank=True,
        validators=[FileExtensionValidator(["pdf"])], help_text="Digital titles: upload the PDF ...",
    )
    pdf_name = models.CharField("PDF-Name", max_length=150, blank=True, help_text="Anzeigename des PDF; leer = Dateiname.")
    pdf_url = models.URLField("PDF link", blank=True, help_text="... or link to a PDF stored elsewhere.")
    genres = models.ManyToManyField(Genre, blank=True, related_name="books")
    description = models.TextField("Zusammenfassung", blank=True)
    cover_image = models.ImageField("front cover", upload_to="covers/front/", blank=True)
    back_cover_image = models.ImageField("back cover", upload_to="covers/back/", blank=True)
    price = models.DecimalField("Preis (CHF)", max_digits=8, decimal_places=2, null=True, blank=True)
    physics_number = models.CharField("Physikbibliothek-Nummer", max_length=50, blank=True, help_text="Nummer in der Physikbibliothek. Wird nicht exportiert.")
    origin = models.CharField("Herkunft", max_length=100, blank=True, help_text="z. B. Barkasse, Geschenk, Nachlass. Nur für Buchadmin sichtbar.")
    quantity_in_stock = models.PositiveIntegerField(default=0)
    shelf_location = models.CharField("signature / code", max_length=50, blank=True)
    internal_notes = models.TextField(blank=True, help_text="Staff only, never shown publicly.")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    # "Gelöscht" = nur ausgeblendet. Die Daten bleiben erhalten; die IT kann das Buch im Admin wiederherstellen.
    is_deleted = models.BooleanField("gelöscht", default=False, db_index=True)
    deleted_at = models.DateTimeField("gelöscht am", null=True, blank=True)
    deleted_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL,
        related_name="+", verbose_name="gelöscht von",
    )

    # "Entsorgt" = Buch physisch weg, bleibt aber in der Liste (mit Symbol) und kann nicht mehr ausgeliehen werden.
    is_disposed = models.BooleanField("entsorgt", default=False, db_index=True)
    disposed_at = models.DateTimeField("entsorgt am", null=True, blank=True)

    objects = ActiveBookManager()
    all_objects = models.Manager()  # inkl. gelöschte (Admin, IT)

    class Meta:
        ordering = ["title"]
        default_manager_name = "all_objects"
        indexes = [models.Index(fields=["title"])]

    def __str__(self):
        return self.title

    @property
    def cover_color_index(self):
        """Farbe des Platzhalter-Titelbilds: immer blau (0)."""
        return 0

    @property
    def topic_paths(self):
        """[(Thema, Unterthema or None), ...] for display as «Physik → Lehrbuch»."""
        gs = [g for g in self.genres.all() if not g.is_tag]
        parents = {g.parent_id for g in gs if g.parent_id}
        return [(g.parent, g) for g in gs if g.parent_id] + [(g, None) for g in gs if not g.parent_id and g.pk not in parents]

    @property
    def media_group_display(self):
        """Mediengruppe: eingetragener Wert, sonst aus Alterskategorie und Sprache, z. B. «Sachbuch Erw. dt.»."""
        if self.media_group:
            return self.media_group
        age = {"children": "Kinder", "youth": "Jug.", "adult": "Erw."}.get(self.age_category, "")
        lang = {"de": "dt.", "en": "engl.", "fr": "franz."}.get(self.language, self.language)
        return " ".join(x for x in ("Sachbuch", age, lang) if x)

    @property
    def tags(self):
        """Freie Schlagwörter (Tags) des Buchs."""
        return [g for g in self.genres.all() if g.is_tag]

    @property
    def is_physical(self):
        return self.medium in (self.Medium.ANALOG, self.Medium.BOTH)

    @property
    def is_digital(self):
        return self.medium in (self.Medium.DIGITAL, self.Medium.BOTH)

    @property
    def pdf_display_name(self):
        """Name des PDF: eingetragener Name, sonst der Dateiname."""
        if self.pdf_name:
            return self.pdf_name
        return self.pdf_file.name.rsplit("/", 1)[-1] if self.pdf_file else ""

    @property
    def has_pdf(self):
        return bool(self.pdf_file or self.pdf_url)

    @property
    def has_digital(self):
        """Digital tab/row is shown only when there is something digital: medium or a PDF."""
        return self.is_digital or self.has_pdf

    def get_absolute_url(self):
        return reverse("books:detail", args=[self.pk])

    def save(self, *args, **kwargs):
        self.isbn13 = self.isbn13.replace("-", "").replace(" ", "")
        self.isbn10 = self.isbn10.replace("-", "").replace(" ", "")
        self.edition = self.edition.strip().strip("[]").strip()  # Katalog-Klammern «[1. Aufl.]» nicht anzeigen
        super().save(*args, **kwargs)


class Favorite(models.Model):
    """Lieblingsbuch einer angemeldeten Person (nur für sie selbst sichtbar)."""
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="book_favorites")
    book = models.ForeignKey(Book, on_delete=models.CASCADE, related_name="favorites")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [models.UniqueConstraint(fields=["user", "book"], name="unique_book_favorite")]

    def __str__(self):
        return f"{self.user} ★ {self.book}"


class Comment(models.Model):
    book = models.ForeignKey(Book, on_delete=models.CASCADE, related_name="comments")
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="book_comments"
    )
    text = models.TextField()
    rating = models.PositiveSmallIntegerField(
        null=True, blank=True, validators=[MinValueValidator(1), MaxValueValidator(5)],
        help_text="Optional, 1 to 5.",
    )
    is_visible = models.BooleanField(default=True, help_text="Untick to hide (moderation).")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return f"{self.user} on {self.book}"


class ImportDraft(models.Model):
    """Uploaded files and found data while an import waits for review."""

    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE)
    created_at = models.DateTimeField(auto_now_add=True)
    front = models.ImageField(upload_to="import_tmp/", blank=True)
    back = models.ImageField(upload_to="import_tmp/", blank=True)
    pdf = models.FileField(upload_to="import_tmp/", blank=True)
    isbn = models.CharField(max_length=13, blank=True)
    isbn_source = models.CharField(max_length=100, blank=True)
    data = models.JSONField(default=dict, blank=True)
    sources = models.JSONField(default=list, blank=True)
    notes = models.JSONField(default=list, blank=True)

    def discard(self):
        """Delete temporary files and the draft itself."""
        for f in (self.front, self.back, self.pdf):
            if f:
                f.delete(save=False)
        self.delete()
