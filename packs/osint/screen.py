"""The OSINT screen (Pack.screen; commons/application/screening.py): rules over what enters an OSINT society, so that
it never targets a private individual and only ever collects passively (FRAMEWORK.md §7.4). Rules, never a model's
judgement; deliberately broad: a refused public-interest question can be reworded, a leaked address can't be unleaked.

    question     must name its subject's kind: [org], [event], [infrastructure] or [record]; [person] is refused
    everywhere   requests for personal data: home addresses, phone numbers, personal email, dates of birth, family,
                 where someone lives or is, locating or tracking a person, doxxing, people-finder sites
    web_fetch    people-finder sites, and the pages of public registers that are about people (officers, persons
                 with significant control)
    work         personal data in what is handed in: phone numbers, personal email addresses, street addresses,
                 dates of birth
"""

from __future__ import annotations

import re

KINDS = ("org", "event", "infrastructure", "record")
_TAG = re.compile(r"^\s*\[(\w+)\]")

_ASKS = [re.compile(p, re.IGNORECASE) for p in (
    r"\b(home|residential|personal|private)\s+address",
    r"\b(phone|mobile|cell|telephone)\s*(number|no\.?)s?\b",
    r"\bpersonal\s+e-?mails?\b",
    r"\b(date\s+of\s+birth|birth\s*date|d\.?o\.?b\.?)\b",
    r"\b(wife|husband|partner|spouse|children|kids|relatives|parents|family(\s+members)?)\b.{0,40}\b(of|who)\b|"
    r"\b(his|her|their)\s+(wife|husband|partner|spouse|children|kids|relatives|parents|family)\b",
    r"\bwhere\b.{0,60}\b(live|living|lives|stay|staying|reside|resides|work|works|located)\b",
    r"\bmy\s+(neighbou?r|ex|colleague|boss|landlord|tenant|classmate|friend)s?\b",
    r"\b(locate|track(\s+down)?|trace|find)\s+(a|an|this|that|the)?\s*(person|individual|someone|people)\b",
    r"\b(this|that|the)\s+individual'?s\b",
    r"\bdox+(ing|ed)?\b",
    r"\b(licen[cs]e|number)\s+plate",
    r"people[-\s]?(search|finder)|whitepages|spokeo|pipl|192\.com|truepeoplesearch|beenverified|intelius|radaris|"
    r"fastpeoplesearch|peekyou|zabasearch",
)]
_PEOPLE_PAGES = re.compile(r"/(officers|persons-with-significant-control|people|person|profile|directors?)(/|$|\?)",
                           re.IGNORECASE)

_PHONE = re.compile(r"(?<!\d)(\+?\d[\d\s().-]{8,}\d)(?!\d)")
_PERSONAL_EMAIL = re.compile(r"\b[\w.+-]+@(gmail|googlemail|yahoo|hotmail|outlook|live|icloud|me|aol|proton|protonmail|"
                             r"gmx|mail)\.[a-z.]+\b", re.IGNORECASE)
_STREET = re.compile(r"\b\d{1,5}[a-z]?\s+(\w+\s){0,3}(street|st|road|rd|avenue|ave|lane|ln|drive|dr|close|way|crescent|"
                     r"court|ct|place|terrace|grove|boulevard|blvd)\b", re.IGNORECASE)
_BORN = re.compile(r"\bborn\s+(on\s+)?(\d{1,2}\s+\w+|\w+\s+\d{1,2})[,\s]+\d{4}\b", re.IGNORECASE)


def screen(kind: str, text: str) -> str | None:
    """Why this is refused, or None."""
    if kind == "question" and (why := _subject(text)):
        return why
    if kind in ("brief", "question", "web_search") and (why := _asks_for_personal_data(text)):
        return why
    if kind == "web_fetch" and (why := _asks_for_personal_data(text) or _people_page(text)):
        return why
    if kind == "work" and (why := _personal_data(text)):
        return why
    return None


def _subject(question: str) -> str | None:
    m = _TAG.match(question)
    if m is None:
        return f"a question must say what it is about: start it with one of {', '.join(f'[{k}]' for k in KINDS)}"
    if m.group(1).lower() == "person":
        return "subjects are never private individuals: organisations, events, infrastructure and public records only"
    if m.group(1).lower() not in KINDS:
        return f"[{m.group(1)}] isn't a kind of subject here; use one of {', '.join(f'[{k}]' for k in KINDS)}"
    return None


def _asks_for_personal_data(text: str) -> str | None:
    for pattern in _ASKS:
        if pattern.search(text):
            return "it asks for personal data or for a person to be found (no targeting of private individuals)"
    return None


def _people_page(url: str) -> str | None:
    path = "/" + url.split("://", 1)[-1].partition("/")[2]
    return "that page is about people, not organisations" if _PEOPLE_PAGES.search(path) else None


def _personal_data(text: str) -> str | None:
    for name, pattern in (("a phone number", _PHONE), ("a personal email address", _PERSONAL_EMAIL),
                          ("a street address", _STREET), ("a date of birth", _BORN)):
        if pattern.search(text):
            return f"it contains {name}: personal data never goes into the work"
    return None
