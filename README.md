# mtg-to-print

Turn an [MPCFill](https://mpcfill.com) order into print-ready image sets and InDesign data-merge CSVs.

MPCFill is great at assembling a proxy order, but it only hands you a flat pile of images.
If you print at home (or at a local shop) you need those images grouped by the cardback they
share, numbered in a stable order, and referenced from a data-merge file. This tool does that
end to end:

1. **Download** — fetches every card image in your order straight from Google Drive, using
   the image IDs in the order XML.
2. **Organize** — copies the images into one folder per cardback (`set1`, `set2`, …), with the
   fronts numbered `1.png`, `2.png`, … and the shared back saved as `zzback.png`.
3. **CSV** — writes one data-merge CSV per set, with an `@image` column of absolute paths that
   InDesign (or any data-merge-capable layout tool) can consume directly.

Each step is idempotent and resumable, so an interrupted 300-card download can be picked up
where it left off.

---

## Requirements

- Python 3.9+ (developed on 3.13)

## Installation

```bash
git clone https://github.com/antoniomf97/mtg-to-print.git
cd mtg-to-print

python -m venv venv
venv\Scripts\activate          # Windows
# source venv/bin/activate     # macOS / Linux

pip install -r requirements.txt
```

## Getting an order XML

1. Build your order on [mpcfill.com](https://mpcfill.com/editor).
2. Use **Download → XML** to export it.
3. Drop the file into `input/`, e.g. `input/cards1.xml`.

Any file name works. The first time the tool runs on a file, it renames it to lowercase letters
and digits only, dropping spaces, punctuation and accents: `Tannuk, Matheus (2).xml` becomes
`tannukmatheus2.xml`. The output folder and CSVs get the same clean name, because spaces, commas
and brackets in those paths break the data merge.

The XML is the single source of truth for the run — it carries the card IDs, the slot each card
occupies, the per-slot backs, and the default cardback.

## Usage

```bash
python main.py cards1
```

That runs all three steps for `input/cards1.xml`. The `.xml` extension is optional, and you can
type a name either as it was or cleaned: `python main.py "Tannuk, Matheus (2)"` and
`python main.py tannukmatheus2` find the same file.

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

## How downloading works

Every image is fetched straight from Google Drive by the ID in the XML, four at a time, and
saved to `output/<project>/` the moment it arrives. mpcfill.com itself isn't involved, so it
doesn't matter whether its editor can still find every card in your order.

- On a re-run, images already in `output/<project>/` are skipped, so an interrupted download
  (Ctrl+C, a dropped connection, a laptop going to sleep) picks up where it stopped.
- If Google Drive refuses a file (it rate-limits popular ones), the image is fetched through the
  Google Apps Script that mpcfill.com uses for its own downloads instead. It returns the same
  file, just more slowly.
- If both fail, the run still finishes every other image, then names the cards it couldn't get
  and exits with an error. Running the same command again retries just those.

A 530-card order (539 images, 2.2 GB) took under 6 minutes in testing. The progress bar counts
images, not bytes.

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
  card names from the XML only appear in error messages.
- **Output folders from before names were cleaned are adopted.** If `output/` has a folder whose
  cleaned name matches the order (`Beast Victor/` for `beastvictor.xml`), it is renamed to the
  clean name and its CSVs are rebuilt, since they contain the folder's path. Nothing is downloaded
  again, but InDesign documents linked to the old CSVs need relinking.
- **Names that clean to the same thing stop the run.** If `Deck 1.xml` and `deck1.xml` are both in
  `input/`, the tool names them and renames neither; the same goes for two matching output
  folders.

## Development

```bash
python -m pytest tests -q
```

The suite (44 tests) covers argument parsing, XML/slot handling, name cleaning, downloading
(including the Apps Script fallback and failed cards), set organization, CSV output and the step-skipping logic
in `process()`. Google Drive and the Apps Script are replaced by a fake that serves canned
responses, so the tests run offline and in well under a second.

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
