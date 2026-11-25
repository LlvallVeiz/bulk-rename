"""bulk-rename: a safe bulk file-renamer CLI.

Rename many files at once with find/replace, regex, sequential numbering,
case transforms and extension changes. Every run is previewable
(--dry-run), refuses to clobber existing files, and writes a JSON journal
so the whole batch can be undone with ``bulk-rename undo``.
"""

__version__ = "1.0.0"
__all__ = ["__version__"]
