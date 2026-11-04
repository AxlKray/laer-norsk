import re
from datetime import date

from django.apps import apps
from django.conf import settings
from django.contrib import messages
from django.contrib.auth.decorators import login_required, user_passes_test
from django.contrib.auth.mixins import LoginRequiredMixin
from django.core.files.base import ContentFile
from django.db import transaction
from django.db.models import Count, Min, Q
from django.forms import ModelForm
from django.http import FileResponse, Http404
from django.utils import timezone
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_POST
from django.views.generic import DetailView, ListView

from . import importer
from .export import build_export
from .permissions import book_admin_required, is_book_admin
from .forms import ImportReviewForm, UploadForm
from .models import Author, Book, Comment, Favorite, Genre, ImportDraft, Publisher

SORTS = {"inventar": "inventory_number", "code": "shelf_location", "name": "title", "isbn": "isbn13", "author": "sort_author", "topic": "sort_topic"}

# (param, Font Awesome icon, title). Value "1" = yes, "0" = no, empty = any.
TRISTATE = [
    ("cover", "fas fa-image", "Mit Titelbild"),
    ("comments", "fas fa-comment", "Mit Kommentaren"),
    ("available", "fas fa-ban", "Verfügbar (Anzahl > 0)"),
]

staff_required = book_admin_required  # Buchadmin (Gruppe "Buchadmin"), siehe permissions.py


def filtered_books(g, user=None):
    """Apply the list-page filters (a QueryDict or dict) and sorting."""
    qs = Book.objects.prefetch_related("authors", "genres__parent").annotate(
        comment_total=Count("comments", filter=Q(comments__is_visible=True), distinct=True)
    )
    if g.get("code"):
        qs = qs.filter(shelf_location__istartswith=g["code"])
    if g.get("isbn"):
        qs = qs.filter(isbn13__startswith=g["isbn"].replace("-", "").replace(" ", ""))
    if g.get("author", "").isdigit():
        qs = qs.filter(authors__pk=g["author"])
    if g.get("genre", "").isdigit():
        qs = qs.filter(Q(genres__pk=g["genre"]) | Q(genres__parent_id=g["genre"]))  # incl. sub-topics
    if g.get("medium") in ("analog", "digital"):
        # "analog + digital" titles show up under both filters
        qs = qs.filter(medium__in=[g["medium"], "both"])
    if g.get("loaned") == "1" and apps.is_installed("book_loans"):  # currently lent out
        from book_loans.models import BookLoan

        qs = qs.filter(pk__in=BookLoan.objects.filter(returned_at__isnull=True).values("book_id"))
    # Entweder "noch vorhanden" (Standard) oder "entsorgt", nie beides gemischt.
    if g.get("stock") == "disposed":
        qs = qs.filter(is_disposed=True)
    else:
        qs = qs.filter(is_disposed=False)
    if g.get("fav") == "1" and user is not None and user.is_authenticated:  # nur meine Favoriten
        qs = qs.filter(pk__in=Favorite.objects.filter(user=user).values("book_id"))
    if g.get("language"):
        qs = qs.filter(language=g["language"])
    if g.get("q"):
        q = g["q"]
        qs = qs.filter(
            Q(title__icontains=q) | Q(subtitle__icontains=q)
            | Q(authors__name__icontains=q) | Q(description__icontains=q)
        )
    if g.get("cover") == "1":
        qs = qs.exclude(cover_image="")
    elif g.get("cover") == "0":
        qs = qs.filter(cover_image="")
    if g.get("comments") == "1":
        qs = qs.filter(comment_total__gt=0)
    elif g.get("comments") == "0":
        qs = qs.filter(comment_total=0)
    if g.get("available") == "1":  # digital titles are always available
        qs = qs.filter(Q(quantity_in_stock__gt=0) | Q(medium="digital"))
    elif g.get("available") == "0":
        qs = qs.filter(quantity_in_stock=0).exclude(medium="digital")

    sort = g.get("sort", "name")
    field = SORTS.get(sort.lstrip("-"), "title")
    if field == "sort_author":
        qs = qs.annotate(sort_author=Min("authors__name"))
    elif field == "sort_topic":
        qs = qs.annotate(sort_topic=Min("genres__name", filter=Q(genres__is_tag=False)))
    return qs.order_by(("-" if sort.startswith("-") else "") + field, "pk").distinct()


