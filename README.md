# bulk-rename

A safe bulk file-renamer CLI, written in pure Python (standard library
only — no third-party packages). Rename many files at once with
find/replace, regex, sequential numbering, case transforms and extension
changes — always with a preview first, collision protection, and a
one-command undo.

## Install / run

No installation needed — Python 3.8+ is the only requirement:

```bash
git clone https://github.com/LlvallVeiz/bulk-rename.git
cd bulk-rename
python3 -m bulk_rename --help
```

For a global command, symlink the entry point or add the project
directory to `PYTHONPATH`:

```bash
export PYTHONPATH="$PWD"
python3 -m bulk_rename rename ~/Photos --dry-run
```

## Quick examples

### 1. Regex rename with capture groups

```bash
$ ls photos/
IMG_0001.jpg  IMG_0002.jpg  IMG_0003.jpg

$ python3 -m bulk_rename rename photos \
    --regex 'IMG_(\d+)' --replace 'photo-\1' --yes
IMG_0001.jpg  ->  photo-0001.jpg
IMG_0002.jpg  ->  photo-0002.jpg
IMG_0003.jpg  ->  photo-0003.jpg
Done: 3 file(s) renamed.

$ ls photos/
photo-0001.jpg  photo-0002.jpg  photo-0003.jpg
```

### 2. Sequential numbering

```bash
$ ls tracks/
song.mp3  track.mp3  demo.mp3

$ python3 -m bulk_rename rename tracks --number --start 10 --pad 2 --yes
demo.mp3   ->  demo-10.mp3
song.mp3   ->  song-11.mp3
track.mp3  ->  track-12.mp3
```

Files are numbered in **sorted order**, so the result is deterministic.

### 3. Find/replace + case transform

```bash
$ python3 -m bulk_rename rename docs \
    --find DRAFT --replace final --case-insensitive --lower --yes
My DRAFT File.TXT  ->  my final file.TXT
```

### 4. Change extension (recursively, images only)

```bash
$ python3 -m bulk_rename rename gallery --recursive \
    --include '*.jpg,*.png' --ext .jpeg --yes
```

### 5. Preview first, apply later

```bash
$ python3 -m bulk_rename preview photos --regex 'IMG_(\d+)' --replace 'photo-\1'
IMG_0001.jpg  ->  photo-0001.jpg
...
Dry run: no files were changed.
```

`preview` is an alias for `rename --dry-run`.

### 6. Undo the last batch

```bash
$ python3 -m bulk_rename undo --dir photos
restored: photo-0002.jpg -> IMG_0002.jpg
restored: photo-0001.jpg -> IMG_0001.jpg
Undo complete: 2 restored, 0 missing, 0 blocked.
```

## Operation order

When several modes are combined, they are applied to each file's
**stem** (name without extension) in this fixed order:

1. **Find/replace** (`--find`/`--replace`, optionally
   `--case-insensitive`) **or regex** (`--regex` + `--replace`) — the
   two are mutually exclusive.
2. **Sequential numbering** (`--number`, `--start`, `--pad`) — appends
   `-<NNN>` to the stem.
3. **Case transform** (`--lower` / `--upper` / `--title`) — at most one;
   applies to the stem only, the extension is untouched.
4. **Extension change** (`--ext .md`) — replaces the extension.

So `--regex 'IMG_(\d+)' --replace 'photo-\1' --number --lower --ext .png`
turns `IMG_0042.JPG` into `photo-0042-001.png` (numbering follows the
sorted file order).

## Safety

- **Preview before you commit.** `preview` / `--dry-run` prints the
  full old → new table and changes nothing.
- **Confirmation.** Without `--yes`, the preview is shown and you are
  asked `Apply these renames? [y/N]`. When stdin is not a terminal
  (e.g. in a script or pipe), the run refuses to apply unless `--yes`
  or `--dry-run` is given.
- **Collision detection.** A rename is refused — and the rest of the
  batch still runs — when:
  - its target already exists on disk, or
  - two sources would produce the same target.
  Refused pairs are marked `[SKIPPED: …]` in the preview, and the
  process exits non-zero if any rename was skipped.
- **Chains are safe.** If a target is itself renamed away in the same
  batch (e.g. `x.txt → x-001.txt` while `x-001.txt → x-001-001.txt`),
  files are staged through temporary names first so nothing is lost.
- **Undo journal.** Every successful apply writes
  `.bulk-rename-journal.json` in the target directory (or the path
  given with `--journal`), recording old → new pairs and a timestamp.
  `bulk-rename undo` renames everything back in reverse order. Entries
  whose target no longer exists are reported and skipped, and the
  journal file is removed after a successful undo.
- **Files only.** Directories are never renamed. Hidden files
  (dotfiles) are skipped unless `--include-hidden` is given. The
  journal file itself is never renamed.

## Options reference

```
bulk-rename rename <dir> [options]
bulk-rename preview <dir> [options]     # same as rename --dry-run
bulk-rename undo [--journal PATH] [--dir DIR]

Rename options:
  --find TEXT            literal substring to replace
  --replace TEXT         replacement text (default: empty)
  --case-insensitive     case-insensitive --find matching
  --regex PATTERN        regex with capture groups, e.g. 'IMG_(\d+)'
  --number               append sequential numbering -<NNN>
  --start N              first number (default: 1)
  --pad WIDTH            zero-padding width (default: 3)
  --lower / --upper / --title
                         case transform (at most one)
  --ext .EXT             change the extension, e.g. '.md'
  --recursive            rename files in subdirectories too
  --include '*.jpg,*.png'
                         only rename files matching these globs
  --include-hidden       also rename hidden files
  --dry-run              preview only, change nothing
  --yes                  apply without asking for confirmation
  --journal PATH         where to write the undo journal
```

## Project layout

```
bulk_rename/
  __init__.py      package version
  __main__.py      entry point (python -m bulk_rename)
  renamer.py       pattern logic: pipeline, planning, collision detection
  journal.py       JSON undo journal (read/write)
  cli.py           argparse CLI, file collection, apply + undo
tests/
  test_bulk_rename.py   unittest suite (stdlib only)
```

## Tests

```bash
python3 -m unittest discover -s tests -v
```

15 tests cover regex capture groups, numbering (start + pad),
dry-run making no changes, collision refusal, undo restoring original
names, find/replace + case transform, recursive mode with an include
filter, hidden-file skipping, and undo with a missing target.

## License

MIT — see [LICENSE](LICENSE).
