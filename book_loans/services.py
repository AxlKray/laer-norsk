"""Lending logic. Views and the admin call these functions."""
from django.core.exceptions import ValidationError
from django.db import transaction
from django.db.models import Sum
from django.utils import timezone

from books.models import Book

from .models import BookLoan


def open_loans(book):
    return BookLoan.objects.filter(book=book, returned_at__isnull=True)


def available_copies(book):
    taken = open_loans(book).aggregate(n=Sum("quantity"))["n"] or 0
    return max(book.quantity_in_stock - taken, 0)


def borrow(book, borrower, recorded_by=None, quantity=1):
    """Lend a book. Self-service: recorded_by defaults to the borrower."""
    with transaction.atomic():
        book = Book.objects.select_for_update().get(pk=book.pk)  # prevents double booking
        if not book.is_physical:
            raise ValidationError("Dieses Buch ist nur digital verfügbar.")
        if book.is_disposed:
            raise ValidationError("Dieses Buch wurde entsorgt und kann nicht ausgeliehen werden.")
        if book.loan_status == Book.LoanStatus.REFERENCE:
            raise ValidationError("Dieses Buch ist ein Präsenzexemplar und kann nicht ausgeliehen werden.")
        if open_loans(book).filter(borrower=borrower).exists():
            raise ValidationError("Du hast dieses Buch bereits ausgeliehen.")
        if available_copies(book) < quantity:
            raise ValidationError("Zurzeit ist kein Exemplar verfügbar.")
        return BookLoan.objects.create(
            book=book, borrower=borrower, recorded_by=recorded_by or borrower, quantity=quantity,
            borrower_name=borrower.get_full_name() or borrower.get_username(),
            borrower_email=getattr(borrower, "email", "") or "",
        )


def give_back(loan, when=None):
    if loan.returned_at:
        raise ValidationError("Diese Ausleihe ist bereits zurückgegeben.")
    loan.returned_at = when or timezone.now()
    loan.save(update_fields=["returned_at"])