class BookListView(ListView):  # öffentlich: auch Gäste sehen die Liste
    model = Book
    paginate_by = 25
    template_name = "books/book_list.html"

    def get_queryset(self):
        return filtered_books(self.request.GET, self.request.user)

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        g = self.request.GET.copy()
        g.pop("page", None)
        ctx["querystring"] = g.urlencode()
        author_id = self.request.GET.get("author", "")
        ctx["active_author"] = Author.objects.filter(pk=author_id).first() if author_id.isdigit() else None
        no_author = g.copy()
        no_author.pop("author", None)
        ctx["qs_no_author"] = no_author.urlencode()
        from .management.commands.seed_topics import ensure_topics
        ensure_topics()
        ctx["genres"] = sorted(Genre.objects.filter(is_tag=False).select_related("parent"), key=lambda g: ((g.parent.name if g.parent_id else g.name).lower(), g.parent_id is not None, g.name.lower()))
        base = ["de", "en", "fr"]
        others = [l for l in Book.objects.order_by("language").values_list("language", flat=True).distinct() if l and l not in base]
        ctx["languages"] = base + others
        ctx["tristate"] = [
            {"name": n, "icon": i, "title": t, "value": self.request.GET.get(n, "")}
            for n, i, t in TRISTATE
        ]
        ctx["sort"] = self.request.GET.get("sort", "name")
        nos = self.request.GET.copy()
        nos.pop("sort", None)
        nos.pop("page", None)
        ctx["qs_nosort"] = nos.urlencode()
        ctx["loans_enabled"] = apps.is_installed("book_loans")
        ctx["loaned_ids"] = set()
        if ctx["loans_enabled"]:
            from book_loans.models import BookLoan

            ctx["loaned_ids"] = set(
                BookLoan.objects.filter(book__in=ctx["object_list"], returned_at__isnull=True).values_list("book_id", flat=True)
            )
        ctx["elided"] = ctx["paginator"].get_elided_page_range(ctx["page_obj"].number)
        return ctx


@staff_required
@require_POST
def export_books(request):
    """ZIP export. Selected rows (ids) if any, otherwise every book matching the
    current filters (the filters travel in the query string of the form action).
    Exportiert werden nur vorhandene analoge Bücher."""
    ids = [i for i in request.POST.getlist("ids") if i.isdigit()]
    books = Book.objects.filter(pk__in=ids) if ids else filtered_books(request.GET, request.user)
    # Nur vorhandene gedruckte Bücher: Medium analog oder analog + digital, nicht entsorgt (gelöschte fehlen ohnehin)
    books = books.filter(medium__in=[Book.Medium.ANALOG, Book.Medium.BOTH], is_disposed=False)
    return FileResponse(
        build_export(books, with_pdf=request.POST.get("with_pdf") == "1"),
        as_attachment=True,
        filename=f"buecher-export-{date.today():%Y%m%d}.zip",
        content_type="application/zip",
    )


# ---- detail page ------------------------------------------------------------
class CommentForm(ModelForm):
    class Meta:
        model = Comment
        fields = ["text", "rating"]


