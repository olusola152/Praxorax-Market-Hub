"""Social accounts — the platform's own, and each person's.

Both kinds live in one table, told apart by whether user_id is set. That is
not a shortcut: the rules are identical. The same eight networks, the same
validation, the same way of turning what somebody typed into a link that
opens the right app.

What people actually paste varies wildly — a full URL, an @handle, a bare
username, a phone number with or without a plus. Rather than making them get
it right, each network knows how to read all of those and produce one
canonical link.
"""
import re

from db import execute, query

#: The networks offered, in the order they are shown. Each carries the label
#: people know it by, the hint under the field, and how a handle becomes a
#: URL. `prefix` is what a bare handle is appended to; `host` is how a pasted
#: URL is recognised as already being this network.
NETWORKS = {
    "whatsapp":  {"label": "WhatsApp",  "host": "wa.me",
                  "prefix": "https://wa.me/",
                  "hint": "Phone number with country code, e.g. 2348012345678",
                  "digits": True},
    "telegram":  {"label": "Telegram",  "host": "t.me",
                  "prefix": "https://t.me/",
                  "hint": "Your username, without the @"},
    "x":         {"label": "X",         "host": "x.com",
                  "prefix": "https://x.com/",
                  "hint": "Your handle, without the @",
                  "also": ("twitter.com",)},
    # LinkedIn is the one network where a person and an organisation live at
    # different paths — /in/ada-obi against /company/praxorax — so the stored
    # handle keeps its segment and the prefix stops at the domain. A bare
    # name is assumed to be a person, which is who is usually filling this in.
    "linkedin":  {"label": "LinkedIn",  "host": "linkedin.com",
                  "prefix": "https://www.linkedin.com/",
                  "segments": ("in", "company", "school", "showcase"),
                  "default_segment": "in",
                  "hint": "Your profile URL, or company/your-page"},
    "facebook":  {"label": "Facebook",  "host": "facebook.com",
                  "prefix": "https://www.facebook.com/",
                  "hint": "Your page or profile name",
                  "also": ("fb.com", "fb.me")},
    "instagram": {"label": "Instagram", "host": "instagram.com",
                  "prefix": "https://www.instagram.com/",
                  "hint": "Your username, without the @"},
    "tiktok":    {"label": "TikTok",    "host": "tiktok.com",
                  "prefix": "https://www.tiktok.com/@",
                  "hint": "Your username, without the @"},
    "youtube":   {"label": "YouTube",   "host": "youtube.com",
                  "prefix": "https://www.youtube.com/@",
                  "hint": "Your channel handle, without the @",
                  "also": ("youtu.be",)},
}

#: Networks a person can be contacted on directly. The rest are places to
#: follow somebody, which is a different thing, and a student looking for
#: their supervisor should not be sent to a TikTok account.
CONTACTABLE = ("whatsapp", "telegram", "x", "linkedin", "facebook")

#: What each network is actually for on this platform. The eight are not
#: interchangeable and showing them as one undifferentiated list was wrong:
#: a company fills in the ones somebody can message it on, a student fills
#: in the one they publish their record to, and the broadcast channels are
#: the platform's own and nobody else's.
PURPOSE = {
    "contact": {
        "networks": ("whatsapp", "telegram", "facebook", "instagram", "x"),
        "title": "Where people can message you",
        "blurb": "Fill in the ones you actually watch.",
        # The same group means something different depending on who is
        # filling it in, so the sentence that explains it is per role
        # rather than one line that is wrong for most readers.
        "blurb_by_role": {
            "company": "A student placed on one of your briefs reaches you "
                       "here when they have a question. Fill in the ones you "
                       "actually watch.",
            "student": "Your supervising lecturer and the companies whose "
                       "briefs you take on can reach you here. Fill in the "
                       "ones you actually watch.",
            "lecturer": "Your students and the companies whose briefs you "
                        "supervise can reach you here.",
            None: "How somebody reaches " + "us" + " directly, rather than "
                  "a channel we post to.",
        },
    },
    "profile": {
        "networks": ("linkedin",),
        "title": "Your professional profile",
        "blurb": "Where finished work is worth showing.",
        "blurb_by_role": {
            "student": "Where your finished work is worth showing. Your "
                       "Praxfolio has a share button that posts your public "
                       "link straight here.",
            "company": "Your organisation's page, for students looking you up "
                       "before they apply.",
            "lecturer": "Your professional profile.",
            None: "The " + "platform's" + " own page.",
        },
    },
    "broadcast": {
        "networks": ("youtube", "tiktok"),
        "title": "Channels you post to",
        "blurb": "Places you publish to rather than places people reach you.",
    },
}


def blurb_for(group, role):
    """The sentence under a group's heading, for this particular reader."""
    by_role = group.get("blurb_by_role") or {}
    return by_role.get(role, group["blurb"])


def groups_for_role(role):
    """Which groups of networks a given account is asked to fill in.

    A company is asked for the channels people message it on. A student is
    asked for the profile they publish their record to. Nobody but the
    platform is asked for broadcast channels, because a student's TikTok has
    no business on a page about supervised work.
    """
    if role == "company":
        keys = ("contact", "profile")
    elif role in ("student", "lecturer"):
        keys = ("profile", "contact")
    elif role is None:                      # the platform itself
        keys = ("broadcast", "contact", "profile")
    else:
        keys = ("contact", "profile")
    return [(k, PURPOSE[k]) for k in keys]


