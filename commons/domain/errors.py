"""Errors the domain raises. A DomainError means code tried something the rules forbid; callers check the rules
first and tell agents why in plain words, so in a correct world one is never raised."""


class DomainError(Exception):
    pass