class BookDetailView(DetailView):  # öffentlich; PDF/Ausleihe nur angemeldet
    model = Book
    template_name = "books/book_detail.html"
    queryset = Book.objects.select_related("publisher").prefetch_related("authors", "genres__parent")

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx["topic_paths"] = self.object.topic_paths
        ctx["login_url"] = settings.LOGIN_URL
        ctx["is_favorite"] = self.request.user.is_authenticated and Favorite.objects.filter(user=self.request.user, book=self.object).exists()
        ctx["comments"] = self.object.comments.filter(is_visible=True).select_related("user") if self.request.user.is_authenticated else []
        ctx["comment_form"] = CommentForm()
        ctx["loans_enabled"] = apps.is_installed("book_loans")
        if ctx["loans_enabled"]:
            from book_loans import services
            from book_loans.models import BookLoan

            user = self.request.user
            open_loans = BookLoan.objects.filter(book=self.object, returned_at__isnull=True)
            mine = open_loans.filter(borrower=user).first() if user.is_authenticated else None
            free = services.available_copies(self.object)
            ctx["borrow"] = {
                "mine": mine,
                "available": free,
                "can_borrow": user.is_authenticated and mine is None and free > 0 and self.object.loan_status != "reference" and not self.object.is_disposed,
                "active_count": sum(loan.quantity for loan in open_loans),
            }
            # Wer hat das Buch? Nur für Angemeldete (Gäste sehen keine Namen),
            # bei BOOK_LOANS_VISIBLE_TO_ALL = False nur für Buchadmin.
            visible = user.is_authenticated and (getattr(settings, "BOOK_LOANS_VISIBLE_TO_ALL", True) or is_book_admin(user))
            all_loans = BookLoan.objects.filter(book=self.object)
            ctx["show_borrowers"] = visible
            ctx["open_loans"] = list(open_loans.select_related("borrower"))
            ctx["recent_loans"] = list(all_loans.select_related("borrower")[:10]) if visible else []
            ctx["loan_total"] = all_loans.count() if visible else 0
        return ctx


@login_required
def book_pdf(request, pk):
    """Open the PDF for logged-in users (uploaded file or external link)."""
    book = get_object_or_404(Book, pk=pk)
    if book.pdf_file:
        try:
            return FileResponse(book.pdf_file.open("rb"), content_type="application/pdf",
                                filename=(book.pdf_name if book.pdf_name.lower().endswith(".pdf") else (book.pdf_name + ".pdf" if book.pdf_name else f"{book.isbn13 or book.pk}.pdf")))
        except (OSError, ValueError):
            raise Http404("PDF file not found")
    if book.pdf_url:
        return redirect(book.pdf_url)
    raise Http404("No PDF for this book")


@login_required
def book_pdf_thumb(request, pk):
    """Kleine Vorschau (erste Seite) des PDF. Wird einmal erzeugt und im Medienordner zwischengespeichert."""
    import hashlib

    from django.core.files.base import ContentFile
    from django.core.files.storage import default_storage

    book = get_object_or_404(Book, pk=pk)
    if not book.pdf_file:
        raise Http404("Kein PDF")
    key = hashlib.sha1(book.pdf_file.name.encode()).hexdigest()[:10]
    name = f"pdfthumbs/{book.pk}_{key}.png"
    if not default_storage.exists(name):
        try:
            import fitz  # PyMuPDF

            book.pdf_file.open("rb")
            data = book.pdf_file.read()
            book.pdf_file.close()
            doc = fitz.open(stream=data, filetype="pdf")
            png = doc[0].get_pixmap(dpi=60).tobytes("png")
        except Exception:
            raise Http404("Vorschau nicht möglich")
        default_storage.save(name, ContentFile(png))
    response = FileResponse(default_storage.open(name, "rb"), content_type="image/png")
    response["Cache-Control"] = "private, max-age=86400"
    return response


@book_admin_required
@require_POST
def pdf_upload(request, pk):
    """Buchadmin: PDF hochladen (ersetzt ein vorhandenes PDF)."""
    book = get_object_or_404(Book, pk=pk)
    f = request.FILES.get("pdf")
    limit = getattr(settings, "BOOK_PDF_MAX_MB", 100) * 1024 * 1024
    if not f or not f.name.lower().endswith(".pdf"):
        messages.error(request, "Bitte eine PDF-Datei wählen.")
    elif f.size > limit:
        messages.error(request, f"Die Datei ist zu gross (maximal {limit // 1048576} MB).")
    elif f.read(5) != b"%PDF-":
        messages.error(request, "Das ist keine gültige PDF-Datei.")
    else:
        f.seek(0)
        old = book.pdf_file.name if book.pdf_file else ""
        if old:
            book.pdf_file.delete(save=False)
        book.pdf_file = f
        book.pdf_name = ""  # neuer Dateiname gilt
        book.save(update_fields=["pdf_file", "pdf_name"])
        messages.success(request, "PDF gespeichert.")
    return redirect(book.get_absolute_url())


