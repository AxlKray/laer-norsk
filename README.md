# Für die IT: Kurzanleitung (Deutsch)

**Zieladresse: https://raemilab.ch/book/** – alle Links im Modul sind per `{% url %}` erzeugt (keine fest eingetragenen Pfade). Es genügt also das Präfix `book/` in der Haupt-`urls.py`. Falls die Seite hinter einem Proxy/Unterordner läuft: `FORCE_SCRIPT_NAME = "/book"` nur setzen, wenn der Webserver den Präfix abschneidet; sonst nicht. Prüfen: Login-Weiterleitung (`LOGIN_URL`), `STATIC_URL`/`MEDIA_URL` (PDF-Ordner bleibt privat, Zugriff nur über `/book/<id>/pdf/`) und `CSRF_TRUSTED_ORIGINS = ["https://raemilab.ch"]`.

## Login und drei Rollen

Das Modul hat **kein eigenes Login und keine eigene Benutzerverwaltung**. Es nutzt das normale Django-Login des raemilab-Projekts (`LOGIN_URL`, `AUTH_USER_MODEL`). Die Apps müssen dafür im **selben Django-Projekt** laufen wie raemilab.

| | Gast (nicht angemeldet) | Benutzer (angemeldet) | Buchadmin |
|---|---|---|---|
| Bücherliste und Detailseite ansehen | ja | ja | ja |
| PDF öffnen | nein | ja | ja |
| Ausleihen, verlängern, zurückgeben (eigene) | nein, Hinweis «Zum Ausleihen anmelden» | ja | ja |
| Liste der Ausleihen (`/book/loan/`), Namen der Leihnehmer | nein | ja | ja |
| Kommentare sehen und schreiben | nein | ja | ja |
| Tags hinzufügen | nein | ja | ja |
| Buch bearbeiten | nein | nein | ja |
| Buch löschen / entsorgen | nein | nein | ja |
| Import, Export | nein | nein | ja |
| Ausleihen anderer erfassen/ändern, interne Notiz | nein | nein | ja |

**Buchadmin** = Mitglied der Gruppe «Buchadmin» (oder Superuser). Einrichten: `python manage.py setup_book_roles` legt die Gruppe mit allen nötigen Rechten an. Danach im Admin die gewünschten Personen dieser Gruppe zuordnen. Technisch gilt als Buchadmin, wer das Recht `books.change_book` hat (`books/permissions.py`). «Benutzer» ist jede angemeldete Person ohne diese Gruppe. Einstellung `BOOK_LOANS_VISIBLE_TO_ALL = False` zeigt die Leihnehmer nur noch Buchadmin.

## Setup in the existing project
1. Copy `books/` and `book_loans/` next to `manage.py`.
2. `settings.py`: `INSTALLED_APPS += ["books"]` and `"book_loans"`.
   Ensure `MEDIA_URL`/`MEDIA_ROOT` are set (cover images) and Pillow is installed
   (`pip install -r requirements.txt`).
3. Main `urls.py`: `path("book/", include("books.urls"))`
   (and, in development, serve MEDIA files).
4. Sidebar: add a "Bücher" entry linking to `{% url 'books:list' %}`.
5. `templates/books/book_list.html`: adjust the `{% extends %}` and block name to
   the site's base template; swap the plain markup for the site's CSS classes.
   Icons assume Font Awesome, which the site already seems to use.
6. `python manage.py makemigrations books book_loans` then `migrate`.

Each book has a detail page (`books:detail`) laid out like the Komponenten detail page: images on the left (front and back cover), code badge, title, then collapsible sections Beschreibung, Kommentare and Zusatzinformationen in two columns. Logged-in users can post comments there (`books:comment`); staff can hide comments in the admin. The "Reservieren" button comes with step 2.

New/edit/delete currently link to the Django admin. Replace with the site's own
forms if preferred. Comments are managed per book in the admin (hide with
"is visible"); showing and posting comments on a public book page still needs a
view and form.

## Example data
`books/fixtures/physik_beispiele.json` contains seven physics books (Halliday, Giancoli,
Tipler, Formeln und Tafeln, Formeln/Tabellen/Begriffe, Fundamentum). Load it after
`migrate` with `python manage.py loaddata physik_beispiele`. Library fields (branch,
location, media group, status), quantities and age categories are sample values.

Books have a **Medium** field (Analog, Digital, Analog + digital); the list can be filtered by it and the export has a Medium column.

Analog titles show location fields (signature, branch, location, stock); digital titles
show a PDF upload and/or PDF link instead (the admin form switches automatically with the
Medium dropdown, via `static/books/admin_medium.js`). PDFs open through a login-protected
view (`books:pdf`); keep the `pdfs/` media folder out of public web-server access, otherwise
anyone with the file address can download it. Check copyright before uploading PDFs.

