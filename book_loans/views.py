from datetime import timedelta

from django.db.models.functions import Coalesce
from django import forms
from django.conf import settings
from django.contrib import messages
from books.permissions import is_book_admin
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied, ValidationError
from django.core.paginator import Paginator
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import NoReverseMatch, reverse
from django.utils import timezone
from django.views.decorators.http import require_POST

from books.models import Book

from . import services
from .models import BookLoan

DT = "%Y-%m-%dT%H:%M"


class ReturnForm(forms.ModelForm):
    returned_at = forms.DateTimeField(
        required=True, input_formats=[DT],
        widget=forms.DateTimeInput(attrs={"type": "datetime-local"}, format=DT),
        label="Rückgabedatum",
    )

    class Meta:
        model = BookLoan
        fields = ["borrower_name", "borrower_email", "returned_at"]

    def __init__(self, *args, editable_borrower=False, **kwargs):
        super().__init__(*args, **kwargs)
        if not editable_borrower:  # nur Buchadmin ändert Leihnehmer und E-Mail
            del self.fields["borrower_name"], self.fields["borrower_email"]
        else:  # Speichern nur mit Leihnehmer, E-Mail und Rückgabedatum
            self.fields["borrower_name"].required = True
            self.fields["borrower_email"].required = True

    def clean_returned_at(self):
        value = self.cleaned_data["returned_at"]
        if value and value < self.instance.borrowed_at:
            raise forms.ValidationError("Das Rückgabedatum liegt vor dem Ausleihdatum.")
        return value


@login_required
@require_POST
def borrow_book(request, pk):
    book = get_object_or_404(Book, pk=pk)
    try:
        loan = services.borrow(book, request.user)
        messages.success(request, f"«{book.title}» ausgeliehen, Rückgabe bis {loan.due_at:%d.%m.%Y}.")
    except ValidationError as e:
        messages.error(request, " ".join(e.messages))
    return redirect(book.get_absolute_url())


@login_required
@require_POST
def extend_loan(request, pk):
    """Leihfrist um die normale Ausleihdauer verlängern (Leihnehmer oder Mitarbeitende)."""
    loan = get_object_or_404(BookLoan, pk=pk, returned_at__isnull=True)
    if not (is_book_admin(request.user) or loan.borrower_id == request.user.id):
        raise PermissionDenied
    loan.due_at = max(loan.due_at, timezone.now()) + timedelta(days=getattr(settings, "BOOK_LOAN_DAYS", 28))
    loan.save(update_fields=["due_at"])
    messages.success(request, f"«{loan.book.title}» verlängert, Rückgabe bis {loan.due_at:%d.%m.%Y}.")
    return redirect(loan.book.get_absolute_url())


@login_required
def loan_list(request):
    """'Liste aller Ausleihen' for books. Everyone sees all loans unless
    BOOK_LOANS_VISIBLE_TO_ALL = False in settings (then non-staff see only their own)."""
    qs = BookLoan.objects.select_related("book", "borrower", "recorded_by").prefetch_related("book__authors")
    if not (is_book_admin(request.user) or getattr(settings, "BOOK_LOANS_VISIBLE_TO_ALL", True)):
        qs = qs.filter(borrower=request.user)
    filter_book = None
    book_id = request.GET.get("book", "")
    if book_id.isdigit():  # e.g. "all loans of this book" from the detail page
        filter_book = Book.objects.filter(pk=book_id).first()
        qs = qs.filter(book_id=book_id)
    show = request.GET.get("status", "open")
    if show == "open":
        qs = qs.filter(returned_at__isnull=True)
    # sortiert nach dem angezeigten «Bis»-Datum (Rückgabedatum bzw. voraussichtliche Rückgabe), älteste zuerst
    qs = qs.annotate(bis=Coalesce("returned_at", "due_at")).order_by("bis", "pk")
    paginator = Paginator(qs, 25)
    page = paginator.get_page(request.GET.get("page"))
    return render(request, "book_loans/loan_list.html", {
        "page_obj": page, "paginator": paginator, "show": show,
        "elided": paginator.get_elided_page_range(page.number),
        "filter_book": filter_book, "extra": f"&book={filter_book.pk}" if filter_book else "",
    })


@login_required
def loan_edit(request, pk):
    """'Ausleihe bearbeiten': set the Rückgabedatum."""
    loan = get_object_or_404(BookLoan.objects.select_related("book", "borrower", "recorded_by"), pk=pk)
    if not (is_book_admin(request.user) or loan.borrower_id == request.user.id):
        raise PermissionDenied
    form = ReturnForm(request.POST or None, instance=loan, editable_borrower=is_book_admin(request.user))
    if request.method == "POST" and form.is_valid():
        form.save()
        messages.success(request, "Gespeichert.")
        return redirect("book_loans:list")
    return render(request, "book_loans/loan_edit.html", {"loan": loan, "form": form})