def share_url(network, link, title=""):
    """A link that opens the given network's share dialog.

    Only LinkedIn for now, which is the one a student has a reason to post a
    finished record to. Added here rather than in a template so the next one
    is a line in this dict instead of markup in three pages.
    """
    from urllib.parse import quote
    builders = {
        "linkedin": lambda u, t: "https://www.linkedin.com/sharing/share-offsite/?url=" + quote(u, safe=""),
    }
    build = builders.get(network)
    return build(link, title) if build else None

MAX_HANDLE = 200


def _hosts(key):
    net = NETWORKS[key]
    return (net["host"],) + tuple(net.get("also", ()))


def clean(key, raw):
    """Turn whatever somebody typed into a stored handle, or None.

    Accepts a full URL, an @handle, or a bare name, because all three are
    what people paste and none of them is wrong.
    """
    if key not in NETWORKS:
        return None
    value = (raw or "").strip()
    if not value:
        return None

    net = NETWORKS[key]

    segments = net.get("segments")

    # A pasted URL: keep the path, drop everything else. Query strings on a
    # profile link are tracking parameters and do not belong in a database.
    if "/" in value or value.startswith("http"):
        stripped = re.sub(r"^https?://", "", value, flags=re.I).strip("/")
        host = stripped.split("/")[0].lower()
        if any(host == h or host.endswith("." + h) for h in _hosts(key)):
            rest = stripped.split("/", 1)[1] if "/" in stripped else ""
            value = rest.split("?")[0].split("#")[0].strip("/")
        elif segments and host.split("/")[0] in segments:
            # Not a URL at all — a path like "company/praxorax" typed on its
            # own, which is what somebody copying half a LinkedIn address
            # produces.
            value = stripped.split("?")[0].split("#")[0].strip("/")
        else:
            # A link to somewhere else entirely. Refuse rather than store a
            # handle that will build into a URL pointing at the wrong site.
            return None

    value = value.lstrip("@").strip("/")

    if segments:
        head = value.split("/", 1)[0].lower()
        if head in segments:
            # Keep exactly one segment and one name; anything deeper is a
            # post or a job advert rather than a profile.
            parts = [p for p in value.split("/") if p][:2]
            if len(parts) < 2:
                return None
            value = parts[0].lower() + "/" + parts[1]
        elif "/" in value:
            return None
        else:
            value = net["default_segment"] + "/" + value

    if net.get("digits"):
        value = re.sub(r"[^0-9]", "", value)
        # Shorter than this is not a phone number anywhere.
        if len(value) < 7:
            return None

    if not value or len(value) > MAX_HANDLE:
        return None
    if re.search(r"[\s<>\"']", value):
        return None
    return value


def url_for_handle(key, handle):
    """The link that opens the right app."""
    net = NETWORKS.get(key)
    if not net or not handle:
        return None
    return net["prefix"] + handle


def _rows(user_id):
    where = "user_id = %s" if user_id else "user_id IS NULL"
    params = (user_id,) if user_id else ()
    return query(f"SELECT network, handle FROM social_links WHERE {where}",
                 params)


def links_for(user_id=None, contactable_only=False):
    """Every account held, in the display order of NETWORKS.

    Returns dicts carrying the label and the built URL, so a template never
    has to know anything about any particular network.
    """
    held = {r["network"]: r["handle"] for r in _rows(user_id)}
    out = []
    for key, net in NETWORKS.items():
        if key not in held:
            continue
        if contactable_only and key not in CONTACTABLE:
            continue
        out.append({"key": key, "label": net["label"], "handle": held[key],
                    "url": url_for_handle(key, held[key])})
    return out


def handles_for(user_id=None):
    """Raw handles keyed by network, for filling in the edit form."""
    return {r["network"]: r["handle"] for r in _rows(user_id)}


def save(user_id, submitted):
    """Write a whole set of handles at once.

    Returns the networks that were rejected, so the form can say which field
    to look at rather than silently dropping it. An empty field is a removal,
    which is how somebody takes their number back down.
    """
    bad = []
    for key in NETWORKS:
        raw = (submitted.get(key) or "").strip()
        value = clean(key, raw) if raw else None

        if raw and value is None:
            bad.append(key)
            continue

        if value is None:
            if user_id:
                execute("DELETE FROM social_links WHERE user_id=%s AND network=%s",
                        (user_id, key))
            else:
                execute("DELETE FROM social_links WHERE user_id IS NULL AND network=%s",
                        (key,))
            continue

        if user_id:
            execute(
                """INSERT INTO social_links (user_id, network, handle)
                   VALUES (%s,%s,%s)
                   ON CONFLICT (user_id, network) WHERE user_id IS NOT NULL
                   DO UPDATE SET handle=EXCLUDED.handle, updated_at=NOW()""",
                (user_id, key, value))
        else:
            execute(
                """INSERT INTO social_links (user_id, network, handle)
                   VALUES (NULL,%s,%s)
                   ON CONFLICT (network) WHERE user_id IS NULL
                   DO UPDATE SET handle=EXCLUDED.handle, updated_at=NOW()""",
                (key, value))
    return bad
