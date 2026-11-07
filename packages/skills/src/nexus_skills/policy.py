"""Release policy: what happens to a skill given where it came from and what the scan found.

A pure table (openspec 2026-11-07-skill-evolution, S1). The caller supplies the source, the scan verdict and whether
an administrator acknowledged the findings; the result says whether to publish, ask for acknowledgement, send the
skill to human review or refuse it.

====================  ======  ===========================  ===========================
source                safe    caution                      dangerous
====================  ======  ===========================  ===========================
builtin               allow   allow                        allow
admin                 allow   allow                        acknowledge (needs ack)
import                allow   blocked (ack releases)       blocked (ack releases)
agent                 allow   review                       refused
user                  review  review                       refused
private               allow   allow                        refused
====================  ======  ===========================  ===========================

"builtin" skills come from the repository and are imported by a platform administrator, so they are trusted. A
private skill is only ever seen by its owner. ``review`` means a person must approve it before it is published.
"""
from __future__ import annotations

from typing import Literal

Decision = Literal['allow', 'need_ack', 'block', 'review', 'refuse']

SOURCES = ('builtin', 'admin', 'import', 'agent', 'user', 'private')
VERDICTS = ('safe', 'caution', 'dangerous')

_TABLE: dict[str, dict[str, Decision]] = {
    'builtin': {'safe': 'allow', 'caution': 'allow', 'dangerous': 'allow'},
    'admin': {'safe': 'allow', 'caution': 'allow', 'dangerous': 'need_ack'},
    'import': {'safe': 'allow', 'caution': 'block', 'dangerous': 'block'},
    'agent': {'safe': 'allow', 'caution': 'review', 'dangerous': 'refuse'},
    'user': {'safe': 'review', 'caution': 'review', 'dangerous': 'refuse'},
    'private': {'safe': 'allow', 'caution': 'allow', 'dangerous': 'refuse'},
}


def decide(source: str, verdict: str, *, acknowledged: bool = False) -> Decision:
    """Decide what to do with a skill. ``acknowledged`` lifts ``need_ack`` and ``block`` into ``allow``.

    An unknown source or verdict is refused rather than allowed.
    """
    try:
        outcome = _TABLE[source][verdict]
    except KeyError:
        return 'refuse'
    if acknowledged and outcome in ('need_ack', 'block'):
        return 'allow'
    return outcome
