from django.urls import path

from .views import borrow_book, extend_loan, loan_edit, loan_list

app_name = "book_loans"
urlpatterns = [
    path("", loan_list, name="list"),
    path("buch/<int:pk>/ausleihen/", borrow_book, name="borrow"),
    path("<int:pk>/", loan_edit, name="edit"),
    path("<int:pk>/verlaengern/", extend_loan, name="extend"),
]
