from datetime import timedelta

from django.conf import settings
from django.db import models
from django.db.models import Q
from django.utils import timezone


def default_due():
    """Loan period in days; override with BOOK_LOAN_DAYS in settings.py."""
    return timezone.now() + timedelta(days=getattr(settings, "BOOK_LOAN_DAYS", 28))


class BookLoan(models.Model):
    """Same fields as a component loan: von / bis (voraussichtlich) / Leihnehmer /
    erfasst von / Rückgabedatum."""

    book = models.ForeignKey("books.Book", on_delete=models.CASCADE, related_name="loans")
    quantity = models.PositiveSmallIntegerField(default=1)
    borrower = models.ForeignKey(  # "an" / Leihnehmer
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="book_loans"
    )
    recorded_by = models.ForeignKey(  # "durch" / Erfasst von
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="recorded_book_loans"
    )
    borrower_name = models.CharField("Leihnehmer", max_length=150, blank=True)  # wie bei den Komponenten
    borrower_email = models.EmailField("Leihnehmer E-Mail", blank=True)
    borrowed_at = models.DateTimeField(default=timezone.now)  # von / ausgeliehen am
    due_at = models.DateTimeField(default=default_due)  # voraussichtliche Rückgabe
    returned_at = models.DateTimeField(null=True, blank=True)  # Rückgabedatum

    class Meta:
        ordering = ["-borrowed_at"]
        constraints = [
            models.UniqueConstraint(
                fields=["borrower", "book"],
                condition=Q(returned_at__isnull=True),
                name="one_open_loan_per_borrower_and_book",
            )
        ]

    def __str__(self):
        return f"{self.quantity}x {self.book} an {self.borrower}"

    @property
    def borrower_label(self):
        """Name des Leihnehmers: eingetragener Name, sonst Name des Benutzerkontos."""
        return self.borrower_name or self.borrower.get_full_name() or self.borrower.get_username()

    @property
    def borrower_contact(self):
        """E-Mail-Adresse des Leihnehmers: eingetragene, sonst die des Benutzerkontos."""
        return self.borrower_email or getattr(self.borrower, "email", "") or ""

    @property
    def is_returned(self):
        return self.returned_at is not None

    @property
    def is_overdue(self):
        return self.returned_at is None and self.due_at < timezone.now()
