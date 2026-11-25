"""Core rename-pattern logic for bulk-rename.

The transformation pipeline, applied to each file's *stem* (name without
extension), runs in a fixed, documented order:

1.  find/replace  (literal substring, optionally case-insensitive) OR
    regex substitution (``--regex`` with capture groups ``\\1`` … ``\\9``)
    — exactly one of the two may be used.
2.  sequential numbering  (``--number``): appends ``-<NNN>`` to the stem,
    numbering files in sorted order.
3.  case transform  (``--lower`` / ``--upper`` / ``--title``) — at most one.
4.  extension change  (``--ext``): replaces the file extension.

Everything here is pure: given a filename it returns the new filename
(or ``None`` when the pattern leaves the name unchanged). Collision
detection and the actual filesystem moves live in :mod:`cli`.
"""

from __future__ import annotations

import re
from dataclasses import dataclass


@dataclass(frozen=True)
class RenameOptions:
    """All rename options that affect the generated target name."""

    find: str | None = None
    replace: str = ""
    case_insensitive: bool = False
    regex: str | None = None
    number: bool = False
    start: int = 1
    pad: int = 3
    lower: bool = False
    upper: bool = False
    title: bool = False
    ext: str | None = None

    def validate(self) -> None:
        """Raise ValueError on contradictory option combinations."""
        if self.find is not None and self.regex is not None:
            raise ValueError("use either --find or --regex, not both")
        if self.regex is not None:
            try:
                re.compile(self.regex)
            except re.error as exc:
                raise ValueError(f"invalid --regex pattern: {exc}") from exc
        if self.pad < 1:
            raise ValueError("--pad must be >= 1")
        if sum((self.lower, self.upper, self.title)) > 1:
            raise ValueError("use at most one of --lower, --upper, --title")
        if self.ext is not None:
            if not self.ext.startswith(".") or len(self.ext) < 2:
                raise ValueError("--ext must look like '.md'")
        if self.number and self.start < 0:
            raise ValueError("--start must be >= 0")
        if self.find is None and self.regex is None and not (
            self.number or self.lower or self.upper or self.title
            or self.ext is not None
        ):
            raise ValueError(
                "nothing to do: give --find/--regex, --number, a case flag, "
                "or --ext"
            )


def split_name(filename: str) -> tuple[str, str]:
    """Split ``name.ext`` into (stem, extension incl. leading dot)."""
    if "." not in filename:
        return filename, ""
    stem, dot, ext = filename.rpartition(".")
    if not stem:  # hidden file such as ".gitignore" — treat as stem
        return filename, ""
    return stem, "." + ext


def apply_case(stem: str, opts: RenameOptions) -> str:
    """Apply the case transform, if any."""
    if opts.lower:
        return stem.lower()
    if opts.upper:
        return stem.upper()
    if opts.title:
        return stem.title()
    return stem


def transform_stem(stem: str, opts: RenameOptions, index: int = 0) -> str:
    """Apply steps 1–3 of the pipeline to a stem.

    ``index`` is the 0-based position of the file in the sorted rename
    list; it only matters when ``--number`` is active.
    """
    result = stem

    # Step 1: find/replace or regex substitution.
    if opts.regex is not None:
        result = re.sub(opts.regex, opts.replace, result)
    elif opts.find is not None:
        if opts.case_insensitive:
            pattern = re.compile(re.escape(opts.find), re.IGNORECASE)
            result = pattern.sub(opts.replace, result)
        else:
            result = result.replace(opts.find, opts.replace)

    # Step 2: sequential numbering, appended as "-<NNN>".
    if opts.number:
        number = opts.start + index
        result = f"{result}-{number:0{opts.pad}d}"

    # Step 3: case transform.
    result = apply_case(result, opts)
    return result


def new_filename(filename: str, opts: RenameOptions, index: int = 0) -> str | None:
    """Return the new filename for ``filename`` under ``opts``.

    Returns ``None`` when the pipeline leaves the name unchanged.
    """
    stem, ext = split_name(filename)
    new_stem = transform_stem(stem, opts, index)
    new_ext = opts.ext if opts.ext is not None else ext
    candidate = new_stem + new_ext
    if candidate == filename or not new_stem:
        return None
    return candidate


def plan_renames(
    filenames: list[str], opts: RenameOptions
) -> list[tuple[str, str]]:
    """Map sorted ``filenames`` to their new names.

    Returns a list of (old, new) pairs, skipping files the pipeline
    leaves unchanged. Deterministic: input order is preserved, and
    numbering follows that order, so callers should pass a sorted list.
    """
    plan: list[tuple[str, str]] = []
    for index, name in enumerate(filenames):
        new = new_filename(name, opts, index)
        if new is not None:
            plan.append((name, new))
    return plan


def detect_collisions(
    plan: list[tuple[str, str]], existing: set[str]
) -> dict[str, str]:
    """Find rename pairs that must be refused.

    Returns ``{old: reason}`` for every pair that would either overwrite
    a file already on disk (``existing`` — excluding files that are
    themselves being renamed away) or collide with another pair's target.
    """
    problems: dict[str, str] = {}
    sources = {old for old, _ in plan}
    targets: dict[str, str] = {}
    for old, new in plan:
        if new in existing and new not in sources:
            problems[old] = f"target '{new}' already exists on disk"
        if new in targets:
            problems[old] = (
                f"target '{new}' also produced by '{targets[new]}'"
            )
            problems.setdefault(
                targets[new],
                f"target '{new}' also produced by '{old}'",
            )
        else:
            targets[new] = old
    return problems
