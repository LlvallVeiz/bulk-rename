"""Command-line interface for bulk-rename.

Subcommands::

    bulk-rename rename <dir> [options...]   rename files in <dir>
    bulk-rename preview <dir> [options...]  same as rename --dry-run
    bulk-rename undo [--journal PATH] [--dir DIR]

Safety rules enforced here:

* Files only — directories are never renamed.
* Hidden files are skipped unless ``--include-hidden`` is given.
* The journal file itself is never renamed.
* A target that already exists on disk, or that two sources would both
  produce, is refused: that pair is reported and skipped, the rest of
  the batch still runs, and the process exits non-zero.
* Without ``--yes``, the preview is printed and the user is asked to
  confirm; when stdin is not a TTY the run refuses to apply unless
  ``--dry-run`` or ``--yes`` was given.
* Every successful apply writes a JSON journal (see :mod:`journal`)
  so the batch can be undone.
"""

from __future__ import annotations

import argparse
import fnmatch
import os
import sys
from pathlib import Path

from . import __version__
from .journal import (
    DEFAULT_JOURNAL_NAME,
    Journal,
    default_journal_path,
    read_journal,
    write_journal,
)
from .renamer import RenameOptions, detect_collisions, plan_renames


def collect_files(
    directory: Path,
    recursive: bool,
    include_hidden: bool,
    include_patterns: list[str] | None,
) -> list[str]:
    """Return the sorted, relative file names in ``directory`` to rename.

    Directories are skipped. Hidden files (any path component starting
    with ``.``) are skipped unless ``include_hidden`` is set. When
    ``include_patterns`` is given (e.g. ``["*.jpg", "*.png"]``), only
    files whose name matches one of the glob patterns are kept.
    """
    if recursive:
        paths = sorted(p for p in directory.rglob("*") if p.is_file())
    else:
        paths = sorted(p for p in directory.iterdir() if p.is_file())

    names: list[str] = []
    for path in paths:
        rel = path.relative_to(directory).as_posix()
        parts = rel.split("/")
        if not include_hidden and any(p.startswith(".") for p in parts):
            continue
        if rel == DEFAULT_JOURNAL_NAME:
            continue  # never rename the journal itself
        if include_patterns and not any(
            fnmatch.fnmatchcase(path.name, pat) for pat in include_patterns
        ):
            continue
        names.append(rel)
    return names


def print_preview(plan: list[tuple[str, str]], problems: dict[str, str]) -> None:
    """Print the old -> new table, marking refused pairs."""
    if not plan:
        print("Nothing to rename: no file matches the given options.")
        return
    width = max(len(old) for old, _ in plan)
    print(f"{'OLD':<{width}}  ->  NEW")
    print("-" * (width + 8))
    for old, new in plan:
        if old in problems:
            print(f"{old:<{width}}  ->  {new}   [SKIPPED: {problems[old]}]")
        else:
            print(f"{old:<{width}}  ->  {new}")


def build_options(args: argparse.Namespace) -> RenameOptions:
    """Translate parsed CLI args into a validated RenameOptions."""
    opts = RenameOptions(
        find=args.find,
        replace=args.replace or "",
        case_insensitive=args.case_insensitive,
        regex=args.regex,
        number=args.number,
        start=args.start,
        pad=args.pad,
        lower=args.lower,
        upper=args.upper,
        title=args.title,
        ext=args.ext,
    )
    opts.validate()
    return opts


def parse_include(value: str | None) -> list[str] | None:
    """Split ``--include '*.jpg,*.png'`` into a glob list."""
    if not value:
        return None
    return [p.strip() for p in value.split(",") if p.strip()]


