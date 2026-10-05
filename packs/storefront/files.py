"""A product's files: the printable PDF a buyer downloads, and the cover image a listing shows (Etsy wants at least
one, about 2000 px wide). Typeset in code from the product's content and layout parts: the same text always makes
the same file, nothing is drawn from a real person's likeness, and it costs nothing. An illustration from the image
service (packs/storefront/images.py), if you approved one, goes on the cover.

Files are written under the society's folder, `products/<id>/`, when a listing is requested, so you can open them
before you approve it.
"""

from __future__ import annotations

import io
import textwrap
from pathlib import Path

from fpdf import FPDF
from PIL import Image, ImageDraw, ImageFont

COVER = (2000, 1600)
INK, PAPER, ACCENT = (34, 34, 40), (250, 247, 240), (32, 52, 92)
LATIN1 = str.maketrans({"‘": "'", "’": "'", "“": '"', "”": '"', "–": "-", "—": "-",
                        "…": "...", " ": " ", "•": "-"})


def _latin1(text: str) -> str:
    """The PDF's built-in fonts are Latin-1: typographic quotes and dashes become plain ones, anything else is dropped."""
    return text.translate(LATIN1).encode("latin-1", "ignore").decode("latin-1")


def credit(text: str) -> str:
    if "WEB" in text or "World English Bible" in text:
        return "Scripture quotations from the World English Bible (public domain)."
    if "KJV" in text or "King James" in text:
        return "Scripture quotations from the King James Version (public domain)."
    return ""


def pdf(title: str, content: str) -> bytes:
    """US Letter: a title page, then the content, paragraphs and headings as written."""
    doc = FPDF(format="Letter", unit="pt")
    doc.set_auto_page_break(True, margin=60)
    doc.set_margins(72, 72, 72)
    doc.add_page()
    doc.set_font("Times", "B", 28)
    doc.set_text_color(*ACCENT)
    doc.ln(180)
    doc.multi_cell(0, 36, _latin1(title), align="C")
    doc.set_font("Times", "I", 12)
    doc.set_text_color(*INK)
    doc.ln(24)
    doc.multi_cell(0, 16, _latin1(credit(content) or "A printable for home use."), align="C")
    doc.add_page()
    for block in [b.strip() for b in content.split("\n\n") if b.strip()]:
        heading = len(block) < 70 and "\n" not in block and not block.endswith(".")
        doc.set_font("Times", "B" if heading else "", 15 if heading else 12)
        doc.multi_cell(0, 20 if heading else 17, _latin1(block))
        doc.ln(8)
    return bytes(doc.output())


def _font(size: int):
    for path in ("/System/Library/Fonts/Supplemental/Georgia.ttf", "/Library/Fonts/Georgia.ttf",
                 "/usr/share/fonts/truetype/dejavu/DejaVuSerif.ttf"):
        if Path(path).exists():
            return ImageFont.truetype(path, size)
    return ImageFont.load_default(size=size)


def cover(title: str, subtitle: str = "Printable PDF - instant download", art: bytes | None = None) -> bytes:
    """PNG, 2000 x 1600: an approved illustration with a title band, or a typographic cover."""
    img = Image.new("RGB", COVER, PAPER)
    if art:
        picture = Image.open(io.BytesIO(art)).convert("RGB")
        picture.thumbnail((COVER[0], COVER[1] - 420))
        img.paste(picture, ((COVER[0] - picture.width) // 2, 0))
    draw = ImageDraw.Draw(img)
    draw.rectangle((40, 40, COVER[0] - 40, COVER[1] - 40), outline=ACCENT, width=6)
    big, small = _font(110), _font(48)
    lines = textwrap.wrap(title, 26)[:4]
    top = COVER[1] - 400 if art else (COVER[1] - len(lines) * 130) // 2 - 60
    for i, line in enumerate(lines):
        w = draw.textlength(line, font=big)
        draw.text(((COVER[0] - w) / 2, top + i * 130), line, fill=ACCENT if not art else INK, font=big)
    w = draw.textlength(subtitle, font=small)
    draw.text(((COVER[0] - w) / 2, COVER[1] - 140), subtitle, fill=INK, font=small)
    out = io.BytesIO()
    img.save(out, "PNG", optimize=True)
    return out.getvalue()


def write(folder: Path, product_id: str, title: str, content: str, art: bytes | None = None) -> dict[str, Path]:
    where = folder / "products" / product_id
    where.mkdir(parents=True, exist_ok=True)
    files = {"pdf": where / "product.pdf", "cover": where / "cover.png"}
    files["pdf"].write_bytes(pdf(title, content))
    files["cover"].write_bytes(cover(title, art=art))
    return files
