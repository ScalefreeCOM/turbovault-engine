"""
Inferring a dbt project's settings from its models (spec §8, D22, D28).

Names and values are kept as they are; inference only finds the project's
defaults, so new entities follow its style and imported ones store less.
For each setting the import collects samples: what a pattern's placeholders
stand for and the name or value the project uses (a hub and its hash key, a
source table and its stage, a model's folder and its group, ...). A value
most samples follow (at least half, and two unless there is only one) is
suggested; the report says how many follow it. Applying it is the caller's
choice (the CLI asks, Studio offers it).
"""

from __future__ import annotations

import re
from collections import Counter
from collections.abc import Hashable, Iterable, Mapping, Sequence
from dataclasses import dataclass
from itertools import combinations
from typing import Any

from engine.services.generation.folder_config import FolderConfig, folder_name

# Most samples must follow a value for it to be suggested.
_SHARE = 0.5
_PLACEHOLDER = re.compile(r"\[\[\s*(\w+)\s*\]\]")


@dataclass(frozen=True)
class Inferred:
    value: Any
    matching: int
    total: int


def _enough(value: Any, matching: int, total: int) -> Inferred | None:
    if not total or matching / total < _SHARE or (matching < 2 and total > 1):
        return None
    return Inferred(value=value, matching=matching, total=total)


def _best(counts: Mapping[Any, int], *, prefer: Any, rank=None) -> tuple[Any, int]:
    """The most common candidate; ``prefer`` (the current setting) wins a
    tie, then the highest ``rank``, then the first found."""
    top = max(counts.values())
    tied = [value for value, count in counts.items() if count == top]
    if prefer in tied:
        return prefer, top
    if rank is not None:
        tied.sort(key=rank, reverse=True)  # stable: first found among equals
    return tied[0], top


def majority(values: Sequence[Hashable], *, prefer: Any = None) -> Inferred | None:
    """The value most samples have, or None."""
    if not values:
        return None
    value, matching = _best(Counter(values), prefer=prefer)
    return _enough(value, matching, len(values))


# -- naming patterns ---------------------------------------------------------


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


def infer(
    samples: list[tuple[dict[str, str], str]], *, prefer: str | None = None
) -> Inferred | None:
    """The naming pattern most samples follow, or None.

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
    if prefer and prefer not in counts:
        # The current pattern, however it is spaced, counts the names it gives
        given = sum(1 for values, name in samples if _fill(prefer, values) == name)
        if given:
            counts[prefer] = given
    if not counts:
        return None
    pattern, matching = _best(counts, prefer=prefer)
    return _enough(pattern, matching, len(samples))


# -- values with optional placeholders (record source, load date) -------------


def _fill(pattern: str, values: Mapping[str, str]) -> str:
    return _PLACEHOLDER.sub(lambda m: values.get(m.group(1), m.group(0)), pattern)


def _occurrences(text: str, value: str) -> list[int]:
    """Where ``value`` stands in ``text`` as a word of its own (not inside
    another word: ``crm`` in ``crm_ts``, not ``a`` in ``load``)."""
    found = []
    start = text.find(value)
    while value and start >= 0:
        end = start + len(value)
        before = text[start - 1] if start else ""
        after = text[end] if end < len(text) else ""
        if not before.isalnum() and not after.isalnum():
            found.append(start)
        start = text.find(value, start + 1)
    return found


def _value_candidates(values: Mapping[str, str], text: str) -> set[str]:
    """Every pattern that gives ``text``: any of the values found in it
    (as words of their own) replaced by their placeholders."""
    found = [
        (name, value)
        for name, value in sorted(values.items(), key=lambda kv: -len(kv[1]))
        if value and _occurrences(text, value)
    ]
    candidates = {text}
    for size in range(1, len(found) + 1):
        for chosen in combinations(found, size):
            working = text
            tokens = {}
            for number, (name, value) in enumerate(chosen):
                token = f"\x00{number}\x00"
                working = re.sub(
                    rf"(?<![A-Za-z0-9]){re.escape(value)}(?![A-Za-z0-9])",
                    token,
                    working,
                )
                tokens[token] = f"[[ {name} ]]"
            for token, placeholder in tokens.items():
                working = working.replace(token, placeholder)
            candidates.add(working)
    return candidates


def infer_value(
    samples: list[tuple[Mapping[str, str], str | None]],
    *,
    prefer: str | None = None,
) -> Inferred | None:
    """The value most samples have, placeholders and all, or None.

    ``samples`` are (placeholder values, value) pairs, e.g.
    ``({"source_system": "crm", "source_table": "orders"}, "!crm.orders")``;
    a None value counts as a sample without it. A pattern counts every sample
    it gives; among equally common ones the most general wins.
    """
    if not samples:
        return None
    candidates: set[str] = {prefer} if prefer else set()
    for values, text in samples:
        if text:
            candidates |= _value_candidates(values, text)
    counts = {
        candidate: sum(
            1 for values, text in samples if text and _fill(candidate, values) == text
        )
        for candidate in sorted(candidates)
    }
    counts = {candidate: count for candidate, count in counts.items() if count}
    if not counts:
        return None
    pattern, matching = _best(
        counts, prefer=prefer, rank=lambda p: len(_PLACEHOLDER.findall(p))
    )
    return _enough(pattern, matching, len(samples))


# -- folders --------------------------------------------------------------------


@dataclass(frozen=True)
class FolderSample:
    """A model's folder, with what its placeholders would stand for."""

    folder: str
    group: str | None = None
    source_system: str | None = None


