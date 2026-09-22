# Changelog

All notable changes to this project are documented here.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and this project
adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html). No git tags exist yet, so
the released versions below were reconstructed from the commit history and dated accordingly.

## [Unreleased]

### Added

- Proper CLI built on `argparse`, with `--help` and validation of mutually exclusive inputs.
- Step flags `-d` (download), `-o` (organize) and `-c` (CSV) to run any part of the pipeline on
  its own. With no flags, all three run in order, as before.
- `-f` to force a step to re-run even when its output is already on disk.
- `-all` to process every `.xml` file in `input/` in one invocation, sorted by filename.
- `clean` command to wipe `input/` and `output/`, guarded by a confirmation prompt that aborts on
  anything other than `y`/`yes` (including EOF, so it is safe in non-interactive shells).
- Pytest suite (33 tests) covering argument parsing, slot/back resolution, resume-file
  generation, set organization, CSV output and step skipping. `request_mpcfill` is stubbed, so the
  suite runs offline.
- `README.md` and this changelog.
- GNU General Public License v3.0 (or later): full text in `LICENSE`, notice header in `main.py`.

### Changed

- Each step now detects its own prior output and skips: download is skipped once every image is
  present (or the images are already organized into sets), organize is skipped once sets exist,
  and CSV generation is skipped once CSVs exist. `-f` overrides all three.
- Organize and CSV report the missing prerequisite instead of failing partway — organize tells you
  to run `-d` when images are missing, CSV tells you to run `-o` when there are no sets.
- Forced organize now removes the existing `setN/` folders before rebuilding them, rather than
  mixing new output into old.
- `parse_args()` takes an optional argv list, and `process()` was split out of `run()`, so both are
  testable without touching `sys.argv`.
- `download_counter()` no longer returns a redundant download count; callers derive the expected
  set of IDs from the front/back/cardback mapping.
- stdout/stderr are reconfigured to UTF-8 on startup, so the status emoji no longer crash the run
  when output is piped on Windows (cp1252).

## [0.3.0] - 2026-07-08

### Added

- Resumable downloads. Images already in `output/<project>/` are recognized and skipped; when only
  part of an order is missing, a trimmed `_resume.xml` is written to the output folder and uploaded
  in place of the full order, so MPCFill only serves the outstanding cards.
- Stall detection: if no new download arrives for 240 seconds the run stops instead of hanging.

### Changed

- Download progress is tracked by matching received files against the expected card IDs, replacing
  the previous fixed-count wait.
- A session that ends with images still missing now raises, naming how many are outstanding and
  telling you to re-run the same command.

## [0.2.0] - 2026-04-30

The project moved from "rename a folder of images" to a full MPCFill pipeline.

### Added

- MPCFill automation via Playwright: launches headless Firefox, opens the editor, uploads the order
  XML with cardback and finish settings retained, and captures the resulting image downloads.
- Order XML parsing with `xmltodict`, resolving fronts, per-slot backs and the default cardback,
  including orders where a card occupies several slots and orders with a single card in a section.
- Set organization: one folder per distinct back, fronts numbered continuously across sets, shared
  back copied in as `zzback.png`, and loose image files cleaned up afterwards.
- One data-merge CSV per set, with an `@image` header and absolute image paths.
- `requirements.txt` with pinned dependencies.
- `tqdm` progress bar for downloads.

### Removed

- The old flow that walked a directory of pre-downloaded images and renamed them in place.

## [0.1.0] - 2026-01-28

### Added

- First working version: walk a folder under `input/`, strip spaces, commas, apostrophes and other
  characters that break data merge from the filenames, and write a single `@image` CSV of absolute
  paths.
- Argument and path validation with clear error messages for a missing or malformed input.

[Unreleased]: https://github.com/antoniomf97/mtg-to-print/compare/fd260ff...HEAD
[0.3.0]: https://github.com/antoniomf97/mtg-to-print/compare/8f3f302...fd260ff
[0.2.0]: https://github.com/antoniomf97/mtg-to-print/compare/e7a6f9e...8f3f302
[0.1.0]: https://github.com/antoniomf97/mtg-to-print/commits/e7a6f9e
