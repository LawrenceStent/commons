"""A product's files, typeset with Typst (your decision, 6 Oct): the printable PDF a buyer downloads, and the cover image
a listing shows (2000 x 1600 px; Etsy wants at least 2000 px wide).

Typst compiles in-process (the `typst` package), with its own openly licensed fonts (Libertinus Serif for text), so a
file looks the same on any machine and nothing depends on fonts installed here. The product's words never enter the
markup: the template reads them as data (`data.json`) and sets them as plain text, so nothing a model wrote can
become Typst code. An illustration you approved (packs/storefront/images.py) goes on the cover.

Files are written under the society's folder, `products/<id>/`, when a listing is requested, so you can open them
before you approve it.
"""

from __future__ import annotations

import json
import tempfile
from pathlib import Path
from typing import Literal

import typst

PALETTE = {"ink": "#22222a", "paper": "#faf7f0", "accent": "#20345c", "muted": "#6b6b78"}

PDF_TEMPLATE = """
#let d = json("data.json")
#let ink = rgb(d.palette.ink)
#let accent = rgb(d.palette.accent)
#let muted = rgb(d.palette.muted)
#set document(title: d.title)
#set page(paper: d.paper, margin: (x: 0.9in, y: 0.85in), fill: rgb(d.palette.paper),
  footer: context {
    set text(size: 8.5pt, fill: muted)
    if counter(page).get().first() > 1 [#d.credit #h(1fr) #counter(page).display()]
  })
#set text(font: "Libertinus Serif", size: 11.5pt, fill: ink, lang: "en")
#set par(justify: true, leading: 0.75em, spacing: 1.1em)

// title page
#v(1fr)
#align(center)[
  #text(size: 30pt, weight: "bold", fill: accent)[#d.title]
  #v(14pt)
  #line(length: 30%, stroke: 0.8pt + accent)
  #v(14pt)
  #text(size: 12pt, style: "italic", fill: muted)[#d.subtitle]
]
#v(1.4fr)
#pagebreak()

#for b in d.blocks {
  if b.kind == "heading" {
    v(6pt)
    block(below: 8pt, text(size: 15pt, weight: "bold", fill: accent)[#b.text])
  } else {
    par[#b.text]
  }
}
"""

COVER_TEMPLATE = """
#let d = json("data.json")
#let accent = rgb(d.palette.accent)
#set page(width: 1000pt, height: 800pt, margin: 0pt, fill: rgb(d.palette.paper))
#set text(font: "Libertinus Serif", fill: rgb(d.palette.ink))
#if d.art != none {
  place(top + left, image(d.art, width: 1000pt, height: 560pt, fit: "cover"))
}
#place(top + left, dx: 20pt, dy: 20pt, rect(width: 960pt, height: 760pt, stroke: 3pt + accent))
#let band = if d.art != none { (top: 580pt, height: 160pt) } else { (top: 200pt, height: 400pt) }
#place(top + left, dy: band.top, block(width: 1000pt, height: band.height, inset: (x: 70pt))[
  #set align(center + horizon)
  #text(size: if d.art != none { 46pt } else { 64pt }, weight: "bold", fill: accent)[#d.title]
])
#place(bottom + center, dy: -45pt, text(size: 22pt, style: "italic", fill: rgb(d.palette.muted))[#d.subtitle])
"""


def credit(text: str) -> str:
    if "WEB" in text or "World English Bible" in text:
        return "Scripture quotations from the World English Bible (public domain)."
    if "KJV" in text or "King James" in text:
        return "Scripture quotations from the King James Version (public domain)."
    return ""


def blocks(content: str) -> list[dict]:
    """Paragraphs as written; a short line on its own that doesn't end a sentence is a heading."""
    out = []
    for b in (b.strip() for b in content.split("\n\n")):
        if b:
            heading = len(b) < 70 and "\n" not in b and not b.endswith((".", "?", "!", ":"))
            out.append({"kind": "heading" if heading else "text", "text": b})
    return out


def _compile(template: str, data: dict, fmt: Literal["pdf", "png"] = "pdf", art: bytes | None = None, **kw) -> bytes:
    with tempfile.TemporaryDirectory() as d:
        root = Path(d)
        if art:
            (root / "art.png").write_bytes(art)
        (root / "data.json").write_text(json.dumps({**data, "palette": PALETTE, "art": "art.png" if art else None}))
        (root / "main.typ").write_text(template)
        out = typst.compile(str(root / "main.typ"), root=str(root), format=fmt, **kw)
    if not isinstance(out, bytes):
        raise ValueError("expected one page from the cover template")
    return out


def pdf(title: str, content: str, paper: str = "us-letter") -> bytes:
    """A title page, then the content: paragraphs and headings as written, the scripture credit in the footer."""
    note = credit(content)
    return _compile(PDF_TEMPLATE, {"title": title, "subtitle": note or "A printable for home use.", "credit": note,
                                   "paper": paper, "blocks": blocks(content)})


def cover(title: str, subtitle: str = "Printable PDF · instant download", art: bytes | None = None) -> bytes:
    """PNG, 2000 x 1600 px: an approved illustration with a title band, or a typographic cover."""
    return _compile(COVER_TEMPLATE, {"title": title, "subtitle": subtitle}, "png", art, ppi=144)


def write(folder: Path, product_id: str, title: str, content: str, art: bytes | None = None) -> dict[str, Path]:
    """The PDF in US Letter and A4 (buyers on both sides of the Atlantic), and the cover."""
    where = folder / "products" / product_id
    where.mkdir(parents=True, exist_ok=True)
    files = {"pdf": where / "product.pdf", "pdf_a4": where / "product-a4.pdf", "cover": where / "cover.png"}
    files["pdf"].write_bytes(pdf(title, content))
    files["pdf_a4"].write_bytes(pdf(title, content, "a4"))
    files["cover"].write_bytes(cover(title, art=art))
    return files
