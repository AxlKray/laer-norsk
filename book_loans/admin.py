from django.contrib import admin

from .models import BookLoan


@admin.register(BookLoan)
class BookLoanAdmin(admin.ModelAdmin):
    list_display = ("book", "borrower", "borrower_name", "recorded_by", "borrowed_at", "due_at", "returned_at")
    list_filter = ("returned_at",)
    search_fields = ("book__title", "book__isbn13", "borrower__username", "borrower__last_name")
    date_hierarchy = "borrowed_at"