@book_admin_required
@require_POST
def pdf_rename(request, pk):
    """Buchadmin: Anzeigename des PDF ändern (leer = Dateiname)."""
    book = get_object_or_404(Book, pk=pk)
    book.pdf_name = (request.POST.get("name") or "").strip()[:150]
    book.save(update_fields=["pdf_name"])
    messages.success(request, "Name gespeichert.")
    return redirect(book.get_absolute_url())


@book_admin_required
@require_POST
def pdf_delete(request, pk):
    """Buchadmin: PDF des Buches entfernen (Datei und Link)."""
    book = get_object_or_404(Book, pk=pk)
    if book.pdf_file:
        book.pdf_file.delete(save=False)
    book.pdf_file = ""
    book.pdf_url = ""
    book.pdf_name = ""
    book.save(update_fields=["pdf_file", "pdf_url", "pdf_name"])
    messages.success(request, "PDF gelöscht.")
    return redirect(book.get_absolute_url())


@login_required
@require_POST
def toggle_favorite(request, pk):
    """Buch als Favorit markieren oder die Markierung wieder entfernen (nur angemeldete Benutzer)."""
    book = get_object_or_404(Book, pk=pk)
    fav, created = Favorite.objects.get_or_create(user=request.user, book=book)
    if not created:
        fav.delete()
    return redirect(book.get_absolute_url())


@login_required
@require_POST
def add_tag(request, pk):
    """Angemeldete Benutzer: ein Tag (freies Schlagwort) zu einem Buch hinzufügen."""
    book = get_object_or_404(Book, pk=pk)
    name = (request.POST.get("tag") or "").strip()[:100]
    if request.method == "POST" and name:
        genre = Genre.objects.filter(name__iexact=name).first() or Genre.objects.create(name=name, is_tag=True)
        book.genres.add(genre)
    return redirect(book.get_absolute_url())


@login_required
@require_POST
def delete_book(request, pk):
    """Buch "löschen": nur als gelöscht markieren (unsichtbar, für die IT im Admin wiederherstellbar)."""
    book = get_object_or_404(Book, pk=pk)
    if not request.user.has_perm("books.delete_book"):
        raise Http404
    if apps.is_installed("book_loans"):
        from book_loans.models import BookLoan
        if BookLoan.objects.filter(book=book, returned_at__isnull=True).exists():
            messages.error(request, "Das Buch ist noch ausgeliehen und kann erst nach der Rückgabe gelöscht werden.")
            return redirect(book.get_absolute_url())
    if request.POST.get("action") == "dispose" and book.medium == Book.Medium.BOTH:
        # Papierbuch weg, digitale Version (PDF/E-Book) bleibt: Buch wird "nur digital".
        book.medium = Book.Medium.DIGITAL
        book.save(update_fields=["medium"])
        messages.success(request, f"Das Papierbuch von «{book.title}» wurde entsorgt. Die digitale Version bleibt erhalten.")
        return redirect("books:list")
    if request.POST.get("action") == "dispose" and book.is_physical:
        book.is_disposed, book.disposed_at = True, timezone.now()
        book.save(update_fields=["is_disposed", "disposed_at"])
        messages.success(request, f"«{book.title}» wurde als entsorgt markiert. Sichtbar mit dem Filter «Entsorgt».")
        return redirect("books:list")
    book.is_deleted, book.deleted_at, book.deleted_by = True, timezone.now(), request.user
    book.save(update_fields=["is_deleted", "deleted_at", "deleted_by"])
    messages.success(request, f"«{book.title}» wurde gelöscht. Die IT kann es bei Bedarf wiederherstellen.")
    return redirect("books:list")


@login_required
def add_comment(request, pk):
    book = get_object_or_404(Book, pk=pk)
    form = CommentForm(request.POST)
    if form.is_valid():
        comment = form.save(commit=False)
        comment.book, comment.user = book, request.user
        comment.save()
    return redirect(book.get_absolute_url() + "#kommentare")


# ---- import: cover images / PDF -> ISBN -> online data -> review -> create ------------
WIDE = {"title", "subtitle", "authors_text", "description", "statement_of_responsibility"}


def _bytes(f):
    if not f:
        return None
    with f.open("rb") as fh:
        return fh.read()


