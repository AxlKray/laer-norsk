"""MARC21 output for library software (winMedio and others): binary ISO 2709 (.mrc) and MARCXML.

Fields follow common RDA/ISBD practice for monographs. Local fields carry what MARC has no standard
place for: 852 = Zweigstelle/Standort/Signatur/Inventar, 990 = Mediengruppe/Status/Medium.
No Django imports, so it is easy to test."""
from datetime import datetime
from xml.sax.saxutils import escape

FT, RT, SF = "\x1e", "\x1d", "\x1f"
LANG3 = {"de": "ger", "en": "eng", "fr": "fre", "it": "ita", "no": "nor", "nb": "nor", "es": "spa",
         "la": "lat", "nl": "dut", "pt": "por", "ru": "rus"}


def _c(s):
    return " ".join(str(s or "").split())


def _sorted(fields):
    return sorted(fields, key=lambda f: f[0])  # stable: repeated tags keep their order


def record_fields(book, pdf_ref="", front_ref="", back_ref=""):
    """Fields of one book: ('001', data) or (tag, ind1, ind2, [(code, value), ...])."""
    authors = [_c(a.name) for a in book.authors.all() if _c(a.name)]
    year = book.publication_year
    created = getattr(book, "created_at", None) or datetime.now()
    updated = getattr(book, "updated_at", None) or created
    lang = LANG3.get((book.language or "")[:2].lower(), "und")
    pub = _c(book.publisher.name) if book.publisher else ""
    place = _c(book.publisher.place) if book.publisher else ""
    price = [("c", f"CHF {book.price:.2f}")] if book.price is not None else []  # Herkunft und Physikbibliothek-Nr. werden nicht exportiert
    binding = []  # Einband (Taschenbuch/Hardcover) wird nicht mehr geführt
    f = [
        ("001", f"book-{book.pk}"),
        ("005", updated.strftime("%Y%m%d%H%M%S") + ".0"),
        ("008", created.strftime("%y%m%d") + "s" + (f"{year:04d}" if year else "    ") + "    xx "
         + " " * 17 + lang + " d"),
        ("020", " ", " ", [("a", book.isbn13)] + binding + price),
    ]
    if book.isbn10:
        f.append(("020", " ", " ", [("a", book.isbn10)] + binding))
    f.append(("041", "0", " ", [("a", lang)]))
    for i, name in enumerate(authors):  # first = main entry, the rest = added entries
        personal = "," in name
        tag = ("100" if personal else "110") if i == 0 else ("700" if personal else "710")
        f.append((tag, "1" if personal else "2", " ", [("a", name)]))
    t, s, r = _c(book.title), _c(book.subtitle), _c(book.statement_of_responsibility)
    sub = [("a", t + " :"), ("b", s + (" /" if r else ""))] if s else [("a", t + (" /" if r else ""))]
    if r:
        sub.append(("c", r))
    f.append(("245", "1" if authors else "0", "0", sub))
    if _c(book.edition):
        f.append(("250", " ", " ", [("a", _c(book.edition))]))
    if pub or place or year:
        sub = []
        if place:
            sub.append(("a", place + (" :" if pub else ("," if year else ""))))
        if pub:
            sub.append(("b", pub + ("," if year else "")))
        if year:
            sub.append(("c", str(year)))
        f.append(("264", " ", "1", sub))
    ext, _, ill = _c(book.extent).partition(" : ")
    if ext:
        f.append(("300", " ", " ", [("a", ext + (" :" if ill else ""))] + ([("b", ill)] if ill else [])))
    elif book.page_count:
        f.append(("300", " ", " ", [("a", f"{book.page_count} Seiten")]))
    if ext and book.page_count:
        f.append(("500", " ", " ", [("a", f"Seitenzahl: {book.page_count}")]))
    digital_only = not book.is_physical
    f += [("336", " ", " ", [("a", "Text"), ("b", "txt"), ("2", "rdacontent")]),
          ("337", " ", " ", [("a", "Computermedien" if digital_only else "ohne Hilfsmittel zu benutzen"),
                             ("b", "c" if digital_only else "n"), ("2", "rdamedia")]),
          ("338", " ", " ", [("a", "Online-Ressource" if digital_only else "Band"),
                             ("b", "cr" if digital_only else "nc"), ("2", "rdacarrier")])]
    if _c(book.description):
        f.append(("520", " ", " ", [("a", _c(book.description)[:2000])]))
    if book.age_category:
        f.append(("521", " ", " ", [("a", book.get_age_category_display())]))
    terms = []
    for g in book.genres.all():
        for name in ([g.parent.name] if g.parent else []) + [g.name]:
            if name not in terms:
                terms.append(name)
    f += [("653", " ", " ", [("a", name)]) for name in terms]
    for g in book.genres.all():  # Thema -> Unterthema as a subject heading with subdivision
        sub = [("a", g.parent.name), ("x", g.name)] if g.parent else [("a", g.name)]
        f.append(("650", " ", "4", sub))
    if pdf_ref:
        f.append(("856", "4", "0", [("u", pdf_ref), ("z", "PDF")]))
    if front_ref:
        f.append(("856", "4", "2", [("u", front_ref), ("z", "Titelbild")]))
    if back_ref:
        f.append(("856", "4", "2", [("u", back_ref), ("z", "Rückseite")]))
    if _c(getattr(book, "internal_notes", "")):
        f.append(("590", " ", " ", [("a", _c(book.internal_notes)[:2000])]))  # local note, staff only
    if book.is_physical:  # one holdings field per copy
        for i in range(max(book.quantity_in_stock, 1)):
            sub = [(c, v) for c, v in (("a", _c(book.branch)), ("b", _c(book.location2)),
                                       ("h", _c(book.shelf_location)),
                                       ("p", _c(book.inventory_number) if i == 0 else ""),
                                       ("z", book.get_loan_status_display())) if v]
            if sub:
                f.append(("852", " ", " ", sub))
    local = [(c, v) for c, v in (("a", _c(book.media_group_display)),
                                 ("b", book.get_loan_status_display() if book.is_physical else ""),
                                 ("c", book.get_medium_display()),
                                 ("e", str(book.quantity_in_stock) if book.is_physical else "")) if v]
    if local:
        f.append(("990", " ", " ", local))
    return f