## Export for the school library (MARC21 for winMedio and others)
On the list page, staff tick books (none ticked = all books of the current search) and click
"Export für Schulbibliothek". The ZIP contains:
- `buecher.mrc`: catalogue data as **MARC21** (binary, UTF-8), the standard exchange format of library
  software. winMedio lists MARC21 among its interfaces (Predata AG product pages). Local fields:
  852 = Zweigstelle / Standort 2 / Signatur / Inventar / Status (one per copy), 990 = Mediengruppe /
  Status / Medium / Format / Anzahl, 856 = PDF and cover images, 590 = internal notes (staff only).
  Every book field is exported: ISBN-13/10 (020, with binding and price), language (041), authors
  (100/110/700/710), title/subtitle/responsibility (245), edition (250), publisher/place/year (264),
  extent and page count (300/500), carrier (336-338), description (520), age category (521),
  Thema/Unterthema (650 with subdivision and flat 653).
- `buecher-marcxml.xml`: the same records as MARCXML (readable, for checking).
- `isbn-liste.txt`: one ISBN per line, for winMedio's automatic data takeover from online sources.
- `buecher.csv` (UTF-8 with BOM, semicolon): all fields as a table.
- `covers/` and `pdf/` folders; the CSV columns name the paths.
**Not verified:** which file and which field mapping winMedio's import wants was not found in public
documentation. Send a small test file (3 to 5 titles) to the vendor (Predata AG) or try it in a test
database first; the 852/990 mapping is the part most likely to need adjusting. Code: `books/marc.py`,
`books/export.py`.

## Standard topics
`python manage.py seed_topics` creates Physik with sub-topics (Mechanik, Strömung, Akustik, Optik,
Wärmelehre, Energie, Elektrizität, Magnetismus, Atom-, Kern-, Quantenphysik, Relativitätstheorie,
Astronomie, Didaktik, Geschichte, Aufgaben, Praktikum, Experimente, Lehrbuch, Formelsammlung, ...) plus
Mathematik, Chemie, Informatik, Biologie. Safe to run again; edit and extend the list in
`books/management/commands/seed_topics.py` or in the admin (Genre > "parent").

## Import (staff): `/book/import/`
Three separate drop zones: Vorderseite, Rückseite (JPG/PNG) and PDF. Any combination works and all
given files are analysed together (barcodes on every image and PDF page, ISBN in the PDF text, printed
ISBN via text recognition, PDF properties as a fallback). The ISBN is looked up at DNB, Google Books and
Open Library, then a review page lets you correct and complete every field before the book is created.
Needs `PyMuPDF` and `zxing-cpp` (see requirements.txt); `pytesseract` + tesseract is optional. The server
needs internet access for the lookup.

## Lending (app `book_loans`)
Books are lent like components: the loan has the same fields as the component loan
(von, bis voraussichtlich, Leihnehmer, erfasst von, Rückgabedatum, Menge) and the pages copy
the layout of "Liste aller Ausleihen" and "Ausleihe bearbeiten".
1. `INSTALLED_APPS += ["book_loans"]`, `path("book/loan/", include("book_loans.urls"))`,
   then `makemigrations books book_loans` and `migrate`.
2. Optional `settings.py`: `BOOK_LOAN_DAYS = 28` (loan period) and
   Die Bücher-Ausleihe ist eigenständig (`/book/loan/`) und hat keine Verbindung zur Komponenten-Ausleihe.
3. Detail page: the **Ausleihen** button lends the book to the logged-in user at once
   (durch = an = the user, like the component loan). Staff can create loans for others in the
   admin. Return: edit the loan and enter the Rückgabedatum (staff or the borrower).
4. List page: the **Ausleihen** link opens the book loan list (staff: all loans, others: own).
5. The detail page marks a borrowed book ("Ausgeliehen: Name, bis ...", red when overdue) and
   has a table "Letzte Ausleihen" (last 10, eye icon opens the loan; link to all loans of the
   book). Borrower names are shown to all logged-in users; set
   `BOOK_LOANS_VISIBLE_TO_ALL = False` to restrict names and loan lists to staff.
6. Availability = stock minus open loans; one open loan per person and book; digital-only
   books cannot be lent.

### Merging with the existing component loans
`book_loans` is a separate table with the same shape. For one single list/edit page, the
existing loan model can get a nullable `book` foreign key next to its component key (exactly
one of the two set), and the existing list and edit views can show `loan.book or loan.component`.
That depends on the existing code; see the notes of the developer.

## Production notes
SQLite by default; use PostgreSQL in production. Serve media via the web server.
