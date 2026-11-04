"""Drei Rollen für das Bücher-Modul (Login und Benutzer kommen vom Hauptprojekt):

* Gast (nicht angemeldet): Listen und Detailseiten ansehen. Kein PDF, keine Ausleihe,
  keine Namen von Leihnehmern.
* Benutzer (angemeldet): alles ansehen, PDF öffnen, ausleihen, verlängern, zurückgeben, kommentieren.
* Buchadmin: zusätzlich bearbeiten, Tags, löschen/entsorgen, Import/Export, Ausleihen anderer verwalten.
  Buchadmin = Mitglied der Gruppe "Buchadmin" (siehe `manage.py setup_book_roles`) oder Superuser.
"""
from functools import wraps

from django.contrib.auth.views import redirect_to_login
from django.core.exceptions import PermissionDenied

BOOK_ADMIN_PERM = "books.change_book"


def is_book_admin(user):
    return bool(user.is_authenticated and (user.is_superuser or user.has_perm(BOOK_ADMIN_PERM)))


def book_admin_required(view):
    @wraps(view)
    def wrapper(request, *args, **kwargs):
        if not request.user.is_authenticated:
            return redirect_to_login(request.get_full_path())
        if not is_book_admin(request.user):
            raise PermissionDenied
        return view(request, *args, **kwargs)
    return wrapper
