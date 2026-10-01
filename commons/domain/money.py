"""Money. Every amount is an integer of micro-units (µ): 1 credit (cr) or 1 dollar is 1,000,000 µ. Which currency an
amount is in is the ledger's business (SIM for simulations, USD for a live society; commons/substrate/ledger.py).

`Micros` is a NewType: an int at run time, a named kind of int to a reader and a type checker."""

from typing import NewType

Micros = NewType("Micros", int)

MICROS_PER_UNIT = 1_000_000
