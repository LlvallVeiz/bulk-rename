"""Tests for bulk-rename (stdlib unittest, no third-party packages)."""

import json
import os
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from bulk_rename.cli import cmd_rename, cmd_undo, main  # noqa: E402
from bulk_rename.renamer import (  # noqa: E402
    RenameOptions,
    detect_collisions,
    new_filename,
    plan_renames,
)


def make_args(**overrides):
    """A minimal argparse-like namespace for cmd_rename / cmd_undo."""
    import argparse

    args = argparse.Namespace(
        dir="",
        find=None,
        replace="",
        case_insensitive=False,
        regex=None,
        number=False,
        start=1,
        pad=3,
        lower=False,
        upper=False,
        title=False,
        ext=None,
        recursive=False,
        include=None,
        include_hidden=False,
        dry_run=False,
        yes=True,
        journal=None,
    )
    args.__dict__.update(overrides)
    return args


class RenamerUnitTests(unittest.TestCase):
    def test_regex_with_capture_groups(self):
        opts = RenameOptions(regex=r"IMG_(\d+)", replace=r"photo-\1")
        self.assertEqual(new_filename("IMG_0042.jpg", opts), "photo-0042.jpg")
        self.assertIsNone(new_filename("vacation.jpg", opts))

    def test_numbering_start_and_pad(self):
        opts = RenameOptions(number=True, start=5, pad=4)
        plan = plan_renames(["a.txt", "b.txt", "c.txt"], opts)
        self.assertEqual(
            plan,
            [("a.txt", "a-0005.txt"), ("b.txt", "b-0006.txt"),
             ("c.txt", "c-0007.txt")],
        )

    def test_find_replace_and_case_transform(self):
        opts = RenameOptions(find="draft", replace="final", upper=True)
        self.assertEqual(new_filename("draft_notes.txt", opts),
                         "FINAL_NOTES.txt")
        opts_ci = RenameOptions(find="DRAFT", replace="final",
                                case_insensitive=True)
        self.assertEqual(new_filename("draft_notes.txt", opts_ci),
                         "final_notes.txt")

    def test_extension_change(self):
        opts = RenameOptions(ext=".md")
        self.assertEqual(new_filename("notes.txt", opts), "notes.md")
        self.assertIsNone(new_filename("notes.md", opts))

    def test_nothing_to_do_is_rejected(self):
        with self.assertRaises(ValueError):
            RenameOptions().validate()
        with self.assertRaises(ValueError):
            RenameOptions(find="a", regex="b").validate()
        with self.assertRaises(ValueError):
            RenameOptions(regex="([unclosed").validate()
        with self.assertRaises(ValueError):
            RenameOptions(ext="md").validate()

    def test_collision_detection(self):
        # Target already on disk.
        plan = [("a.txt", "b.txt")]
        problems = detect_collisions(plan, existing={"b.txt", "a.txt"})
        self.assertIn("a.txt", problems)
        # Two sources mapping to the same target.
        plan = [("a.txt", "same.txt"), ("b.txt", "same.txt")]
        problems = detect_collisions(plan, existing={"a.txt", "b.txt"})
        self.assertEqual(set(problems), {"a.txt", "b.txt"})
        # Target that is itself renamed away is fine (a chain).
        plan = [("a.txt", "b.txt"), ("b.txt", "c.txt")]
        self.assertEqual(detect_collisions(plan, {"a.txt", "b.txt"}), {})


class CliIntegrationTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    def touch(self, *names):
        for name in names:
            path = self.dir / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text("x", encoding="utf-8")

    def ls(self):
        return sorted(p.name for p in self.dir.iterdir() if p.is_file())

    def test_dry_run_makes_no_changes(self):
        self.touch("IMG_0001.jpg", "IMG_0002.jpg")
        code = cmd_rename(
            make_args(dir=str(self.dir), regex=r"IMG_(\d+)",
                      replace=r"photo-\1", dry_run=True),
            dry_run=True,
        )
        self.assertEqual(code, 0)
        self.assertEqual(self.ls(), ["IMG_0001.jpg", "IMG_0002.jpg"])
        self.assertFalse((self.dir / ".bulk-rename-journal.json").exists())

    def test_regex_rename_and_undo(self):
        self.touch("IMG_0001.jpg", "IMG_0002.jpg")
        code = cmd_rename(
            make_args(dir=str(self.dir), regex=r"IMG_(\d+)",
                      replace=r"photo-\1"),
            dry_run=False,
        )
        self.assertEqual(code, 0)
        self.assertEqual(self.ls(),
                         [".bulk-rename-journal.json", "photo-0001.jpg",
                          "photo-0002.jpg"])
        journal = json.loads(
            (self.dir / ".bulk-rename-journal.json").read_text())
        self.assertEqual(len(journal["renames"]), 2)

        code = cmd_undo(make_args(dir=str(self.dir)))
        self.assertEqual(code, 0)
        self.assertEqual(self.ls(), ["IMG_0001.jpg", "IMG_0002.jpg"])

    def test_collision_refused_and_exit_nonzero(self):
        self.touch("a.txt", "b.txt")
        code = cmd_rename(
            make_args(dir=str(self.dir), find="a", replace="b"),
            dry_run=False,
        )
        self.assertNotEqual(code, 0)
        # Nothing was clobbered; both originals are untouched.
        self.assertEqual(self.ls(), ["a.txt", "b.txt"])
        self.assertEqual((self.dir / "b.txt").read_text(), "x")

    def test_numbering_applies(self):
        self.touch("song.mp3", "track.mp3")
        code = cmd_rename(
            make_args(dir=str(self.dir), number=True, start=10, pad=2),
            dry_run=False,
        )
        self.assertEqual(code, 0)
        self.assertEqual(self.ls(),
                         [".bulk-rename-journal.json", "song-10.mp3",
                          "track-11.mp3"])

    def test_find_replace_plus_lower(self):
        self.touch("My DRAFT File.TXT")
        code = cmd_rename(
            make_args(dir=str(self.dir), find="DRAFT", replace="final",
                      case_insensitive=True, lower=True),
            dry_run=False,
        )
        self.assertEqual(code, 0)
        # Case transform applies to the stem only; the extension is
        # untouched unless --ext is given.
        self.assertIn("my final file.TXT", self.ls())

    def test_undo_skips_missing_targets(self):
        self.touch("one.txt", "two.txt")
        cmd_rename(make_args(dir=str(self.dir), ext=".md"), dry_run=False)
        (self.dir / "one.md").unlink()  # user deleted it meanwhile
        code = cmd_undo(make_args(dir=str(self.dir)))
        self.assertNotEqual(code, 0)  # one entry could not be restored
        self.assertIn("two.txt", self.ls())
        self.assertNotIn("one.txt", self.ls())

    def test_recursive_and_include_filter(self):
        self.touch("a.jpg", "b.png", "sub/c.jpg", "sub/d.txt")
        code = cmd_rename(
            make_args(dir=str(self.dir), recursive=True,
                      include="*.jpg", ext=".jpeg"),
            dry_run=False,
        )
        self.assertEqual(code, 0)
        names = sorted(p.relative_to(self.dir).as_posix()
                       for p in self.dir.rglob("*") if p.is_file())
        self.assertIn("a.jpeg", names)
        self.assertIn("sub/c.jpeg", names)
        self.assertIn("b.png", names)
        self.assertIn("sub/d.txt", names)

    def test_hidden_files_skipped_by_default(self):
        self.touch(".secret.txt", "visible.txt")
        code = cmd_rename(
            make_args(dir=str(self.dir), ext=".md"), dry_run=False)
        self.assertEqual(code, 0)
        self.assertIn(".secret.txt", self.ls())
        self.assertIn("visible.md", self.ls())

    def test_cli_entrypoint_preview(self):
        self.touch("IMG_1.png")
        code = main(["preview", str(self.dir), "--regex", r"IMG_(\d+)",
                     "--replace", r"pic-\1"])
        self.assertEqual(code, 0)
        self.assertEqual(self.ls(), ["IMG_1.png"])


if __name__ == "__main__":
    unittest.main()