def cmd_rename(args: argparse.Namespace, *, dry_run: bool) -> int:
    """Run the rename (or preview-only) subcommand."""
    directory = Path(args.dir)
    if not directory.is_dir():
        print(f"error: not a directory: {args.dir}", file=sys.stderr)
        return 2

    try:
        opts = build_options(args)
    except ValueError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2

    files = collect_files(
        directory,
        recursive=args.recursive,
        include_hidden=args.include_hidden,
        include_patterns=parse_include(args.include),
    )
    plan = plan_renames(files, opts)
    existing = {p.relative_to(directory).as_posix() for p in directory.rglob("*") if p.is_file()}
    problems = detect_collisions(plan, existing)

    print_preview(plan, problems)
    if not plan:
        return 0

    skipped = len(problems)
    if skipped:
        print(f"\n{skipped} rename(s) will be skipped due to collisions.")

    if dry_run:
        print("\nDry run: no files were changed.")
        return 1 if skipped else 0

    if not args.yes:
        if not sys.stdin.isatty():
            print(
                "error: refusing to apply without --yes or --dry-run "
                "when stdin is not a terminal.",
                file=sys.stderr,
            )
            return 2
        answer = input("\nApply these renames? [y/N] ").strip().lower()
        if answer not in ("y", "yes"):
            print("Aborted: no files were changed.")
            return 0

    # Apply, in the planned (sorted) order. If any target is itself a
    # source in this batch (a chain such as A->B, B->C), rename everything
    # to unique temp names first, then to the final targets — otherwise
    # os.rename would fail on the still-existing target.
    todo = [(old, new) for old, new in plan if old not in problems]
    sources = {old for old, _ in plan}
    chained = any(new in sources for _, new in todo)
    staged: list[tuple[str, str]] = []  # (current path, final target)
    if chained:
        for i, (old, new) in enumerate(todo):
            tmp = f".bulk-rename-tmp-{i}"
            try:
                os.rename(directory / old, directory / tmp)
            except OSError as exc:
                print(f"FAILED {old} -> {new}: {exc}", file=sys.stderr)
                problems[old] = str(exc)
                continue
            staged.append((tmp, new))
    else:
        staged = list(todo)

    applied: list[dict[str, str]] = []
    for current, new in staged:
        old = next(o for o, n in plan if n == new)
        src, dst = directory / current, directory / new
        dst.parent.mkdir(parents=True, exist_ok=True)
        try:
            os.rename(src, dst)
        except OSError as exc:
            print(f"FAILED {old} -> {new}: {exc}", file=sys.stderr)
            problems[old] = str(exc)
            continue
        applied.append({"old": old, "new": new})
        print(f"renamed: {old} -> {new}")

    if applied:
        journal_path = (
            Path(args.journal) if args.journal
            else Path(default_journal_path(str(directory)))
        )
        write_journal(
            str(journal_path),
            Journal(directory=str(directory.resolve()), renames=applied),
        )
        print(f"\nJournal written to {journal_path} ({len(applied)} renames).")
        print("Undo with: bulk-rename undo --journal "
              f"{journal_path}")

    if problems:
        print(
            f"\nDone with {len(problems)} skipped/failed rename(s).",
            file=sys.stderr,
        )
        return 1
    print(f"\nDone: {len(applied)} file(s) renamed.")
    return 0


