"""
Inferring a dbt project's naming patterns (spec §8, D22).

Names are kept as they are; inference only finds the project's default
patterns, so new entities follow its style. For each pattern the import
collects what the pattern's placeholders stand for and the name the project
uses (a hub and its hash key, a satellite and its v0 model, a source table
and its stage, ...). A pattern most of the names follow (at least half, and
two names unless there is only one) is suggested; the report says how many
follow it. Applying it is the caller's choice (the CLI asks, Studio offers it).
"""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass

# Most names of a kind must follow a pattern for it to be suggested.
_SHARE = 0.5


@dataclass(frozen=True)
class Inferred:
    pattern: str
    matching: int
    total: int


def _candidate(values: dict[str, str], name: str) -> str | None:
    """The pattern that gives ``name`` from ``values`` (placeholder -> value).

    Each value is found in the name, longest first; it becomes its
    placeholder. None when a value isn't in the name.
    """
    working = name
    tokens: dict[str, str] = {}
    ordered = sorted(values.items(), key=lambda kv: -len(kv[1]))
    for number, (placeholder, value) in enumerate(ordered):
        if not value:
            return None
        index = working.find(value)
        if index < 0:
            return None
        # A token no name contains, so a later value can't match inside it
        token = f"\x00{number}\x00"
        working = f"{working[:index]}{token}{working[index + len(value) :]}"
        tokens[token] = f"[[ {placeholder} ]]"
    for token, placeholder in tokens.items():
        working = working.replace(token, placeholder)
    return working


def infer(samples: list[tuple[dict[str, str], str]]) -> Inferred | None:
    """The pattern most samples follow, or None.

    ``samples`` are (placeholder values, name) pairs, e.g.
    ``({"entity_name": "customer_h"}, "hk_customer_h")``.
    """
    if not samples:
        return None
    counts: Counter[str] = Counter()
    for values, name in samples:
        candidate = _candidate(values, name)
        if candidate is not None:
            counts[candidate] += 1
    if not counts:
        return None
    pattern, matching = counts.most_common(1)[0]
    total = len(samples)
    if matching / total < _SHARE or (matching < 2 and total > 1):
        return None
    return Inferred(pattern=pattern, matching=matching, total=total)
