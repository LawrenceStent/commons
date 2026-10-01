"""What happens around every command, in order, declared where the command is defined:

    lock       the world's lock is held for the whole command, so parallel turns change state one action at a time
               (web reads declare `lock=False`: they take the lock themselves, around everything but the network)
    log        the call, its arguments and its outcome go to the activity log, refused or not
    operator   the operator's limits are world rules, checked before the command runs, whatever the agent decided

    @command()                     lock, log, operator
    @command(log=False)            lock only: runtime hooks the LLM runtime calls about itself
    @command(lock=False)           log and operator, no lock
"""

from __future__ import annotations

import functools
import inspect

from commons.application.observation import Outcome
from commons.substrate.activity import logged


def _operated(name, fn):
    sig = inspect.signature(fn)

    def wrapper(self, *a, **kw):
        try:
            args = {k: v for k, v in sig.bind(self, *a, **kw).arguments.items() if k != "self"}
        except TypeError:
            args = {}
        if why := self.operator_refusal(name, args):
            return Outcome(False, why)
        return fn(self, *a, **kw)

    return functools.wraps(fn)(wrapper)  # keeps fn's signature visible to the logging wrapper


def _locked(fn):
    def wrapper(self, *a, **kw):
        with self.w.lock:
            return fn(self, *a, **kw)

    wrapper.__name__, wrapper.__doc__ = fn.__name__, fn.__doc__
    return wrapper


def command(*, log: bool = True, lock: bool = True):
    def wrap(fn):
        f = logged(fn.__name__, _operated(fn.__name__, fn)) if log else fn
        return _locked(f) if lock else f
    return wrap
