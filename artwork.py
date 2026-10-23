"""Pictures on the public site, and how a real photograph replaces one.

Every illustrated scene on the site is a *slot*: a name like "presenting" or
"teamwork". A slot renders whatever is available for it, in this order:

  1. static/img/photos/<slot>.<ext>  — a real photograph, if one has been
     dropped in. jpg, jpeg, png, webp and avif all count.
  2. static/img/scenes/<slot>.svg    — the drawn artwork that ships with the
     site, so nothing is ever a broken image.

That is the whole mechanism. Putting a photograph of actual students into
the site is copying a file into one folder with the right name; no template
is edited and no code is deployed. On Render the folder is part of the repo,
so the photographs are committed like any other asset.

The folder is read once, when the app starts, rather than on every render —
a public landing page should not be doing filesystem work per image per
visitor. The cost is that a photograph added while the server is running
appears after the next restart, which on Render is every deploy anyway.
"""
import os
import re

#: Extensions worth looking for, best format first. webp and avif are listed
#: ahead of jpg deliberately: if somebody has gone to the trouble of making
#: one, it is smaller than the jpg sitting beside it.
PHOTO_TYPES = (".avif", ".webp", ".jpg", ".jpeg", ".png")

#: Every slot the templates can ask for, with the sentence that describes it
#: to somebody who cannot see it. The alt text lives here rather than in the
#: templates so a photograph and the drawing it replaces are described the
#: same way, and so this list doubles as the brief for what to photograph.
SLOTS = {
    "presenting": "A student standing beside a projected slide, presenting "
                  "their finished project to the company that commissioned it "
                  "while their lecturer watches from the room",
    "teamwork": "Students around a table late into a project, one sketching a "
                "layout, two at laptops, the work spread out between them",
    "review": "A lecturer going through a student's submission on screen, "
              "marking up the parts that need another pass",
    "brief": "A company lead writing up the brief they need delivered, the "
             "requirements taking shape on the board behind them",
    "certificate": "A graduate holding the record of supervised practice "
                   "their finished projects earned them",

    # Slots that exist so a particular part of the site can be given its own
    # picture later, without anybody editing a template to do it. Until a
    # file is dropped in for one, it borrows from the slot named in
    # BORROWS_FROM below, so nothing is ever missing.
    "portal-hero": "Students of this institution at work on a live brief for "
                   "a company, in their own lab",
    "portal-steps": "A lecturer at this institution going through a student's "
                    "submission before it reaches the client",

    # The receipts feature, shown rather than described. Both of these are
    # photographs of a phone whose screen carries the PraxoraX mark — see
    # tools/brand_screens.py, which put it there.
    "alerts": "A phone showing a PraxoraX confirmation: the work was "
              "received, and the person who sent it has been told so",
    "alerts-portal": "A student checking a PraxoraX confirmation on their "
                     "phone moments after submitting their work",
    "car": "A PraxoraX car, side on, moving",
}


#: A slot with no file of its own shows another slot's picture. This is what
#: lets a university supply photographs of their own students without any
#: code change: drop portal-hero.jpg in and that portal stops borrowing.
BORROWS_FROM = {
    "portal-hero": "teamwork",
    "portal-steps": "review",
    "alerts-portal": "alerts",
}


#: The picture that leads a page, by the area of the site it belongs to.
#: Anything not listed gets DEFAULT_HERO. Keep these distinct: the point is
#: that a university's portal does not look like the front door of the main
#: site, and two areas sharing a photograph defeats it.
DEFAULT_HERO = "presenting"
HERO_BY_AREA = {
    "portal": "portal-hero",    # a university's own front page and its forms
}


def _scan(static_folder):
    """Which slots have a real photograph waiting for them."""
    found = {}
    folder = os.path.join(static_folder, "img", "photos")
    if not os.path.isdir(folder):
        return found

    for slot in SLOTS:
        for ext in PHOTO_TYPES:
            name = slot + ext
            if os.path.isfile(os.path.join(folder, name)):
                found[slot] = "img/photos/" + name
                break
    return found


