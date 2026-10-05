"""P2.1: the storefront's rules, red-teamed. Products for a faith and patriotic audience: devotional, inspirational,
educational or decorative; never trading on real people or trademarks, election claims, health or money promises,
pressure, attacks on others, or copyrighted Bible translations. Rules, not judgement."""

import pytest

from packs.storefront.screen import screen

ALLOWED = [
    ("work", "Day 1: Genesis 1. \"In the beginning God created the heaven and the earth.\" (KJV) Reflect on creation."),
    ("work", "A printable of Psalm 23 in the King James Version, in a classic serif, for a family room wall."),
    ("work", "A study pack on the Bill of Rights for homeschool families: each amendment, a question, a short activity."),
    ("work", "Thank you for your service: a Veterans Day card set to print and colour, with space for a note."),
    ("listing", "Title: 30-Day KJV Bible Reading Plan | Printable PDF\nPrice: 4.99\nTags: bible plan, kjv, devotional"),
    ("work", "Stewardship journal: weekly pages to track giving and saving, with a Proverbs verse on each page."),
    ("brief", "Faith and patriotic printables for Christian families: devotionals, verse art, civics study packs."),
    ("work", "Pray for our nation: a 7-day prayer guide for the country, its leaders and its neighbours (WEB)."),
]

REFUSED = [
    ("work", "Trump 2028 printable wall art with his portrait."),
    ("listing", "Title: Make America Great Again Bible verse poster"),
    ("listing", "Official Billy Graham devotional, endorsed by the ministry."),
    ("work", "The 2020 election was stolen: a prayer guide for the truth to come out."),
    ("work", "Vote for the godly candidate: a printable for your yard."),
    ("listing", "This prayer will heal your cancer and bring financial breakthrough, guaranteed."),
    ("listing", "Only 3 left! Hurry, offer expires tonight."),
    ("work", "Liberals are demonic traitors destroying our country."),
    ("work", "John 3:16 (NIV): For God so loved the world..."),
    ("work", "Verse cards from the English Standard Version."),
    ("listing", "As seen on Fox News: patriot planner"),
]


@pytest.mark.parametrize("kind,text", ALLOWED)
def test_faith_and_patriotic_products_pass(kind, text):
    assert screen(kind, text) is None, screen(kind, text)


@pytest.mark.parametrize("kind,text", REFUSED)
def test_what_the_rules_forbid_is_refused(kind, text):
    assert screen(kind, text)
