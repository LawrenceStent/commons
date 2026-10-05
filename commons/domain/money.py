"""Money. Every amount is an integer of micro-units (µ): 1 credit (cr) or 1 dollar is 1,000,000 µ. Which currency an
amount is in is the ledger's business (SIM for simulations, USD for a live society; commons/substrate/ledger.py).

`Micros` is an alias of int: a name for readers. It was a NewType until R13 (5 Oct), but money arithmetic (sums,
max, shares) gives plain ints, so a checker demanded a wrapper on every result; the name says it as well."""

from typing import TypeAlias

Micros: TypeAlias = int

MICROS_PER_UNIT = 1_000_000
