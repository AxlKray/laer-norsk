"""Import helpers: find the ISBN in cover images / a PDF, then look up the book data online.

The analysis uses ALL files that were given (front, back, PDF) together: barcodes on every image
and PDF page, ISBN text in the PDF, printed ISBNs via text recognition, PDF metadata as fallback.

Needs: Pillow, PyMuPDF (PDF), zxing-cpp (barcodes). Optional: pytesseract + the tesseract program.
The online lookup needs internet access from the server (DNB, swisscovery, Google Books, Open Library).
No Django imports here, so it is easy to test."""
import io
import json
import re
import xml.etree.ElementTree as ET
from urllib.request import Request, urlopen

DC = "{http://purl.org/dc/elements/1.1/}"
LANG = {"ger": "de", "deu": "de", "eng": "en", "fre": "fr", "fra": "fr", "ita": "it", "nor": "no", "nob": "no",
        "spa": "es", "lat": "la"}


# ---------------- ISBN helpers ----------------
def isbn13_valid(v):
    return len(v) == 13 and v.isdigit() and sum(int(d) * (1 if i % 2 == 0 else 3) for i, d in enumerate(v)) % 10 == 0


def isbn10_valid(v):
    if len(v) != 10 or not re.fullmatch(r"\d{9}[\dX]", v):
        return False
    return sum((10 - i) * (10 if c == "X" else int(c)) for i, c in enumerate(v)) % 11 == 0


def isbn10_to_13(v):
    body = "978" + v[:9]
    return body + str((10 - sum(int(d) * (1 if i % 2 == 0 else 3) for i, d in enumerate(body)) % 10) % 10)


def _norm(raw):
    return re.sub(r"[\s-]", "", raw).upper()


LABELED = re.compile(r"[I1l|][S5][B8][NM](?:-1[03])?\s*:?\s*((?:97[89][\s-]?)?(?:\d[\s-]?){9}[\dXx])", re.I)
BARE13 = re.compile(r"\b(97[89](?:[\s-]?\d){10})\b")


def find_isbn_in_text(text):
    """Return an ISBN-13 found in free text ('' if none). Labelled ISBNs win over bare numbers."""
    for m in LABELED.finditer(text or ""):
        raw = _norm(m.group(1))
        if len(raw) == 13 and isbn13_valid(raw):
            return raw
        if len(raw) == 10 and isbn10_valid(raw):
            return isbn10_to_13(raw)
    for m in BARE13.finditer(text or ""):
        raw = _norm(m.group(1))
        if isbn13_valid(raw):
            return raw
    return ""


# ---------------- reading images / PDF ----------------
def read_barcode(img):
    try:
        import zxingcpp
    except ImportError:
        return ""
    img = img.convert("RGB")
    img.thumbnail((2400, 2400))
    for variant in (img, img.convert("L"), img.resize((img.width * 2, img.height * 2))):
        for r in zxingcpp.read_barcodes(variant):
            txt = (r.text or "").strip()
            if txt[:3] in ("978", "979") and isbn13_valid(txt[:13]):
                return txt[:13]
    return ""