def cmd_undo(args: argparse.Namespace) -> int:
    """Rename everything in a journal back to its original name."""
    directory = Path(args.dir) if args.dir else Path.cwd()
    journal_path = Path(args.journal) if args.journal else None
    if journal_path is None:
        journal_path = Path(default_journal_path(str(directory)))
    if not journal_path.is_file():
        print(f"error: journal not found: {journal_path}", file=sys.stderr)
        return 2

    try:
        journal = read_journal(str(journal_path))
    except (ValueError, KeyError, OSError) as exc:
        print(f"error: cannot read journal: {exc}", file=sys.stderr)
        return 2

    base = Path(journal.directory) if os.path.isdir(journal.directory) else directory
    restored = missing = blocked = 0
    # Undo in reverse order, so a chain A->B, B->C unwinds cleanly.
    for entry in reversed(journal.renames):
        src, dst = base / entry["new"], base / entry["old"]
        if not src.exists():
            print(f"SKIPPED {entry['new']}: no longer exists")
            missing += 1
            continue
        if dst.exists():
            print(f"SKIPPED {entry['new']}: '{entry['old']}' already exists")
            blocked += 1
            continue
        try:
            os.rename(src, dst)
        except OSError as exc:
            print(f"FAILED {entry['new']}: {exc}", file=sys.stderr)
            blocked += 1
            continue
        print(f"restored: {entry['new']} -> {entry['old']}")
        restored += 1

    print(f"\nUndo complete: {restored} restored, {missing} missing, "
          f"{blocked} blocked.")
    try:
        journal_path.unlink()
        print(f"Journal removed: {journal_path}")
    except OSError:
        pass
    return 1 if (missing or blocked) else 0


def _add_rename_options(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--find", metavar="TEXT",
                        help="literal substring to replace")
    parser.add_argument("--replace", metavar="TEXT", default="",
                        help="replacement text (default: empty)")
    parser.add_argument("--case-insensitive", action="store_true",
                        help="case-insensitive --find matching")
    parser.add_argument("--regex", metavar="PATTERN",
                        help="regex pattern with capture groups, e.g. "
                        "'IMG_(\\d+)' (use --replace 'photo-\\1')")
    parser.add_argument("--number", action="store_true",
                        help="append sequential numbering -<NNN>")
    parser.add_argument("--start", type=int, default=1,
                        help="first number (default: 1)")
    parser.add_argument("--pad", type=int, default=3,
                        help="zero-padding width (default: 3)")
    parser.add_argument("--lower", action="store_true",
                        help="lowercase the name")
    parser.add_argument("--upper", action="store_true",
                        help="uppercase the name")
    parser.add_argument("--title", action="store_true",
                        help="title-case the name")
    parser.add_argument("--ext", metavar=".EXT",
                        help="change the extension, e.g. '.md'")
    parser.add_argument("--recursive", action="store_true",
                        help="rename files in subdirectories too")
    parser.add_argument("--include", metavar="'*.jpg,*.png'",
                        help="only rename files matching these globs "
                        "(comma-separated)")
    parser.add_argument("--include-hidden", action="store_true",
                        help="also rename hidden files (dotfiles)")
    parser.add_argument("--dry-run", action="store_true",
                        help="preview only, change nothing")
    parser.add_argument("--yes", action="store_true",
                        help="apply without asking for confirmation")
    parser.add_argument("--journal", metavar="PATH",
                        help="where to write the undo journal "
                        "(default: <dir>/.bulk-rename-journal.json)")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="bulk-rename",
        description="Rename many files at once — safely, with preview "
                    "and undo.",
    )
    parser.add_argument("--version", action="version",
                        version=f"%(prog)s {__version__}")
    sub = parser.add_subparsers(dest="command", required=True)

    p_rename = sub.add_parser(
        "rename", help="rename files in a directory")
    p_rename.add_argument("dir", help="directory containing the files")
    _add_rename_options(p_rename)
    p_rename.set_defaults(func=lambda a: cmd_rename(a, dry_run=a.dry_run))

    p_preview = sub.add_parser(
        "preview", help="preview renames without changing anything")
    p_preview.add_argument("dir", help="directory containing the files")
    _add_rename_options(p_preview)
    p_preview.set_defaults(func=lambda a: cmd_rename(a, dry_run=True))

    p_undo = sub.add_parser("undo", help="undo the last rename batch")
    p_undo.add_argument("--journal", metavar="PATH",
                        help="journal file to undo "
                        "(default: <dir>/.bulk-rename-journal.json)")
    p_undo.add_argument("--dir", metavar="DIR",
                        help="directory the journal lives in "
                        "(default: current directory)")
    p_undo.set_defaults(func=cmd_undo)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
