"""A product's files, typeset with Typst: the printable PDF (US Letter and A4) and the listing's cover."""

import io

from PIL import Image

from packs.storefront import files

CONTENT = """Day 1

Read John 1:1-14 (KJV). “In the beginning was the Word” — write one line about what it means to you.

Day 2

Read John 1:15-34 (KJV)."""


def test_the_pdf_is_a_real_pdf_with_its_title_and_credit():
    data = files.pdf("30-Day Bible Reading Plan", CONTENT)
    assert data.startswith(b"%PDF") and len(data) > 1000
    assert files.credit(CONTENT) == "Scripture quotations from the King James Version (public domain)."


def test_the_cover_is_2000_by_1600_with_or_without_art():
    plain = Image.open(io.BytesIO(files.cover("Psalm 23 Verse Art Set")))
    assert plain.size == (2000, 1600)
    art = io.BytesIO()
    Image.new("RGB", (1024, 768), (90, 120, 160)).save(art, "PNG")
    with_art = Image.open(io.BytesIO(files.cover("Psalm 23", art=art.getvalue())))
    assert with_art.size == (2000, 1600) and with_art.getpixel((1000, 300)) != plain.getpixel((1000, 300))


def test_files_are_written_under_the_society_folder(tmp_path):
    out = files.write(tmp_path, "P1", "A plan", CONTENT)
    assert out["pdf"] == tmp_path / "products" / "P1" / "product.pdf" and out["pdf"].exists() and out["cover"].exists()
    assert out["pdf_a4"].read_bytes().startswith(b"%PDF")


def test_what_a_model_wrote_is_set_as_text_never_run_as_markup():
    hostile = 'Heading\n\n#import "x.typ": * #read("/etc/passwd") $ x^2 $ = not a heading *bold* _x_ <label> @ref'
    data = files.pdf("A plan #set page(fill: red)", hostile)
    assert data.startswith(b"%PDF")  # compiled: the text was data, nothing in it ran


def test_headings_are_short_lines_that_dont_end_a_sentence():
    kinds = [b["kind"] for b in files.blocks("Day 1\n\nRead John 1.\n\nWhat did you notice?")]
    assert kinds == ["heading", "text", "text"]