def _measure(path):
    """The intrinsic size of an image file, or None if it cannot be read.

    An <img> without width and height makes the browser lay the page out
    once at zero height and again when the picture lands, and everything
    below it jumps. On a hero that is the whole page moving. So every slot
    carries its real size into the markup — which means measuring the file,
    because a photograph dropped in later is not the size of the drawing it
    replaced.
    """
    if path.lower().endswith(".svg"):
        try:
            with open(path, "r", encoding="utf-8", errors="replace") as fh:
                head = fh.read(2048)
        except OSError:
            return None
        m = re.search(r'viewBox="\s*[\d.+-]+\s+[\d.+-]+\s+([\d.]+)\s+([\d.]+)',
                      head)
        if m:
            return int(float(m.group(1))), int(float(m.group(2)))
        m = re.search(r'width="(\d+)"[^>]*height="(\d+)"', head)
        return (int(m.group(1)), int(m.group(2))) if m else None

    try:                                    # a real photograph
        from PIL import Image
        with Image.open(path) as im:
            return im.size
    except Exception:
        # Pillow missing, or a format it will not open. The page still works;
        # it just loses the reserved space for that one picture.
        return None


def _resolve(photos, slot, _seen=None):
    """The static path a slot ends up showing.

    In order: a photograph dropped in for this slot; the slot it borrows
    from, resolved the same way; its own drawing. The loop guard is there
    because BORROWS_FROM is hand-written and a cycle in it would otherwise
    hang the app at startup rather than at review.
    """
    if slot in photos:
        return photos[slot]

    _seen = _seen or set()
    lender = BORROWS_FROM.get(slot)
    if lender and lender not in _seen:
        return _resolve(photos, lender, _seen | {slot})

    return f"img/scenes/{slot}.svg"


def attach(app):
    """Wire the slots into the templates as photo_for(), photo_alt(),
    photo_size() and hero_slot()."""
    photos = _scan(app.static_folder)
    app.config["PHOTO_SLOTS"] = photos

    paths, sizes = {}, {}
    for slot in SLOTS:
        rel = _resolve(photos, slot)
        paths[slot] = rel
        size = _measure(os.path.join(app.static_folder, *rel.split("/")))
        if size:
            sizes[slot] = size
    app.config["PHOTO_PATHS"] = paths
    app.config["PHOTO_SIZES"] = sizes

    if photos:
        app.logger.info("Photographs in use for: %s", ", ".join(sorted(photos)))

    @app.context_processor
    def inject_artwork():
        def photo_for(slot):
            """The static path for a slot: its photograph, the one it
            borrows, or its drawing."""
            return app.config["PHOTO_PATHS"].get(
                slot, _resolve(app.config["PHOTO_SLOTS"], slot))

        def is_photo(slot):
            """Whether this slot is a real photograph.

            Templates use it to decide on treatment: a photograph wants a
            dark scrim under white text, a drawing already has its own
            contrast and looks muddy under one.
            """
            return slot in app.config["PHOTO_SLOTS"]

        def photo_size(slot):
            """(width, height) of whatever is in the slot, or None."""
            return app.config["PHOTO_SIZES"].get(slot)

        def hero_slot():
            """Which picture leads the page the visitor is standing on.

            A university portal must not open with the same photograph as
            the main site. A student who clicks through from their own
            institution should feel they have arrived somewhere of theirs,
            and the fastest way to undo that is to show them the identical
            hero they just left.

            Decided here, by blueprint, rather than passed in by each of the
            portal's render calls — there are six of them and the next one
            added would forget.
            """
            from flask import request
            return HERO_BY_AREA.get(request.blueprint, DEFAULT_HERO)

        return {"photo_for": photo_for,
                "photo_alt": lambda slot: SLOTS.get(slot, ""),
                "is_photo": is_photo,
                "photo_size": photo_size,
                "hero_slot": hero_slot}
