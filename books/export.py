"""Builds the export ZIP: MARC21 (.mrc + MARCXML), ISBN list, CSV, covers/ and pdf/ folders."""
import csv
import io
import os
import tempfile
import zipfile

from . import marc

HEADERS = [
    "Titel", "Untertitel", "Mitwirkende", "Verantwortliche", "Ausgabe",
    "Verlag", "Verlagsort", "Erscheinungsjahr", "Umfang", "Seiten", "ISBN-13", "ISBN-10",
    "Alterskategorie", "Sprache", "Schlagwörter", "Zusammenfassung", "Medium",
    "Zweigstelle", "Signatur", "Standort 2", "Mediengruppe", "Status",
    "Anzahl Exemplare", "Inventarnummer", "Preis CHF", "Titelbild", "Rückseite", "PDF",
]

README = """Bücher-Export
=============
buecher.mrc           Katalogdaten im Standardformat MARC21 (binär, UTF-8) für Bibliothekssoftware.
                      Eigene Felder: 852 = Zweigstelle/Standort/Signatur/Inventar (ein Feld pro
                      Exemplar), 990 = Mediengruppe/Status/Medium, 856 = Link/Pfad zum PDF.
buecher-marcxml.xml   dieselben Datensätze als MARCXML (lesbar, zum Prüfen).
isbn-liste.txt        eine ISBN pro Zeile (für die automatische Fremddatenübernahme).
buecher.csv           alle Titel als Tabelle. Trennzeichen: Semikolon (;), UTF-8 mit BOM
                      (Excel öffnet die Datei direkt). Mehrfachwerte durch " | " getrennt.
                      Mitwirkende im Format "Nachname, Vorname".
covers/               Titelbilder und Rückseiten: <ISBN-13>_front / _back.
pdf/                  PDF-Dateien digitaler Titel: <ISBN-13>.pdf.
Die Spalten "Titelbild", "Rückseite" und "PDF" in der CSV nennen den Pfad in diesem ZIP.
Welche Datei und welche Feldzuordnung die Bibliothekssoftware genau braucht, vorab mit dem
Hersteller klären; eine Testdatei mit wenigen Titeln hilft dabei.
"""


def _add_image(zf, book, field, kind):
    if not field:
        return ""
    ext = os.path.splitext(field.name)[1].lower() or ".jpg"
    name = f"covers/{book.isbn13 or book.pk}_{kind}{ext}"
    try:
        field.open("rb")
        data = field.read()
        field.close()
    except (OSError, ValueError):
        return ""
    zf.writestr(name, data)
    return name


def _topics(book):
    """Topic names including parent topics, without duplicates."""
    names = []
    for g in book.genres.all():
        for name in ([g.parent.name] if g.parent else []) + [g.name]:
            if name not in names:
                names.append(name)
    return names


def _add_pdf(zf, book, with_pdf=True):
    """Put an uploaded PDF into pdf/ (nur wenn with_pdf); fall back to the external link."""
    if book.pdf_file and not with_pdf:
        return ""
    if book.pdf_file:
        try:
            book.pdf_file.open("rb")
            data = book.pdf_file.read()
            book.pdf_file.close()
        except (OSError, ValueError):
            return book.pdf_url
        name = f"pdf/{book.isbn13 or book.pk}.pdf"
        zf.writestr(name, data)
        return name
    return book.pdf_url


def build_export(books, with_pdf=True):
    """Return a file object (positioned at 0) containing the ZIP."""
    tmp = tempfile.SpooledTemporaryFile(max_size=50 * 1024 * 1024)
    text = io.StringIO()
    w = csv.writer(text, delimiter=";")
    w.writerow(HEADERS)
    records, isbns = [], []
    with zipfile.ZipFile(tmp, "w", zipfile.ZIP_DEFLATED) as zf:
        for b in books.select_related("publisher").prefetch_related("authors", "genres__parent"):
            front = _add_image(zf, b, b.cover_image, "front")
            back = _add_image(zf, b, b.back_cover_image, "back")
            pdf = _add_pdf(zf, b, with_pdf)
            records.append(marc.record_fields(b, pdf, front, back))
            isbns.append(b.isbn13)
            w.writerow([
                b.title, b.subtitle,
                " | ".join(a.name for a in b.authors.all()),
                b.statement_of_responsibility, b.edition,
                b.publisher.name if b.publisher else "",
                b.publisher.place if b.publisher else "",
                b.publication_year or "", b.extent, b.page_count or "",
                b.isbn13, b.isbn10,
                b.get_age_category_display() if b.age_category else "",
                b.language,
                " | ".join(_topics(b)),
                b.description, b.get_medium_display(),
                b.branch, b.shelf_location, b.location2, b.media_group_display,
                b.get_loan_status_display(),
                b.quantity_in_stock, b.inventory_number,
                b.price if b.price is not None else "",
                front, back, pdf,
            ])
        zf.writestr("buecher.mrc", b"".join(marc.to_mrc(r) for r in records))
        zf.writestr("buecher-marcxml.xml", marc.to_xml(records))
        zf.writestr("isbn-liste.txt", "\n".join(isbns) + "\n")
        zf.writestr("buecher.csv", "\ufeff" + text.getvalue())
        zf.writestr("LIESMICH.txt", README)
    tmp.seek(0)
    return tmp