@staff_required
def import_start(request):
    form = UploadForm(request.POST or None, request.FILES or None)
    if request.method == "POST" and form.is_valid():
        d = form.cleaned_data
        draft = ImportDraft.objects.create(
            user=request.user, front=d["front"] or "", back=d["back"] or "", pdf=d["pdf"] or ""
        )
        if d["isbn"] and not any((d["front"], d["back"], d["pdf"])):  # ISBN only: no files to read
            data, found, errors = importer.lookup_isbn(d["isbn"])
            r = {"isbn": d["isbn"], "source": "von Hand eingegeben", "data": data, "sources": found,
                 "notes": errors or ([] if found else ["Zu dieser ISBN wurde online nichts gefunden."]), "cover_png": None}
        else:
            r = importer.analyse(_bytes(draft.front), _bytes(draft.back), _bytes(draft.pdf))  # all files together
            if d["isbn"] and not r["isbn"]:  # typed ISBN as a fallback when nothing was readable
                data, found, errors = importer.lookup_isbn(d["isbn"])
                r.update(isbn=d["isbn"], source="von Hand eingegeben", data=data, sources=found)
        draft.isbn, draft.isbn_source = r["isbn"], r["source"]
        draft.data, draft.sources, draft.notes = r["data"], r["sources"], r["notes"]
        if r["cover_png"] and not draft.front:
            draft.front.save("pdf-cover.png", ContentFile(r["cover_png"]), save=False)
        draft.save()
        return redirect("books:import_review", draft.pk)
    return render(request, "books/import_form.html", {"form": form})


def _initial(draft):
    d = draft.data
    own_images = bool(draft.back or (draft.front and not draft.front.name.endswith("pdf-cover.png")))
    medium = ("both" if own_images else "digital") if draft.pdf else "analog"
    wanted = {g.lower() for g in d.get("genres", [])}
    found = [g for g in Genre.objects.filter(is_tag=False).select_related("parent") if g.name.lower() in wanted]  # nur echte Themen
    sub_ids = [g.pk for g in found if g.parent_id]
    top = next((g.parent_id for g in found if g.parent_id), None) or next((g.pk for g in found if not g.parent_id), None)
    topic_names = {g.name.lower() for g in found}
    unknown = [g for g in d.get("genres", []) if g.lower() not in topic_names]  # alles andere: Schlagwörter (Tags)
    return {
        "title": d.get("title", ""), "subtitle": d.get("subtitle", ""), "isbn13": draft.isbn,
        "publication_year": d.get("year"), "edition": (d.get("edition") or "").strip().strip("[]").strip(), "extent": d.get("extent", ""),
        "page_count": d.get("pages"), "price": d.get("price") or None, "language": d.get("language") or "de", "description": d.get("description", ""),
        "authors_text": "\n".join(d.get("authors", [])), "topic": top, "subtopics": sub_ids, "genres_text": ", ".join(unknown),
        "publisher_name": d.get("publisher", ""), "publisher_place": d.get("place", ""),
        "statement_of_responsibility": d.get("responsibility", ""),  # Angabe wie auf dem Titelblatt (nur wenn die Quelle sie liefert)
        "analog": medium in ("analog", "both"), "digital": medium in ("digital", "both"),
        "branch": "MNG/RG Lehrer", "loan_status": "lending", "quantity_in_stock": 1,  # Import: vorhanden und ausleihbar (1 Exemplar); Präsenz wählbar
    }


def _duplicate(isbn):
    """Vorhandenes Buch mit dieser ISBN-13 (auch entsorgte; gelöschte zählen nicht)."""
    isbn = re.sub(r"[\s-]", "", isbn or "")
    return Book.objects.filter(isbn13=isbn).first() if isbn else None


def _release_deleted_isbn(isbn):
    """Die ISBN ist in der Datenbank eindeutig: ein gelöschtes Buch gibt sie frei (Original im internen Vermerk)."""
    isbn = re.sub(r"[\s-]", "", isbn or "")
    for old in Book.all_objects.filter(isbn13=isbn, is_deleted=True) if isbn else []:
        note = (old.internal_notes + "\n" if old.internal_notes else "") + "Ursprüngliche ISBN-13: " + isbn
        Book.all_objects.filter(pk=old.pk).update(isbn13="DEL%d" % old.pk, internal_notes=note)


