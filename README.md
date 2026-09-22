# mtg-to-print

Turn an [MPCFill](https://mpcfill.com) order into print-ready image sets and InDesign data-merge CSVs.

MPCFill is great at assembling a proxy order, but it only hands you a flat pile of images.
If you print at home (or at a local shop) you need those images grouped by the cardback they
share, numbered in a stable order, and referenced from a data-merge file. This tool does that
end to end:

1. **Download** — drives mpcfill.com in a headless Firefox (Playwright), uploads your order
   XML and collects every card image.
2. **Organize** — copies the images into one folder per cardback (`set1`, `set2`, …), with the
   fronts numbered `1.png`, `2.png`, … and the shared back saved as `zzback.png`.
3. **CSV** — writes one data-merge CSV per set, with an `@image` column of absolute paths that
   InDesign (or any data-merge-capable layout tool) can consume directly.

Each step is idempotent and resumable, so an interrupted 300-card download can be picked up
where it left off.

---

## Requirements

- Python 3.9+ (developed on 3.13)
- A Playwright-managed Firefox build (installed below)

## Installation

```bash
git clone https://github.com/antoniomf97/mtg-to-print.git
cd mtg-to-print

python -m venv venv
venv\Scripts\activate          # Windows
# source venv/bin/activate     # macOS / Linux

pip install -r requirements.txt
playwright install firefox
```

## Getting an order XML

1. Build your order on [mpcfill.com](https://mpcfill.com/editor).
2. Use **Download → XML** to export it.
3. Drop the file into `input/`, e.g. `input/cards1.xml`.

The XML is the single source of truth for the run — it carries the card IDs, the slot each card
occupies, the per-slot backs, and the default cardback.

## Usage

```bash
python main.py cards1
```

That runs all three steps for `input/cards1.xml`. The `.xml` extension is optional.

### Running individual steps

| Flag   | Step                                                          |
| ------ | ------------------------------------------------------------- |
| `-d`   | Download the card images                                       |
| `-o`   | Organize the images into sets                                  |
| `-c`   | Create the CSV data-merge files                                |
| `-f`   | Force — re-run a step even if its output already exists        |
| `-all` | Process every `.xml` file in `input/` instead of a single file |

Flags combine, and steps always run in pipeline order regardless of how you type them:

```bash
python main.py cards1 -d          # download only
python main.py cards1 -o -c       # organize and build CSVs from images already on disk
python main.py cards1 -c -f       # rebuild the CSVs, overwriting the existing ones
python main.py -all               # full pipeline for every order in input/
python main.py -all -c            # rebuild CSVs for every order
```

### Cleaning up

```bash
python main.py clean
```

Deletes **everything** in `input/` and `output/`. It asks for confirmation first and aborts on
anything other than `y`/`yes`.

## What you get

For `input/cards1.xml`:

```
output/cards1/
├── set1/
│   ├── 1.png          # fronts, numbered in slot order
│   ├── 2.png
│   └── zzback.png     # the back shared by this set
├── set2/
│   ├── 3.png
│   └── zzback.png
├── cards1_set1.csv
└── cards1_set2.csv
```

Each CSV looks like:

```csv
@image
C:\...\output\cards1\set1\1.png
C:\...\output\cards1\set1\2.png
C:\...\output\cards1\set1\zzback.png
```

Card numbering is continuous across sets, so no two images in a project share a filename. The
back is named `zzback.png` so it always sorts last within its folder — handy when you lay the
sheet out by filename.

### How sets are formed

- Every distinct back declared in `<backs>` becomes its own set, together with the fronts in the
  slots that back covers.
- If some slots have no explicit back, the order's default `<cardback>` gets a final set holding
  all the remaining fronts.
- An order where every slot has an explicit back produces no default-cardback set.

## Resuming an interrupted download

Downloads are matched against the IDs the XML expects, so the tool always knows what is still
missing:

- On a re-run it skips images already present in `output/<project>/`.
- If only part of the order is missing, it writes a trimmed `_resume.xml` into the output folder
  and uploads that instead — MPCFill then only serves the cards you still need.
- If no new file arrives for 240 seconds, the run gives up rather than hanging forever, and
  tells you to run the same command again.
- If the browser session ends with images still missing, the run exits with an error naming how
  many are outstanding. Re-running the same command fetches just those.

Large orders take a while — MPCFill serves the images one at a time and a 150-card order is
normal to sit through. The progress bar tracks images received, not bytes.

## Notes and caveats

- **Organizing consumes the loose downloads.** After a successful organize step, the flat image
  files in `output/<project>/` are deleted; only the `setN/` folders remain. To re-organize from
  scratch, re-download first: `python main.py cards1 -d -o -f`.
- **Once sets exist, `-d` is a no-op** unless you pass `-f`. This is deliberate: it keeps
  `python main.py cards1` cheap to re-run after the work is done.
- **`-o` refuses to run with images missing**, and `-c` refuses to run with no sets present. Each
  prints which earlier step to run instead of failing halfway.
- **Nothing in `input/` or `output/` is tracked by git** — `.gitignore` excludes `*.xml`, `*.png`,
  `*.csv` and `*.pdf` project-wide.
- **Card images are named by their Google Drive ID** while downloading (`<id>.png`); the friendly
  card names from the XML are only used to build the resume file.

## Development

```bash
python -m pytest tests -q
```

The suite (33 tests) covers argument parsing, XML/slot handling, resume-file generation, set
organization, CSV output and the step-skipping logic in `process()`. `request_mpcfill` — the only
function that touches the network — is monkeypatched out, so the tests run offline and in well
under a second.

Formatting is [black](https://black.readthedocs.io/) (pinned in `requirements.txt`, run with
`-l 90` to match the existing style):

```bash
python -m black -l 90 main.py tests
```

### Layout

```
main.py            # the whole pipeline: parse → download → organize → csv
input/             # order XMLs go here
output/<project>/  # per-order images, sets and CSVs
tests/             # pytest suite
```

## License

Copyright (C) 2026 antoniomf97.

This program is free software: you can redistribute it and/or modify it under the terms of the
[GNU General Public License](LICENSE) as published by the Free Software Foundation, either
version 3 of the License, or (at your option) any later version.

It is distributed in the hope that it will be useful, but **without any warranty** — without even
the implied warranty of merchantability or fitness for a particular purpose. See the GNU General
Public License for details.
