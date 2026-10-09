# Images

## What is here

`hero-chain.svg` — the landing page illustration.
`fields/*.svg` — one tile per curriculum field, used as the fallback image on
every brief that has no cover of its own.
`brief-placeholder.svg` — last resort when a brief has no cover and its field
has no tile.

These are vector drawings, not photographs. They are here so the site has
structure and colour out of the box, and they weigh almost nothing.

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
