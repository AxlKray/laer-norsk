from django.urls import path

from .views import BookDetailView, add_tag, toggle_favorite, book_pdf_thumb, delete_book, pdf_delete, pdf_rename, pdf_upload, BookListView, add_comment, book_pdf, export_books, import_review, import_start, recent_books

app_name = "books"
urlpatterns = [
    path("", BookListView.as_view(), name="list"),
    path("neueste/", recent_books, name="recent"),
    path("export/", export_books, name="export"),
    path("import/", import_start, name="import"),
    path("import/<int:pk>/", import_review, name="import_review"),
    path("<int:pk>/", BookDetailView.as_view(), name="detail"),
    path("<int:pk>/pdf/", book_pdf, name="pdf"),
    path("<int:pk>/loeschen/", delete_book, name="delete"),
    path("<int:pk>/pdf/vorschau/", book_pdf_thumb, name="pdf_thumb"),
    path("<int:pk>/pdf/hochladen/", pdf_upload, name="pdf_upload"),
    path("<int:pk>/pdf/umbenennen/", pdf_rename, name="pdf_rename"),
    path("<int:pk>/pdf/loeschen/", pdf_delete, name="pdf_delete"),
    path("<int:pk>/tag/", add_tag, name="tag"),
    path("<int:pk>/favorit/", toggle_favorite, name="favorite"),
    path("<int:pk>/kommentar/", add_comment, name="comment"),
]
