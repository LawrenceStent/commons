"""The storefront's work: digital products for a faith and patriotic audience (your decisions, 5 Oct;
docs/PHASE2-PLAN.md), each made in four parts: audience (who it's for and why they'd trust it), content (the product
itself), layout (how the printable is laid out) and listing (what the store shows: title, description, tags, price).

A product job's subject is a product brief. A society's own briefs (societies/<name>/questions.md) replace the
defaults below. Every part is held to the storefront's rules at hand-in (packs/storefront/screen.py), and a listing
is screened again before it goes to the gate.
"""

from commons.domain.format import Format
from commons.domain.pack import TemplateWorkSource

SUBJECTS = (
    "a 30-day Bible reading plan for new believers (KJV), as a printable PDF",
    "a set of six printable verse art prints from the Psalms (KJV), for a family room",
    "a weekly prayer planner for busy mothers, as a printable PDF",
    "52 scripture memory cards on courage and faith (KJV), to print and cut",
    "a four-week small-group study guide on the Book of Ruth (WEB)",
    "a homeschool study pack on the Bill of Rights: each amendment, a question and a short activity",
    "a July 4th family printable pack: colouring pages, a quiz on the founding, a thanksgiving prayer",
    "a Veterans Day thank-you card set to print and colour",
    "a founders' quotes wall art set (the Declaration of Independence and public-domain words of the founders)",
    "a giving and saving journal with a verse from Proverbs (KJV) on each week, promising nothing but structure",
)

HONEST = ("Honest and modest: devotional, inspirational, educational or decorative; no real people, trademarks or "
          "endorsements; nothing about elections; no promises of health, money or results; no pressure; scripture "
          "from the KJV or WEB only, with references.")

TEMPLATES: dict[str, tuple[str, str]] = {  # in this order: same seed, same jobs
    "audience": (
        "Describe who would buy {subject}, and why: who they are, what they need from it, how they would use it, and "
        "what would make them trust it.",
        "Four labelled sections: Who, Need, Use, Trust. Specific about the buyer (not 'everyone'); grounded in what "
        "the product actually is. 120 to 250 words. " + HONEST,
    ),
    "content": (
        "Write the full content of {subject}, complete and ready to lay out.",
        "Complete: every page, day, card or entry the product promises is there; scripture quoted exactly, with book, "
        "chapter, verse and translation; accurate history and civics; warm, plain language. Where the buyer fills "
        "something in, mark it: a line '- [ ] item' is a box to tick, a line '[write 4]' is four lines to write on. "
        + HONEST,
    ),
    "layout": (
        "Specify the layout of {subject} as a printable PDF.",
        "Three labelled sections: Pages (each page and what's on it), Type (fonts and sizes), Colour (a small "
        "palette). US Letter and A4 both work; prints well in black and white. " + HONEST,
    ),
    "listing": (
        "Write the store listing for {subject}.",
        "Four labelled lines or sections: Title (at most 140 characters), Description (what's included, page count, "
        "that it's a digital download to print at home), Tags (at most 13, comma-separated, each at most 20 "
        "characters), Price (USD, at least 5.00 and at most 49.99: price for the value; bundles and packs well above "
        "the floor). " + HONEST,
    ),
}

FORMATS = {
    "audience": Format(120, 250, ("Who", "Need", "Use", "Trust")),
    "content": Format(150, 2000),
    "layout": Format(60, 600, ("Pages", "Type", "Colour")),
    "listing": Format(40, 400, ("Title", "Description", "Tags", "Price")),
}

WORK_SOURCE = TemplateWorkSource(SUBJECTS, TEMPLATES, title="{subject}", formats=FORMATS)