def ocr_text(img):
    """Text recognition in several passes (whole picture, bottom half, small stickers); returns all texts joined."""
    try:
        import pytesseract
        from PIL import Image, ImageOps
    except ImportError:
        return ""
    try:
        img = ImageOps.exif_transpose(img)  # phone photos: respect the rotation flag
    except Exception:
        pass
    gray = ImageOps.autocontrast(img.convert("L"))
    w, h = gray.size
    if max(w, h) > 3000:
        gray.thumbnail((3000, 3000))
        w, h = gray.size
    def zoom(box, f=3):  # kleine Ausschnitte (Rückseite: ISBN-Kasten unten rechts) vergrössern: viel besser lesbar
        c = gray.crop(box)
        return ImageOps.autocontrast(c.resize((c.width * f, c.height * f), Image.LANCZOS))
    passes = [(zoom((int(w * .6), int(h * .85), w, h)), "--psm 6"), (zoom((int(w * .6), int(h * .85), w, h), 4), "--psm 6"),
              (zoom((int(w * .5), int(h * .75), w, h)), "--psm 6"), (zoom((0, int(h * .85), int(w * .5), h)), "--psm 6"),
              (gray, "--psm 11"), (gray.crop((0, int(h * .5), w, h)), "--psm 11"),
              (gray.crop((0, int(h * .5), w, h)), "--psm 6"), (gray, "--psm 6"),
              (gray.crop((0, int(h * .5), w, h)).resize((w * 2, int(h * .5) * 2)), "--psm 11")]
    texts = []
    for im, cfg in passes:
        for lang in ("deu+eng", None):
            try:
                texts.append(pytesseract.image_to_string(im, lang=lang, config=cfg) if lang
                             else pytesseract.image_to_string(im, config=cfg))
                break
            except Exception:
                continue
        if find_isbn_in_text("\n".join(texts)):
            break  # found: no further passes needed
    return "\n".join(texts)


def _read_pdf(data):
    import fitz  # PyMuPDF
    from PIL import Image

    doc = fitz.open(stream=data, filetype="pdf")
    n = len(doc)
    pages = list(range(min(n, 15))) + list(range(max(n - 3, 15), n))
    text = "\n".join(doc[i].get_text() for i in pages)

    def render(i):
        return Image.open(io.BytesIO(doc[i].get_pixmap(dpi=150).tobytes("png")))

    meta = {k: (v or "").strip() for k, v in (doc.metadata or {}).items()}
    return text, render(0), (render(n - 1) if n > 1 else None), meta


# ---------------- online lookup ----------------
def _get(url, timeout=8):
    req = Request(url, headers={"User-Agent": "BookCatalogImport/1.0 (school library)"})
    with urlopen(req, timeout=timeout) as r:
        return r.read().decode("utf-8", "replace")


def norm_author(name):
    name = re.sub(r"\s*[\[(].*?[\])]", "", name).strip()
    if "," in name or " " not in name:
        return name
    parts = name.split()
    return f"{parts[-1]}, {' '.join(parts[:-1])}"


def _year(s):
    m = re.search(r"\b(1[5-9]\d\d|20\d\d)\b", s or "")
    return int(m.group(1)) if m else None


def _pages(s):
    m = re.search(r"(\d+)\s*(?:S\.|Seiten|p\b)", s or "")
    return int(m.group(1)) if m else None


def parse_dnb(xml_text):
    root = ET.fromstring(xml_text)

    def vals(tag):
        return [e.text.strip() for e in root.iter(DC + tag) if e.text and e.text.strip()]

    titles = vals("title")
    if not titles:
        return {}
    title, _, sub = titles[0].partition(" : ")
    authors = []
    for a in vals("creator") + vals("contributor"):
        a = norm_author(a)
        if a and a not in authors:
            authors.append(a)
    place, publisher = "", ""
    if vals("publisher"):
        publisher = vals("publisher")[0]
        if " : " in publisher:
            place, _, publisher = publisher.partition(" : ")
    fmt = next((f for f in vals("format") if re.search(r"\bS\.|Seiten", f)), "")
    lang = LANG.get((vals("language") or [""])[0][:3].lower(), "")
    return {
        "title": title.strip(), "subtitle": sub.strip(), "authors": authors, "publisher": publisher.strip(),
        "place": place.strip(), "year": _year(" ".join(vals("date"))), "extent": fmt, "pages": _pages(fmt),
        "language": lang, "description": " ".join(vals("description"))[:2000],
        "genres": [s for s in vals("subject") if not s.replace(".", "").isdigit()][:5],
    }


def _clean(t):
    return re.sub(r"\s*[/:;,=]+\s*$", "", (t or "").strip()).strip()


