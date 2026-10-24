# Photographs

Drop a photograph in here and it replaces the drawn artwork on the public
site. Nothing else changes — no template edit, no code deploy.

## The names

The file name is what decides where it appears. Use exactly these:

| file | where it appears | what it should show |
|---|---|---|
| `presenting.jpg` | the hero, top of the landing page | a student presenting their finished project to the company, lecturer in the room |
| `teamwork.jpg` | "How it works" | students mid-project around a table — laptops, sketches, the work spread out |
| `review.jpg` | the supervision section | a lecturer going through a submission on screen, marking it up |
| `brief.jpg` | the companies section | a company lead writing up the work they need done |
| `certificate.jpg` | the closing band | a graduate with the record their finished projects earned |
| `fleet.jpg` | the "wherever you are" card | brand imagery — somewhere being travelled to |

### University portal only

These two are optional. Leave them out and the portal borrows the pictures
above; drop one in and that portal stops borrowing and shows yours instead.
This is how an institution puts photographs of *its own* students on *its own*
portal without anything in the code changing.

| file | where it appears | borrows from if absent |
|---|---|---|
| `portal-hero.jpg` | the hero on every university portal page | `teamwork.jpg` |
| `portal-steps.jpg` | the "how it works here" picture | `review.jpg` |
| `alerts-portal.jpg` | the confirmations card on a portal | `alerts.jpg` |

### Device screens

`alerts.jpg` and `alerts-portal.jpg` show a phone with the PraxoraX mark on
its screen. The mark was composited on by `tools/brand_screens.py`, which
measures the badge already in the photograph — where it is, how big, how the
device is tilted — paints it out, and draws the seal back through the same
transform so it sits on the glass rather than on top of the picture.

If you replace either photograph with one of your own, run:

    python3 tools/brand_screens.py <folder-with-the-originals>

or supply a photograph of a real phone showing the real site, which is
better than any compositing.

`.jpg`, `.jpeg`, `.png`, `.webp` and `.avif` all work. If two formats of the
same name are here, the smaller modern one wins (avif, then webp, then jpg).

## What makes them work

* **Landscape, and big.** 2000px wide or more. `presenting.jpg` and
  `certificate.jpg` run full width behind white text — anything smaller goes
  soft on a laptop screen.
* **Keep the subject off-centre**, towards the right. Headlines sit on the
  left over these images.
* **Room for text.** A busy frame edge to edge leaves the words nowhere to go.
* **Real rooms beat stock.** A photograph of actual students in an actual
  lab is worth more here than a polished stock image of nobody in particular.
* **Compress before committing.** Over about 400KB and the page gets slow on
  a phone, which is how most people will open it. `squoosh.app` does this in
  a browser with nothing to install.

## Permission

Use photographs you took, that the university took, or that are properly
licensed. Students in a recognisable photograph should have agreed to it
being on a public website.

## After adding one

Commit it and push. Render restarts on deploy, which is when the folder is
re-read:

    git add static/img/photos/
    git commit -m "Add photographs"
    git push

Remove a photograph and that slot goes back to the drawn artwork.
