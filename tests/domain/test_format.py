"""Formats: a part's word range and sections, checked by rule."""

from commons.domain.format import Format, has_section, words


def test_words_leave_out_citations():
    assert words("Shade cuts heat stress [archive: web-heat#3] by a lot.") == 7


def test_a_section_is_a_line_starting_with_its_name_whatever_the_markup():
    for heading in ("Risks", "## Risks", "**Risks**", "Risks: two of them", "- risks"):
        assert has_section(f"Evidence\nsome\n{heading}\nmore", "Risks"), heading
    assert not has_section("Evidence\nThe risks are low.", "Risks")  # a mention is not a section


def test_problems_name_what_is_wrong_and_a_good_text_has_none():
    f = Format(5, 8, ("Evidence", "Risks"))
    assert f.problems("Evidence\none two three\nRisks\nfour") == []
    over = f.problems("Evidence\n" + "word " * 20 + "\nRisks\nx")
    assert over == ["it is 23 words; the most is 8"]
    assert f.problems("Evidence\none") == ["it is 2 words; the least is 5",
                                          "it lacks the section(s) Risks (each on a line of its own, starting with its name)"]
    assert Format().problems("anything") == [] and Format().describe() == ""
    assert f.describe() == "5 to 8 words; sections, each on a line starting with its name: Evidence, Risks"