def parse_marc(xml_text):
    """MARC21-XML (swisscovery/SRU, may hold several records): the most complete record becomes the result."""
    xml_text = re.sub(r'\sxmlns(:\w+)?="[^"]*"', "", xml_text)
    root = ET.fromstring(xml_text)
    best, best_score = {}, 0
    for rec in root.iter("record"):
        if rec.find("datafield") is None:
            continue

        def sub(tag, code, rec=rec):
            return [(sf.text or "").strip() for df in rec.findall("datafield") if df.get("tag") == tag
                    for sf in df.findall("subfield") if sf.get("code") == code and (sf.text or "").strip()]

        title = _clean((sub("245", "a") or [""])[0])
        if not title:
            continue
        authors = []
        for tag in ("100", "700"):
            for a in sub(tag, "a"):
                a = norm_author(_clean(a))
                if a and a not in authors:
                    authors.append(a)
        pub_tag = "264" if sub("264", "b") else "260"
        extent = " : ".join(filter(None, [_clean((sub("300", "a") or [""])[0]), _clean((sub("300", "b") or [""])[0])]))
        lang = ""
        for c in rec.findall("controlfield"):
            if c.get("tag") == "008" and len(c.text or "") >= 38:
                lang = LANG.get(c.text[35:38].lower(), "")
        price = ""
        m = re.search(r"CHF\s*([\d.']+)", " ".join(sub("020", "c")))
        if m:
            price = m.group(1).replace("'", "")
        d = {
            "title": title, "subtitle": _clean((sub("245", "b") or [""])[0]), "authors": authors,
            "responsibility": _clean((sub("245", "c") or [""])[0]),
            "publisher": _clean((sub(pub_tag, "b") or [""])[0]), "place": _clean((sub(pub_tag, "a") or [""])[0]),
            "year": _year(" ".join(sub(pub_tag, "c"))), "edition": _clean((sub("250", "a") or [""])[0]),
            "extent": extent, "pages": _pages(extent), "language": lang or LANG.get((sub("041", "a") or [""])[0][:3], ""),
            "description": " ".join(sub("520", "a"))[:2000], "price": price,
            "genres": [g for g in (sub("650", "a") + sub("653", "a")) if g][:5],
        }
        score = sum(1 for v in d.values() if v)
        if score > best_score:
            best, best_score = d, score
    return best


def parse_google(json_text):
    items = json.loads(json_text).get("items") or []
    if not items:
        return {}
    v = items[0].get("volumeInfo", {})
    return {
        "title": v.get("title", ""), "subtitle": v.get("subtitle", ""),
        "authors": [norm_author(a) for a in v.get("authors", [])], "publisher": v.get("publisher", ""),
        "year": _year(v.get("publishedDate", "")), "pages": v.get("pageCount"),
        "language": (v.get("language") or "")[:2], "description": v.get("description", "")[:2000],
        "genres": (v.get("categories") or [])[:3],
    }


def parse_openlibrary(json_text):
    data = json.loads(json_text)
    if not data:
        return {}
    v = next(iter(data.values()))
    return {
        "title": v.get("title", ""), "subtitle": v.get("subtitle", ""),
        "authors": [norm_author(a["name"]) for a in v.get("authors", []) if a.get("name")],
        "publisher": (v.get("publishers") or [{}])[0].get("name", ""),
        "place": (v.get("publish_places") or [{}])[0].get("name", ""),
        "year": _year(v.get("publish_date", "")), "pages": v.get("number_of_pages"),
        "genres": [s["name"] for s in v.get("subjects", [])[:3] if s.get("name")],
    }


def merge(parts):
    """Combine lookup results; the first source that has a value for a field wins."""
    out = {}
    for p in parts:
        for k, v in p.items():
            if v and not out.get(k):
                out[k] = v
    return out