@staff_required
def import_review(request, pk):
    from .management.commands.seed_topics import ensure_topics
    ensure_topics()
    draft = get_object_or_404(ImportDraft, pk=pk, user=request.user)
    if request.method == "POST":
        if "cancel" in request.POST:
            draft.discard()
            return redirect("books:list")
        post = request.POST.copy()
        post["isbn13"] = re.sub(r"[\s-]", "", post.get("isbn13", ""))
        if "lookup" in request.POST:  # ISBN typed in by hand: search again
            raw = post["isbn13"].upper()
            isbn = raw if importer.isbn13_valid(raw) else (importer.isbn10_to_13(raw) if importer.isbn10_valid(raw) else "")
            if isbn:
                data, found, errors = importer.lookup_isbn(isbn)
                draft.isbn, draft.isbn_source, draft.data, draft.sources = isbn, "von Hand eingegeben", data, found
                draft.notes = errors or ([] if found else ["Zu dieser ISBN wurde online nichts gefunden."])
            else:
                draft.notes = ["Das ist keine gültige ISBN."]
            draft.save()
            return redirect("books:import_review", draft.pk)
        if "attach_pdf" in request.POST:  # same ISBN already in the catalogue: add the PDF to that book
            dup = _duplicate(draft.isbn)
            if dup and draft.pdf and not dup.pdf_file:
                dup.pdf_file.save(draft.pdf.name.split("/")[-1], ContentFile(_bytes(draft.pdf)), save=False)
                if dup.medium == Book.Medium.ANALOG:
                    dup.medium = Book.Medium.BOTH
                dup.save()
                draft.discard()
                return redirect(dup.get_absolute_url())
            return redirect("books:import_review", draft.pk)
        if _duplicate(post["isbn13"]):  # never create a second entry with the same ISBN
            form = ImportReviewForm(post)
            form.is_valid()
            return render(request, "books/import_review.html", {"form": form, "draft": draft, "existing": _duplicate(post["isbn13"]), "wide": WIDE})
        _release_deleted_isbn(post["isbn13"])
        form = ImportReviewForm(post)
        if form.is_valid():
            book = _create_book(form, draft)
            return redirect(book.get_absolute_url())
    else:
        form = ImportReviewForm(initial=_initial(draft))
    existing = _duplicate(draft.isbn)
    return render(request, "books/import_review.html", {"form": form, "draft": draft, "existing": existing, "wide": WIDE})


@transaction.atomic
def _create_book(form, draft):
    book = form.save(commit=False)
    for field, src in (("cover_image", draft.front), ("back_cover_image", draft.back), ("pdf_file", draft.pdf)):
        if src:
            getattr(book, field).save(src.name.split("/")[-1], ContentFile(_bytes(src)), save=False)
    name = form.cleaned_data["publisher_name"].strip()
    if name:
        publisher, _ = Publisher.objects.get_or_create(name=name)
        if form.cleaned_data["publisher_place"] and not publisher.place:
            publisher.place = form.cleaned_data["publisher_place"].strip()
            publisher.save()
        book.publisher = publisher
    book.save()
    book.authors.set([Author.objects.get_or_create(name=n.strip())[0]
                      for n in form.cleaned_data["authors_text"].splitlines() if n.strip()])
    new = [Genre.objects.get_or_create(name=n.strip(), defaults={"is_tag": True})[0]
           for n in form.cleaned_data["genres_text"].split(",") if n.strip()]
    topic = form.cleaned_data["topic"]
    subs = list(form.cleaned_data["subtopics"])
    if subs and not topic:  # sub-topics without a chosen topic: take their parent
        topic = subs[0].parent
    book.genres.set(([topic] if topic else []) + subs + new)
    draft.discard()
    return book


def recent_books(request):
    """«Neueste 20 Bücher»: die zuletzt erfassten, noch vorhandenen Bücher mit Rang, Bild und Titel (öffentlich)."""
    books = Book.objects.filter(is_disposed=False).prefetch_related("authors").order_by("-created_at", "-pk")[:20]
    return render(request, "books/recent_books.html", {"books": books})