def to_mrc(fields):
    """One record as binary MARC21 (ISO 2709, UTF-8)."""
    chunks = []
    for fld in _sorted(fields):
        data = fld[1] if len(fld) == 2 else fld[1] + fld[2] + "".join(SF + c + v for c, v in fld[3])
        chunks.append((fld[0], (data + FT).encode("utf-8")))
    directory, pos = "", 0
    for tag, raw in chunks:
        directory += f"{tag}{len(raw):04d}{pos:05d}"
        pos += len(raw)
    base = 24 + len(directory) + 1
    leader = f"{base + pos + 1:05d}nam a22{base:05d} i 4500"
    return (leader + directory + FT).encode("ascii") + b"".join(r for _, r in chunks) + RT.encode("ascii")


def to_xml(records):
    """All records as one MARCXML collection."""
    out = ['<?xml version="1.0" encoding="UTF-8"?>', '<collection xmlns="http://www.loc.gov/MARC21/slim">']
    for fields in records:
        out += ["<record>", "<leader>00000nam a2200000 i 4500</leader>"]
        for fld in _sorted(fields):
            if len(fld) == 2:
                out.append(f'<controlfield tag="{fld[0]}">{escape(fld[1])}</controlfield>')
            else:
                out.append(f'<datafield tag="{fld[0]}" ind1="{fld[1]}" ind2="{fld[2]}">')
                out += [f'<subfield code="{c}">{escape(v)}</subfield>' for c, v in fld[3]]
                out.append("</datafield>")
        out.append("</record>")
    out.append("</collection>")
    return "\n".join(out)
