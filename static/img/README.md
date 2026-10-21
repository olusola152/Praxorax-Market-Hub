# Images

## What is here

`seal.svg` — the mark. Four arcs closing into a ring around a brass centre:
the four parties a project passes through — student, supervisor, university,
client — and the seal they produce between them. The ring only closes when all
four have signed. Used wherever `.mark-seal` appears, which is the header, the
sign-in gates, the institution portals and the certificate check.

`favicon.svg` — the same mark inverted onto a seal-green plate, for the browser
tab. It carries its own ground because a tab may be light or dark and the page
has no say in which, and its arcs are wider and its gaps narrower than the
full-size mark so that four arcs still read as four at 16px.

`hero-chain.svg` — the landing illustration: a certificate of supervised
practice on a seal-green plate, beside the four countersignatures that produced
it. The certificate is the picture rather than a diagram of the software,
because the record is what the platform actually produces. Its text uses
Georgia and the generic monospace stack on purpose — an SVG loaded through
`<img>` cannot fetch the site's webfonts, so those are what will render.

`fields/*.svg` — one tile per curriculum field, used as the fallback image on
every brief that has no cover of its own. Every tile sits on the same
seal-green ground so a row of them reads as one set; the accent says which of
six discipline families the field belongs to, and the drawing says what the
field is — a commit graph for computing, an ECG for medicine, a truss for civil
engineering, ruled columns for accounting.

`brief-placeholder.svg` — last resort when a brief has no cover and its field
has no tile.

These are vector drawings, not photographs. They are here so the site has
structure and colour out of the box, and they weigh almost nothing.

## Adding a faculty tile

The tiles are generated, not hand-drawn, so the set cannot drift out of step
with itself:

```bash
python tools/make_field_tiles.py
```

Add the field to `FIELDS` in that script against a family and a motif, add the
row to the `fields` table, and re-run. The filename is the field name
lowercased with non-alphanumerics turned to hyphens, which is what the landing
page and the brief feed both build from. `tests/test_v14_identity.py` fails if
a field in the database has no tile.

## Putting real photographs in

Real photos will look better, and the app prefers them automatically. There are
three places to set one, all plain URL columns — point them at anything, a file
you drop in this folder or an external host:

| What | Where it is set | Column |
|---|---|---|
| A brief's cover | company: edit the brief | `projects.cover_url` |
| A company logo | company settings | `companies.logo_url` |
| A field tile | SQL | `fields.image_url` |

To replace a field tile with a photo, drop the file here and run:

```sql
UPDATE fields SET image_url = 'img/fields/software-engineering.jpg'
 WHERE name = 'Software Engineering';
```

The path is relative to `static/`. An `https://` URL works too.

## Sizes

Cover images are drawn at roughly 440x280 and cropped to fill, so anything
around 3:2 landscape works. Keep files under about 300 KB — most of your users
are on mobile data.
