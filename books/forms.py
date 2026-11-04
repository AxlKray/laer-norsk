import re

from django import forms
from django.utils.html import format_html
from django.utils.safestring import mark_safe
from django.conf import settings
from django.core.exceptions import ValidationError

from .models import Book, Genre


class LanguageWidget(forms.Widget):
    """Auswahl D / E / F oder «Andere» mit freier Eingabe (Sprachcode oder Name)."""
    CHOICES = (("de", "D – Deutsch"), ("en", "E – Englisch"), ("fr", "F – Französisch"))

    def render(self, name, value, attrs=None, renderer=None):
        from django.utils.html import format_html, format_html_join
        value = (value or "de").strip()
        known = [c for c, _ in self.CHOICES]
        sel = value if value in known else "other"
        fid = (attrs or {}).get("id") or "id_" + name
        opts = format_html_join(
            "", '<option value="{}"{}>{}</option>',
            [(c, " selected" if c == sel else "", l) for c, l in self.CHOICES] + [("other", " selected" if sel == "other" else "", "Andere …")],
        )
        js = ("var i=document.getElementById('%s');if(this.value==='other'){i.hidden=false;i.value='';i.focus();}"
              "else{i.value=this.value;i.hidden=true;}" % fid)
        return format_html(
            '<select id="{}_sel" onchange="{}">{}</select> '
            '<input type="text" name="{}" id="{}" value="{}" maxlength="20" placeholder="z. B. it oder Italienisch"{}>',
            fid, js, opts, name, fid, value, "" if sel == "other" else " hidden",
        )



class UploadForm(forms.Form):
    """Three separate drop zones: front, back, PDF. Any combination is fine."""
    front = forms.ImageField(required=False)
    back = forms.ImageField(required=False)
    pdf = forms.FileField(required=False)
    isbn = forms.CharField(required=False, label="ISBN", max_length=20)

    def _image(self, name):
        f = self.cleaned_data.get(name)
        if f and f.image.format not in ("JPEG", "PNG"):
            raise ValidationError("Nur JPG oder PNG.")
        if f and f.size > 25 * 1024 * 1024:
            raise ValidationError("Bild zu gross (max. 25 MB).")
        return f

    def clean_front(self):
        return self._image("front")

    def clean_back(self):
        return self._image("back")

    def clean_pdf(self):
        f = self.cleaned_data.get("pdf")
        if f:
            if f.read(5) != b"%PDF-":
                raise ValidationError("Das ist keine PDF-Datei.")
            f.seek(0)
            if f.size > getattr(settings, "BOOK_IMPORT_MAX_PDF_MB", 200) * 1024 * 1024:
                raise ValidationError("PDF zu gross.")
        return f

    def clean_isbn(self):
        from . import importer

        raw = re.sub(r"[\s-]", "", self.cleaned_data.get("isbn", "")).upper()
        if not raw:
            return ""
        if importer.isbn13_valid(raw):
            return raw
        if importer.isbn10_valid(raw):
            return importer.isbn10_to_13(raw)
        raise ValidationError("Das ist keine gültige ISBN (Prüfziffer stimmt nicht).")

    def clean(self):
        data = super().clean()
        if not self.errors and not any(data.get(k) for k in ("front", "back", "pdf", "isbn")):
            raise ValidationError("Bitte eine Datei hinzufügen oder eine ISBN eingeben.")
        return data


class SubtopicSelect(forms.SelectMultiple):
    """Multi-select whose options carry data-parent, so the page can show only the sub-topics of the chosen topic."""
    parents = {}

    def create_option(self, name, value, label, selected, index, subindex=None, attrs=None):
        opt = super().create_option(name, value, label, selected, index, subindex=subindex, attrs=attrs)
        parent = self.parents.get(str(getattr(value, "value", value)))
        if parent:
            opt["attrs"]["data-parent"] = str(parent)
        return opt


ORIGINS = ["Barkasse", "Geschenk", "Nachlass", "Schulbudget", "Tausch"]


class OriginInput(forms.TextInput):
    """Textfeld mit Vorschlägen (Barkasse, Geschenk, …); eigene Eingaben bleiben möglich."""

    def render(self, name, value, attrs=None, renderer=None):
        attrs = dict(attrs or {}, list="origin-list", autocomplete="off")
        html = super().render(name, value, attrs, renderer)
        opts = "".join(f'<option value="{o}">' for o in ORIGINS)
        return format_html('{}<datalist id="origin-list">{}</datalist>', mark_safe(html), mark_safe(opts))


class ImportReviewForm(forms.ModelForm):
    authors_text = forms.CharField(
        label="Mitwirkende", required=False, widget=forms.Textarea(attrs={"rows": 3}),
        help_text="Eine Person pro Zeile, Format: Nachname, Vorname.",
    )
    topic = forms.ModelChoiceField(
        label="Thema", required=False, queryset=Genre.objects.filter(parent__isnull=True, is_tag=False).order_by("name"),
        empty_label="– kein Thema –",
        help_text="Hauptthema, z. B. Physik. Standardthemen: python manage.py seed_topics",
    )
    subtopics = forms.ModelMultipleChoiceField(
        label="Unterthema", required=False, queryset=Genre.objects.filter(parent__isnull=False, is_tag=False).order_by("name"),
        widget=SubtopicSelect(attrs={"size": 8}),
        help_text="Zeigt die Unterthemen des gewählten Themas. Mehrere mit Strg/Cmd-Klick.",
    )
    genres_text = forms.CharField(label="Schlagwörter", required=False, help_text="Mit Komma trennen.")
    analog = forms.BooleanField(label="Analog", required=False)
    digital = forms.BooleanField(label="Digital", required=False)
    publisher_name = forms.CharField(label="Verlag", required=False)
    publisher_place = forms.CharField(label="Verlagsort", required=False)

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["language"].widget = LanguageWidget()
        self.fields["origin"].widget = OriginInput()
        for f in self.fields.values():  # «edition (Ausgabe)» -> «Ausgabe»: nur der deutsche Name
            m = re.match(r".*\((.+)\)$", str(f.label or ""))
            if m:
                f.label = m.group(1)
        self.fields["statement_of_responsibility"].label = "Verantwortliche"
        self.fields["statement_of_responsibility"].help_text = "Angabe wie auf dem Titelblatt, z. B. «David Halliday ; Hrsg. Stephan Koch». Nicht dasselbe wie Mitwirkende."
        self.fields["authors_text"].label = "Mitwirkende"
        self.fields["subtopics"].widget.parents = {
            str(pk): parent for pk, parent in Genre.objects.filter(parent__isnull=False).values_list("pk", "parent_id")
        }

    def clean(self):
        data = super().clean()
        a, d = data.get("analog"), data.get("digital")
        if not (a or d):
            raise ValidationError("Bitte Analog und/oder Digital wählen.")
        self.instance.medium = "both" if (a and d) else ("analog" if a else "digital")
        return data

    class Meta:
        model = Book
        fields = [
            "title", "subtitle", "isbn13", "isbn10", "publication_year", "edition",
            "statement_of_responsibility", "extent", "page_count", "language", "age_category",
            "description", "branch", "location2", "media_group",
            "shelf_location", "inventory_number", "quantity_in_stock", "loan_status", "price", "origin", "physics_number",
        ]
        widgets = {"description": forms.Textarea(attrs={"rows": 4}),
                   "physics_number": forms.TextInput(attrs={"placeholder": "1713"})}