def _replaced(parts: list[str], index: int, placeholder: str) -> list[str]:
    return [*parts[:index], f"[[ {placeholder} ]]", *parts[index + 1 :]]


def _folder_candidates(sample: FolderSample) -> set[str]:
    """Patterns that give the sample's folder: the deepest folder named like
    its group, and the one named like its source system, become their
    placeholders (lowercase or as spelled)."""
    parts = sample.folder.split("/")
    variants = [parts]
    for value, short, spelled in (
        (sample.group, "group", "group_name"),
        (sample.source_system, "source_system", "source_system_name"),
    ):
        if not value:
            continue
        # Not the model path itself (models/)
        index = next(
            (
                i
                for i in range(len(parts) - 1, 0, -1)
                if parts[i] in (folder_name(value), value)
            ),
            None,
        )
        if index is None:
            continue
        for variant in list(variants):
            if "[[" in variant[index]:
                continue  # the group's folder is the system's too
            if variant[index] == folder_name(value):
                variants.append(_replaced(variant, index, short))
            if variant[index] == value:
                variants.append(_replaced(variant, index, spelled))
    return {"/".join(variant) for variant in variants}


def _filled(pattern: str, sample: FolderSample) -> str:
    return FolderConfig({"raw_vault": pattern}).folder(
        "raw_vault", group=sample.group, source_system=sample.source_system
    )


def _gives(pattern: str, sample: FolderSample) -> bool:
    return _filled(pattern, sample) == sample.folder


def _under(pattern: str, sample: FolderSample) -> bool:
    """Whether the sample's folder is the pattern's folder or inside it."""
    folder = _filled(pattern, sample)
    return sample.folder == folder or sample.folder.startswith(f"{folder}/")


# A folder name is one of many, not part of the structure, when the models
# beside it in other folders are at least this share of all
_VARYING_SHARE = 0.2


def _varying_part(pattern: str, samples: Counter[FolderSample]) -> int | None:
    """The first fixed folder of ``pattern`` that is one of several the
    models use in its place (e.g. a folder per source: ``crm/``, ``erp/``,
    ``web/``), or None.

    A placeholder can't stand for it, so the pattern ends above it: models
    keep their own folders below.
    """
    parts = pattern.split("/")
    total = sum(samples.values())
    for index in range(1, len(parts)):
        if _PLACEHOLDER.search(parts[index]):
            continue
        above = "/".join(parts[:index])
        others: Counter[str] = Counter()
        for sample, count in samples.items():
            folder = _filled(above, sample)
            if not sample.folder.startswith(f"{folder}/"):
                continue
            name = sample.folder[len(folder) + 1 :].split("/")[0]
            if name != parts[index]:
                others[name] += count
        if len(others) >= 2 and sum(others.values()) >= _VARYING_SHARE * total:
            return index
    return None


def _folder_rank(pattern: str) -> tuple[int, int]:
    names = _PLACEHOLDER.findall(pattern)
    # More placeholders first; the lowercase forms over the spelled ones
    return len(names), -sum(1 for name in names if name.endswith("_name"))


def infer_folder(
    samples: Iterable[FolderSample],
    *,
    prefer: str | None = None,
    context: Iterable[FolderSample] = (),
) -> Inferred | None:
    """The folder pattern most models follow, or None.

    A pattern counts every model whose folder it gives (a model without a
    group drops the group's folder). ``prefer`` is the current pattern: it
    wins a tie, so a project already set up suggests nothing. Where the
    models' folders differ by a name no placeholder stands for (a folder per
    source below the group), the pattern ends above it and counts the models
    inside it. ``context``: more models of the layer, to tell such a folder
    from a fixed one when there are few samples.
    """
    distinct = Counter(s for s in samples if s.folder)
    if not distinct:
        return None
    total = sum(distinct.values())
    candidates: set[str] = set()
    for sample in distinct:
        candidates |= _folder_candidates(sample)
    if prefer:
        candidates.add(prefer)
    counts = {
        candidate: sum(n for s, n in distinct.items() if _gives(candidate, s))
        for candidate in sorted(candidates)
    }
    counts = {candidate: count for candidate, count in counts.items() if count}
    if not counts:
        return None
    pattern, matching = _best(counts, prefer=prefer, rank=_folder_rank)
    varying = _varying_part(pattern, distinct + Counter(context))
    if varying is not None:
        pattern = "/".join(pattern.split("/")[:varying])
        matching = sum(n for s, n in distinct.items() if _under(pattern, s))
    return _enough(pattern, matching, total)
