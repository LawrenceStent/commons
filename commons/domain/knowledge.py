"""Knowledge: playbooks, the written methods co-ops publish to the commons library and cite when they use them."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass
class Playbook:
    id: str
    author: str
    capability: str
    title: str = ""
    text: str = ""
    uses: int = 0
