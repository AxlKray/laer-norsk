from django import forms
from django.contrib import admin

from django.utils import timezone

from .models import Author, Book, Comment, Favorite, Genre, Publisher


class CommentInline(admin.TabularInline):
    model = Comment
    extra = 0
    fields = ("user", "text", "rating", "is_visible", "created_at")
    readonly_fields = ("created_at",)


class BookAdminForm(forms.ModelForm):
    """Medium als zwei Kästchen: Analog (gedrucktes Buch) und/oder Digital (E-Book/PDF). Beide sind möglich."""

    medium = forms.MultipleChoiceField(
        label="Medium", choices=[("analog", "Analog (gedrucktes Buch)"), ("digital", "Digital (E-Book/PDF)")],
        widget=forms.CheckboxSelectMultiple, help_text="Beides ankreuzen, wenn es das Buch gedruckt und als PDF gibt.",
    )

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        m = self.instance.medium if self.instance and self.instance.pk else "analog"
        self.initial["medium"] = ["analog", "digital"] if m == "both" else [m]

    def clean_medium(self):
        v = set(self.cleaned_data["medium"])
        return "both" if v == {"analog", "digital"} else (v.pop() if v else "analog")

    class Meta:
        model = Book
        exclude = ("format",)  # Format (Taschenbuch/Hardcover) entfällt: es zählt nur das Medium


@admin.register(Book)
class BookAdmin(admin.ModelAdmin):
    form = BookAdminForm
    list_display = ("title", "inventory_number", "shelf_location", "isbn13", "publisher", "publication_year", "medium", "quantity_in_stock")
    list_filter = ("is_deleted", "is_disposed", "medium", "age_category", "branch", "language", "genres", "publisher")
    search_fields = ("title", "inventory_number", "shelf_location", "subtitle", "isbn13", "isbn10", "authors__name")
    filter_horizontal = ("authors", "genres")
    inlines = [CommentInline]
    actions = ["restore_books"]

    def has_delete_permission(self, request, obj=None):
        # Endgültiges Löschen nur für Superuser (IT); normale "Löschen"-Funktion blendet nur aus.
        return request.user.is_superuser

    @admin.action(description="Gelöschte Bücher wiederherstellen")
    def restore_books(self, request, queryset):
        n = queryset.filter(is_deleted=True).update(is_deleted=False, deleted_at=None, deleted_by=None)
        self.message_user(request, f"{n} Buch/Bücher wiederhergestellt.")

    def formfield_for_dbfield(self, db_field, request, **kwargs):
        field = super().formfield_for_dbfield(db_field, request, **kwargs)
        if db_field.name == "language":
            from .forms import LanguageWidget
            field.widget = LanguageWidget()
        return field

    class Media:
        js = ("books/admin_medium.js",)


admin.site.register([Author, Publisher, Genre])


@admin.register(Favorite)
class FavoriteAdmin(admin.ModelAdmin):
    list_display = ("user", "book", "created_at")
    search_fields = ("user__username", "book__title")
