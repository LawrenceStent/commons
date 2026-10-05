"""The OSINT pack's work: investigation questions about organisations, events, infrastructure and public records,
taken apart into collect (find public sources), analyse (what they show, how sure), report (answer the question)
and verify (check the others' citations). Verify is independent: bought from a co-op that did no other part, once the
others are done; its contract carries their work (commons/domain/market.py `contract_spec`).

Questions name their subject's kind ([org], [event], [infrastructure], [record]): the screen refuses anything else
(packs/osint/screen.py). A society's own questions (societies/<name>/questions.md) replace the defaults below.
"""

from commons.domain.format import Format
from commons.domain.pack import TemplateWorkSource

SUBJECTS = (
    "[event] What is the public timeline of the 2024 CrowdStrike outage, and what did it disrupt?",
    "[infrastructure] Who operates the Thames Barrier, and how often has it been closed?",
    "[org] What do public sources say about how the Port of Rotterdam handles congestion?",
    "[record] What do public filings show about the structure of a large listed utility?",
    "[event] What happened in the 2021 Suez Canal blockage, and what did it cost shipping?",
    "[infrastructure] Which bodies maintain the UK's national electricity grid, and what failed in the 2019 blackout?",
    "[org] How is the International Committee of the Red Cross funded, according to its own reports?",
    "[record] What do public procurement records show about a large national rail contract?",
)

SOURCING = ("Every factual claim cites a source as [archive: <id>]; nothing is stated as fact without one. Only public "
            "sources; no personal data about anyone.")

TEMPLATES: dict[str, tuple[str, str]] = {  # in this order: same seed, same jobs
    "collect": (
        "Find public sources on this question: {subject} List at least three, each with what it says that bears on "
        "the question.",
        "At least three distinct sources, numbered, each cited as [archive: <id>] with one or two sentences on what "
        "it says; sources independent of each other where possible, and any that repeat another said so. " + SOURCING,
    ),
    "analyse": (
        "Analyse what the public sources show about this question: {subject}",
        "Three labelled sections: Findings (each finding cited), Confidence (high, medium or low for each finding, "
        "and why), Gaps (what the sources don't settle). 150 to 350 words. " + SOURCING,
    ),
    "report": (
        "Write a short report answering this question for a reader who will check every claim: {subject}",
        "Three labelled sections: Answer, Confidence, Unknowns. 200 to 400 words, plain language, every claim cited, "
        "no claim stronger than its sources. " + SOURCING,
    ),
    "verify": (
        "Check the work done on this question: {subject} For each cited claim, say whether its source supports it, "
        "contradicts it, or can't be checked from the archive.",
        "Every cited claim in the work listed with a verdict (supported, contradicted or unverifiable) and the "
        "passage that decides it; claims without a citation flagged; ending with the tally line 'Supported: N of M. "
        "Contradicted: K.' over the M cited claims (a contradicted claim fails the job; pay scales with the share "
        "supported). Checks the work as given; adds no new claims.",
    ),
}

FORMATS = {
    "analyse": Format(150, 350, ("Findings", "Confidence", "Gaps")),
    "report": Format(200, 400, ("Answer", "Confidence", "Unknowns")),
    "verify": Format(tally=True),
}

WORK_SOURCE = TemplateWorkSource(SUBJECTS, TEMPLATES, formats=FORMATS, independent=frozenset({"verify"}))
