"""Sharing a certificate, and what survives printing it.

A certificate exists to be sent to somebody and checked. Two ways that
fails: there is no way to send it, or the printed copy loses the reference
that makes it checkable. The second is the one that bites silently — it
looks right on screen and the fault only appears on paper — so it is tested
here against the stylesheet rather than trusted.

Run after seed_demo.py.
"""
import os
import re

os.environ.setdefault("DATABASE_URL",
                      "postgresql://smtest:test@127.0.0.1:5432/smtest")
os.environ.update(SECRET_KEY="test", DEMO_MODE="false", UPLOAD_FOLDER="/tmp/up27",
                  TRIAL_DAYS="0", BASE_URL="https://praxorax.test")

from app import app
from db import execute, query

app.config["TESTING"] = True
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
P = F = 0


def step(label, ok, extra=""):
    global P, F
    P, F = (P + 1, F) if ok else (P, F + 1)
    print(("PASS  " if ok else "FAIL  ") + label + (f"   {extra}" if extra else ""))


def login(address, password="demo1234"):
    c = app.test_client()
    c.post("/login", data={"email": address, "password": password})
    with c.session_transaction() as s:
        assert s.get("user_id"), f"could not sign in as {address}"
    return c


# A student with something to certify.
with app.app_context():
    row = query(
        """SELECT a.id, u.email, u.id AS student_id
             FROM assignments a JOIN users u ON u.id = a.student_id
            WHERE u.email LIKE %s ORDER BY a.id LIMIT 1""",
        ("%demo.marketplace",), one=True)
    execute("""UPDATE assignments SET status='completed', completed_at=NOW()
                WHERE id=%s""", (row["id"],))

student = login(row["email"])
student.post("/student/praxfolio/certificate", follow_redirects=True)

with app.app_context():
    cert = query("""SELECT reference FROM portfolio_certificates
                     WHERE student_id=%s ORDER BY id DESC LIMIT 1""",
                 (row["student_id"],), one=True)

assert cert, "no certificate was issued to test against"
REF = cert["reference"]
page = app.test_client().get(f"/certificate/{REF}").data.decode()

# ------------------------------------------------------------- it shares
print("\n--- sending it somewhere ---\n")

step("the certificate opens without a login", REF in page)
step("it offers a LinkedIn post", "linkedin.com/sharing" in page)
step("and the link it shares is this certificate",
     f"certificate%2F{REF}" in page or f"certificate/{REF}" in page)
step("the full URL is shown to copy", f"/certificate/{REF}" in page)
step("and there is a copy button", "clipboard" in page)

# The share panel is help, not part of the document. Split on the opening
# tag rather than on class="certificate", which does not appear literally:
# the class attribute carries a conditional second class and renders with a
# trailing space. Matching nothing would hand back the whole page and make
# this assertion pass without testing anything.
DOC_TAG = '<article class="certificate'
assert DOC_TAG in page, "could not find the certificate document in the page"
share_block, doc = page.split(DOC_TAG, 1)
step("the sharing controls sit in the no-print region",
     "no-print" in share_block and "linkedin.com/sharing" in share_block)
step("and not inside the document itself",
     "linkedin.com/sharing" not in doc)

# --------------------------------------------------------------- skills
print("\n--- skills ---\n")

step("skills are tags rather than a run-on line",
     'class="tag-row"' in page or "SKILLS EVIDENCED" in page.upper())

# -------------------------------------------------- what printing keeps
print("\n--- what survives the printer ---\n")

css = open(os.path.join(ROOT, "static", "css", "style.css")).read()
print_block = css.split("@media print", 1)[1] if "@media print" in css else ""

step("there is a print stylesheet", bool(print_block))

# The regression this file exists for: a bare "footer" selector in the print
# block hides .certificate-foot, which is a <footer>, taking the reference
# number and the verify URL off every printed certificate.
hides_bare_footer = bool(
    re.search(r"(^|[,\s])footer\s*(,|\{)", print_block.split("}")[0]))
step("printing does not hide every <footer> blindly", not hides_bare_footer,
     "a bare 'footer' selector would strip the reference off the printout")

step("the certificate footer is explicitly spared",
     "certificate-foot" in print_block)

# And the markup still puts the reference there to begin with.
step("the reference is inside the document, not only in the share panel",
     REF in doc)
step("so is the date it was issued", "Issued" in doc)
step("and the address to check it against", "/verify" in doc)

# ------------------------------------------------------------- revoked
print("\n--- a revoked certificate ---\n")

with app.app_context():
    execute("""UPDATE portfolio_certificates SET revoked_at=NOW()
                WHERE reference=%s""", (REF,))

revoked = app.test_client().get(f"/certificate/{REF}").data.decode()
step("a revoked certificate still opens", REF in revoked)
step("it says so", "revoked" in revoked.lower())
step("and it is not offered for sharing",
     "linkedin.com/sharing" not in revoked)

with app.app_context():
    execute("""UPDATE portfolio_certificates SET revoked_at=NULL
                WHERE reference=%s""", (REF,))

# ------------------------------------------------- from the Praxfolio
print("\n--- from the Praxfolio ---\n")

mine = student.get("/student/praxfolio").data.decode()
step("the certificate is listed", REF in mine)
step("with a way to post it", "linkedin.com/sharing" in mine)

# ------------------------------------------- advertised on the landing page
print("\n--- the example on the front page ---\n")

landing = app.test_client().get("/").data.decode()

step("the front page shows what a certificate looks like",
     'id="certificate"' in landing and "cert-demo" in landing)
step("it says what you can do with one",
     "LinkedIn" in landing and "CV" in landing)

# The honesty rules for this block. A certificate is a document about a
# named person, so an example carrying a plausible name, company and
# institution is a forged record rather than an advertisement.
specimen = landing.split('id="certificate"', 1)[1].split("</section>", 1)[0]

step("the name slot is a placeholder, not a person",
     "Your name" in specimen)
step("the company and institution are placeholders too",
     "Who set the brief" in specimen and "Your university" in specimen)
step("the reference is visibly fake",
     "PX-XXXXXXXXXX" in specimen)
step("and it is captioned as an example",
     "An example" in specimen)

# Nothing real should leak into an advert.
step("no issued certificate reference appears on the landing page",
     REF not in landing, REF)

print(f"\n{P} passed, {F} failed")
raise SystemExit(1 if F else 0)
