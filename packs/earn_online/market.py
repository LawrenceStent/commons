"""The earn-online pack's mock market: small, cheap, gradeable launch-kit jobs for everyday products.

Every part is a few lines a model can write and a grader can judge in one call.
"""

from sim.pack import TemplateWorkSource

SUBJECTS = (
    "a reusable coffee cup", "a budgeting app for students", "a bike repair kit",
    "a sleep-tracking ring", "a sourdough starter kit", "a plant-watering sensor",
    "a language-learning podcast", "a standing desk converter", "a trail running vest",
    "a password manager for families", "a home composting bin", "a noise-cancelling kids' headset",
)

TEMPLATES: dict[str, tuple[str, str]] = {  # in this order: same seed, same jobs
    "research": (
        "List the three considerations a buyer of {subject} cares about most, one line each.",
        "Exactly three lines; each is specific to {subject}, not generic; no marketing fluff.",
    ),
    "build": (
        "Write a Python function `validate_order(order: dict) -> list[str]` for {subject} orders "
        "with keys name, qty, unit_price. Return a list of error strings; empty if valid.",
        "Valid Python; checks presence and types of all three keys; qty must be a positive int; "
        "unit_price a non-negative number; at most 20 lines.",
    ),
    "design": (
        "Propose a product name and a tagline of at most six words for {subject}.",
        "Name is original and pronounceable; tagline is at most six words and says what it does.",
    ),
    "write": (
        "Write a product description of 50 to 70 words for {subject}.",
        "Between 50 and 70 words; concrete benefits; no invented certifications or statistics.",
    ),
}

WORK_SOURCE = TemplateWorkSource(SUBJECTS, TEMPLATES, title="Launch kit for {subject}")
