"""The storefront's rules (Pack.screen; your decisions, 5 Oct; docs/PHASE2-PLAN.md): products for a faith and patriotic
audience are devotional, inspirational, educational or decorative. Rules, not a model's judgement, and deliberately
broad: a refused draft can be reworded; a takedown, a chargeback or a lawsuit can't be.

    1  no real people's names, likenesses or trademarks, nothing posing as or implying endorsement by a real person,
       church, ministry, network or campaign ("Make America Great Again" and "MAGA" are registered trademarks)
    2  no claims about elections, candidates, voting or campaigns
    3  no health, money or "prayer guarantees results" claims; no fake urgency or scarcity
    4  nothing attacking or demeaning other groups
    5  scripture only from public-domain translations (KJV, WEB): the others are copyrighted beyond small quotes

The screen reads briefs and questions at founding, work at hand-in, and every listing before it reaches the gate.
"""

from __future__ import annotations

import re

# 1. real people, trademarks, endorsements (extend the names as needed; a list, not a judgement)
_PEOPLE = (r"trump|melania|vance|desantis|biden|harris|obama|pence|kirk|graham|osteen|tucker carlson|hannity|"
           r"limbaugh|reagan|kennedy|rfk|musk")
_MARKS = r"make america great again|\bmaga\b|keep america great|america first|turning point|focus on the family|" \
         r"southern baptist convention|fox news|newsmax|\bgop\b|\brnc\b|republican party|democratic party|" \
         r"liberty university|hobby lobby|chick-fil-a"
_ENDORSED = r"\bofficial(ly)?\b|endorsed by|approved by|authori[sz]ed by|licensed by|as seen on|in partnership with"
# 2. elections and campaigns
_ELECTION = r"\belections?\b|\bballots?\b|\bvot(e|es|ing|er|ers)\b|\bcampaign\b|\bcandidates?\b|\b20(2[0-9]|3[0-9])\s+race\b"
# 3. promises and pressure
_PROMISE = (r"\b(heal|heals|healing|cure|cures)\b.{0,30}\b(you|your|cancer|disease|illness)\b|guarantee(d|s)?|"
            r"financial (breakthrough|blessing)s?|get rich|debt.?free (fast|guaranteed)|seed (faith )?offering|"
            r"prayer (will|is guaranteed to|guarantees)")
_PRESSURE = (r"only \d+ left|limited time|act now|last chance|hurry|expires (soon|today|tonight)|while (stocks|supplies) "
             r"last|selling fast")
# 4. attacks on groups
_TARGETS = (r"democrats?|liberals?|leftists?|progressives?|muslims?|jews|jewish|immigrants?|migrants?|gays?|lesbians?|"
            r"trans(gender)?|atheists?|catholics?|mormons?|feminists?|socialists?|communists?")
_INSULTS = r"demonic|evil|traitors?|vermin|scum|enemies|enemy|destroy(ing)?|invaders?|godless|subhuman|filth"
_ATTACK = rf"\b({_INSULTS})\b.{{0,60}}\b({_TARGETS})\b|\b({_TARGETS})\b.{{0,60}}\b({_INSULTS})\b"
# 5. copyrighted translations
_TRANSLATIONS = (r"\b(NIV|ESV|NLT|NASB|NKJV|CSB|HCSB|NRSV|NRSVUE|AMP|MSG|TPT|CEV|GNT)\b|(?i:new international version|"
                 r"english standard version|new living translation|new american standard|new king james|"
                 r"christian standard bible|the message bible|the passion translation|amplified bible)")  # acronyms by case

RULES = (
    (re.compile(rf"\b({_PEOPLE})\b", re.I), "it names a real person: products never trade on real people (rule 1)"),
    (re.compile(_MARKS, re.I), "it uses a trademark or a real organisation's name (rule 1)"),
    (re.compile(_ENDORSED, re.I), "it claims or implies an official status or an endorsement (rule 1)"),
    (re.compile(_ELECTION, re.I), "it touches elections, voting or campaigns: products stay out of politics (rule 2)"),
    (re.compile(_PROMISE, re.I), "it promises health, money or results (rule 3)"),
    (re.compile(_PRESSURE, re.I), "it uses urgency or scarcity to pressure buyers (rule 3)"),
    (re.compile(_ATTACK, re.I), "it attacks or demeans a group of people (rule 4)"),
    (re.compile(_TRANSLATIONS), "it uses a copyrighted Bible translation: use the KJV or the WEB (rule 5)"),
)


def screen(kind: str, text: str) -> str | None:
    """Why this is refused, or None. Every kind of text is held to every rule."""
    for pattern, why in RULES:
        if pattern.search(text):
            return why
    return None
