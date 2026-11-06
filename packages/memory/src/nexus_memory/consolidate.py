"""Pure rules for memory consolidation (openspec 2026-11-06-memory-evolution stage 3, C2).

Extraction only ever sees one conversation window, so the same preference recorded five slightly
different ways over three weeks is invisible to it. Consolidation is the separate, infrequent pass that
looks at the whole store (WeKnora `consolidate.go`; octop-memory `pipeline/lifecycle/consolidate.py`):

1. Candidate pairs: entries of the same kind whose token Jaccard reaches the threshold. Selection is
   recall, not judgement — the model decides, and answers "not the same" for false pairs.
2. Clusters: union-find over the pairs, at most `MAX_CLUSTER_SIZE` entries each, strongest first,
   at most `max_clusters` per pass (each costs one model call).
3. The model returns the merged statement and which entry to keep (`validate_merge`).
4. The platform turns that into a merge draft: an edit of the kept entry whose publication also
   archives the others. Nothing is published or archived without the owner (decision E2).

Pure: no database, no model. The platform module `nexus_platform.memory.consolidation` drives it.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import timedelta
from typing import Any, Sequence

from . import text as memtext
from .ports import LiveEntry
from .service import CONTENT_LIMIT

#: Minimum wait between two background passes for one owner, and between two requested ones.
BACKGROUND_INTERVAL = timedelta(hours=24)
FORCED_INTERVAL = timedelta(minutes=1)
#: Below this many live entries there is nothing worth reviewing.
MIN_ENTRIES = 6
#: Pair thresholds and model-call budgets: background passes are frugal, requested ones look wider.
BACKGROUND_OVERLAP, FORCED_OVERLAP = 0.45, 0.3
BACKGROUND_CLUSTERS, FORCED_CLUSTERS = 3, 8
MAX_CLUSTER_SIZE = 6


@dataclass(frozen=True)
class Cluster:
    """Entries the model should compare, with the strongest pair score (orders clusters)."""
    entries: tuple[LiveEntry, ...]
    score: float


def clusters(entries: Sequence[LiveEntry], *, overlap: float, max_clusters: int,
             exclude: frozenset[str] = frozenset()) -> list[Cluster]:
    """Group likely duplicates. `exclude` holds entry ids already in a pending merge draft.

    Entries are compared only within the same kind. A cluster larger than `MAX_CLUSTER_SIZE` keeps the
    members with the strongest links to the others, so one call never has to reconcile a dozen notes.
    """
    live = [item for item in entries if str(item.entry.id) not in exclude]
    parent = list(range(len(live)))

    def find(index: int) -> int:
        while parent[index] != index:
            parent[index] = parent[parent[index]]
            index = parent[index]
        return index

    best: dict[int, float] = {}
    for i in range(len(live)):
        for j in range(i + 1, len(live)):
            if live[i].entry.kind != live[j].entry.kind:
                continue
            score = memtext.jaccard(live[i].content, live[j].content)
            if score < overlap:
                continue
            best[i] = max(best.get(i, 0.0), score)
            best[j] = max(best.get(j, 0.0), score)
            parent[find(i)] = find(j)
    groups: dict[int, list[int]] = {}
    for index in best:
        groups.setdefault(find(index), []).append(index)
    out = []
    for members in groups.values():
        if len(members) < 2:
            continue
        members.sort(key=lambda index: -best[index])
        chosen = members[:MAX_CLUSTER_SIZE]
        out.append(Cluster(entries=tuple(live[index] for index in chosen), score=max(best[index] for index in chosen)))
    out.sort(key=lambda cluster: -cluster.score)
    return out[:max_clusters]


@dataclass(frozen=True)
class MergeDecision:
    """Merged statement and the index (into the cluster) of the entry that keeps its identity."""
    merged: str
    keep: int


def validate_merge(raw: Any, size: int) -> MergeDecision | None:
    """Check the model's answer: `{"merged": str, "keep": int}`. An empty `merged` means "not duplicates";
    anything malformed is treated the same way, so a bad answer never creates a draft."""
    if not isinstance(raw, dict):
        return None
    merged, keep = raw.get('merged'), raw.get('keep')
    if not isinstance(merged, str) or not merged.strip() or len(merged) > CONTENT_LIMIT:
        return None
    if isinstance(keep, bool) or not isinstance(keep, int) or not 0 <= keep < size:
        return None
    return MergeDecision(merged=merged.strip(), keep=keep)