def lookup_isbn(isbn):
    sources = (
        ("DNB", f"https://services.dnb.de/sru/dnb?version=1.1&operation=searchRetrieve&query=num%3D{isbn}"
                "&recordSchema=oai_dc&maximumRecords=1", parse_dnb),
        ("swisscovery", "https://swisscovery.slsp.ch/view/sru/41SLSP_NETWORK?version=1.2&operation=searchRetrieve"
                        f"&recordSchema=marcxml&maximumRecords=5&query=alma.isbn={isbn}", parse_marc),
        ("Google Books", f"https://www.googleapis.com/books/v1/volumes?q=isbn:{isbn}", parse_google),
        ("Open Library", f"https://openlibrary.org/api/books?bibkeys=ISBN:{isbn}&format=json&jscmd=data",
         parse_openlibrary),
    )
    parts, found, errors = [], [], []
    for name, url, parser in sources:
        try:
            d = parser(_get(url))
        except Exception:
            errors.append(f"{name} nicht erreichbar")
            continue
        if d:
            parts.append(d)
            found.append(name)
    return merge(parts), found, errors


# ---------------- everything together ----------------
def pick_isbn(found):
    """found = [(isbn, source_label, is_barcode)]. Barcodes beat text; returns (isbn, label, conflicts)."""
    if not found:
        return "", "", []
    ordered = sorted(found, key=lambda x: not x[2])
    isbn, label, _ = ordered[0]
    others = sorted({i for i, _, _ in found if i != isbn})
    return isbn, label, others


def analyse(front=None, back=None, pdf=None):
    """front/back/pdf are bytes or None. Uses all of them together.
    Returns isbn, source, data, sources, notes, cover_png."""
    from PIL import Image

    notes, cover_png, meta = [], None, {}
    f_img = Image.open(io.BytesIO(front)) if front else None
    b_img = Image.open(io.BytesIO(back)) if back else None
    text, p_first, p_last = "", None, None
    if pdf:
        try:
            text, p_first, p_last, meta = _read_pdf(pdf)
        except Exception:
            notes.append("Das PDF konnte nicht gelesen werden.")
    if p_first is not None and f_img is None:
        buf = io.BytesIO()
        p_first.save(buf, "PNG")
        cover_png = buf.getvalue()  # first PDF page becomes the front cover

    images = [("Rückseite", b_img), ("Vorderseite", f_img), ("PDF, letzte Seite", p_last), ("PDF, erste Seite", p_first)]
    found = []
    for label, img in images:  # 1) barcodes on every image
        if img is not None:
            code = read_barcode(img)
            if code:
                found.append((code, f"Barcode ({label})", True))
    t = find_isbn_in_text(text)  # 2) ISBN printed in the PDF text (imprint page)
    if t:
        found.append((t, "Text im PDF", False))
    if not found:  # 3) printed ISBN on the covers (text recognition)
        for label, img in images[:2]:
            if img is not None:
                code = find_isbn_in_text(ocr_text(img))
                if code:
                    found.append((code, f"gedruckte ISBN ({label}, Texterkennung)", False))
    isbn, source, others = pick_isbn(found)
    if others:
        notes.append("Die Dateien enthalten verschiedene ISBNs (" + ", ".join(others) + "). Bitte prüfen.")
    data, sources, errors = {}, [], []
    if isbn:
        data, sources, errors = lookup_isbn(isbn)
        if not sources and not errors:
            notes.append("Zu dieser ISBN wurde online nichts gefunden.")
    else:
        notes.append("Keine ISBN erkannt. Bitte unten eingeben und online suchen.")
    if meta and not data.get("title") and meta.get("title"):  # fallback: PDF properties
        data["title"] = meta["title"]
        if meta.get("author"):
            data["authors"] = [norm_author(a.strip()) for a in re.split(r"[;&]", meta["author"]) if a.strip()]
        sources = sources + ["PDF-Eigenschaften"]
    return {"isbn": isbn, "source": source, "data": data, "sources": sources, "notes": notes + errors,
            "cover_png": cover_png}
