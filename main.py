# mtg-to-print — build print-ready image sets and data-merge files from MPCFill orders.
# Copyright (C) 2026 antoniomf97
#
# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with this program.  If not, see <https://www.gnu.org/licenses/>.

import os, re, sys
import argparse
import base64
import binascii
import shutil
import unicodedata
from concurrent.futures import ThreadPoolExecutor, as_completed

import requests
import xmltodict
from tqdm import tqdm

INPUT_DIR = "./input"
OUTPUT_DIR = "./output"

# Images are fetched straight from Google Drive by their ID. mpcfill.com downloads through
# this Apps Script, which returns the same file base64-encoded but more slowly, so it is
# only the fallback for files Drive refuses to serve.
DRIVE_URL = "https://drive.google.com/uc"
SCRIPT_URL = (
    "https://script.google.com/macros/s/"
    "AKfycbw8laScKBfxda2Wb0g63gkYDBdy8NWNxINoC4xDOwnCQ3JMFdruam1MdmNmN4wI5k4/exec"
)
PARALLEL_DOWNLOADS = 4
TIMEOUT = 120  # seconds to wait on a stalled request before trying the next source


def parse_args(argv=None):
    parser = argparse.ArgumentParser(
        description="Download, organize and build print files for MPCFill orders."
    )
    parser.add_argument(
        "file",
        nargs="?",
        help="input XML file from ./input, or 'clean' to delete all inputs and outputs",
    )
    parser.add_argument("-d", action="store_true", help="download the card images")
    parser.add_argument("-o", action="store_true", help="organize the images into sets")
    parser.add_argument("-c", action="store_true", help="create the CSV data merge files")
    parser.add_argument(
        "-f", action="store_true", help="force steps to run even if already done"
    )
    parser.add_argument(
        "-all",
        dest="all",
        action="store_true",
        help="process every XML file in ./input",
    )
    args = parser.parse_args(argv)

    if args.file and args.all:
        parser.error("cannot combine an input file with -all")
    if not args.file and not args.all:
        parser.error("provide an input file, 'clean' or -all")

    return args


def download_counter(data):
    fronts = data["fronts"]["card"]
    fronts = fronts if type(fronts) == list else [fronts]
    try:
        backs = data["backs"]["card"]
        backs = backs if type(backs) == list else [backs]
    except:
        backs = []

    front_dict = {}
    for front in fronts:
        for slot in front["slots"].split(","):
            front_dict[int(slot)] = front["id"]
    front_dict = dict(sorted(front_dict.items()))

    num_backs = 0
    back_dict = {}
    for back in backs:
        slots = [int(s) for s in back["slots"].split(",")]
        num_backs += len(slots)
        back_dict[back["id"]] = slots

    cardback_bool = int(not (len(front_dict) == num_backs))

    print(
        f"Download counter [Fronts {len(fronts)} | Backs {len(backs)} | Cardback {cardback_bool}]"
    )

    cardback = data["cardback"] if cardback_bool else None

    return front_dict, back_dict, cardback


def parse_xml(file_path):
    print("Reading input file...")
    with open(file_path, "r", encoding="utf-8") as file:
        xml_file = file.read()

    print("Parsing XML...")
    data_dict = xmltodict.parse(xml_file)["order"]

    return download_counter(data_dict)


def get_missing_ids(output_path, cards):
    fronts, backs, cardback = cards
    expected = set(fronts.values()) | set(backs.keys())
    if cardback:
        expected.add(cardback)

    missing = {
        id
        for id in expected
        if not os.path.exists(os.path.join(output_path, id + ".png"))
    }

    return expected, missing


def card_names(file_path):
    with open(file_path, "r", encoding="utf-8") as file:
        data = xmltodict.parse(file.read())["order"]

    names = {}
    for section in ["fronts", "backs"]:
        cards = data.get(section)
        if not cards:
            continue
        cards = cards["card"]
        cards = cards if type(cards) == list else [cards]
        for card in cards:
            names[card["id"]] = card["name"]
    if data.get("cardback"):
        names[data["cardback"]] = "cardback"

    return names


def from_drive(id):
    response = requests.get(
        DRIVE_URL, params={"id": id, "export": "download"}, timeout=TIMEOUT
    )
    response.raise_for_status()
    return response.content


def from_script(id):
    response = requests.get(SCRIPT_URL, params={"id": id}, timeout=TIMEOUT)
    response.raise_for_status()
    return base64.b64decode(response.text)


def is_image(data):
    # MPCFill only indexes PNG and JPEG files; anything else is an error or quota page
    return data.startswith((b"\x89PNG\r\n\x1a\n", b"\xff\xd8\xff"))


def fetch_image(id):
    for source in (from_drive, from_script):
        try:
            data = source(id)
        except (requests.RequestException, binascii.Error):
            continue
        if is_image(data):
            return data
    return None


def download_image(output_path, id):
    data = fetch_image(id)
    if data is None:
        return False

    # write under a temporary name first, so an interrupted write never looks downloaded
    path = os.path.join(output_path, id + ".png")
    with open(path + ".part", "wb") as file:
        file.write(data)
    os.replace(path + ".part", path)
    return True


def download_images(output_path, ids, names):
    print(f"Downloading {len(ids)} images from Google Drive...")
    os.makedirs(output_path, exist_ok=True)

    failed = []
    pool = ThreadPoolExecutor(PARALLEL_DOWNLOADS)
    try:
        jobs = {pool.submit(download_image, output_path, id): id for id in sorted(ids)}
        for job in tqdm(as_completed(jobs), total=len(jobs)):
            if not job.result():
                failed.append(jobs[job])
    finally:
        # on Ctrl+C, let the downloads in flight finish saving but drop the queued ones
        pool.shutdown(cancel_futures=True)

    if failed:
        for id in sorted(failed, key=lambda id: names.get(id, id)):
            print(f"⛔ Could not download {names.get(id, id)} ({id}).")
        raise RuntimeError(
            f"⛔ {len(failed)} of {len(ids)} images failed. "
            "Run the same command again to retry just those."
        )

    print(f"✅ Downloaded {len(ids)} images.")


def organize_sets(output_path, cards):
    fronts, backs, cardback = cards
    used_slots = []
    card_counter = 1
    set_counter = 0
    for id, slots in backs.items():
        set_counter += 1
        os.makedirs(os.path.join(output_path, f"set{set_counter}"), exist_ok=True)
        shutil.copy2(
            os.path.join(output_path, id + ".png"),
            os.path.join(output_path, f"set{set_counter}", "zzback.png"),
        )
        for slot in slots:
            shutil.copy2(
                os.path.join(output_path, f"{fronts[slot]}.png"),
                os.path.join(output_path, f"set{set_counter}", f"{card_counter}.png"),
            )
            used_slots.append(slot)
            card_counter += 1

    if cardback:
        set_counter += 1
        os.makedirs(os.path.join(output_path, f"set{set_counter}"), exist_ok=True)
        shutil.copy2(
            os.path.join(output_path, f"{cardback}.png"),
            os.path.join(output_path, f"set{set_counter}", "zzback.png"),
        )
        for slot, id in fronts.items():
            if slot not in used_slots:
                shutil.copy2(
                    os.path.join(output_path, id + ".png"),
                    os.path.join(output_path, f"set{set_counter}", f"{card_counter}.png"),
                )
                card_counter += 1

    print(f"Created {set_counter} sets of cards.")
    print("Cleaning files...")

    for filename in os.listdir(output_path):
        file_path = os.path.join(output_path, filename)
        if os.path.isfile(file_path):
            os.remove(file_path)

    return set_counter


def create_csv(output_path, n_sets):
    project = os.path.split(output_path)[-1]

    for i in range(n_sets):
        path = os.path.join(output_path, f"set{i+1}")

        with open(os.path.join(output_path, project + f"_set{i+1}.csv"), "w") as file:
            file.write("@image" + "\n")
            for filename in os.listdir(path):
                full_path = os.path.abspath(os.path.join(path, filename))
                if os.path.isfile(full_path):
                    file.write(full_path + "\n")

        print(f"✅ CSV file created successfully at {path}")


def count_sets(output_path):
    if not os.path.isdir(output_path):
        return 0
    return len(
        [
            entry
            for entry in os.listdir(output_path)
            if re.fullmatch(r"set\d+", entry)
            and os.path.isdir(os.path.join(output_path, entry))
        ]
    )


def list_csvs(output_path):
    if not os.path.isdir(output_path):
        return []
    return [f for f in os.listdir(output_path) if f.endswith(".csv")]


def clean():
    try:
        answer = input(
            f"⚠️ This will delete everything in '{INPUT_DIR}' and '{OUTPUT_DIR}'. "
            "Are you sure? [y/N] "
        )
    except EOFError:
        answer = ""
    if answer.strip().lower() not in ["y", "yes"]:
        print("Aborted, nothing deleted.")
        return

    for folder in [INPUT_DIR, OUTPUT_DIR]:
        if not os.path.isdir(folder):
            continue
        for entry in os.listdir(folder):
            path = os.path.join(folder, entry)
            if os.path.isdir(path):
                shutil.rmtree(path)
            else:
                os.remove(path)
    print("✅ Deleted all inputs and outputs.")


def clean_name(name):
    # drop accents (ã -> a), then keep only lowercase letters and digits: spaces, commas
    # and brackets in a project's paths break the data merge CSVs
    name = unicodedata.normalize("NFKD", name).encode("ascii", "ignore").decode()
    return re.sub(r"[^a-z0-9]", "", name.lower())


def clean_input(filename):
    """Find the input file `filename` refers to and rename it to its clean name."""
    clean = clean_name(filename[:-4])
    if not clean:
        raise ValueError(
            f"⛔ '{filename}' has no letters or digits to name the project after."
        )

    # match on the clean name, so the original and the cleaned name both find the file
    matches = [
        f
        for f in os.listdir(INPUT_DIR)
        if f.lower().endswith(".xml") and clean_name(f[:-4]) == clean
    ]
    if not matches:
        raise FileNotFoundError(f"⛔ No input file matching '{filename}' in {INPUT_DIR}.")
    if len(matches) > 1:
        raise FileExistsError(
            f"⛔ {', '.join(sorted(matches))} would all become '{clean}.xml'. "
            "Rename or remove all but one."
        )

    found = matches[0]
    if found != clean + ".xml":
        os.rename(os.path.join(INPUT_DIR, found), os.path.join(INPUT_DIR, clean + ".xml"))
        print(f"Renamed input '{found}' to '{clean}.xml'.")
    return clean + ".xml"


def clean_output(output_path):
    """Rename an output folder made before names were cleaned, e.g. 'Beast Victor'."""
    clean = os.path.basename(output_path)
    if not os.path.isdir(OUTPUT_DIR):
        return

    matches = [
        d
        for d in os.listdir(OUTPUT_DIR)
        if clean_name(d) == clean and os.path.isdir(os.path.join(OUTPUT_DIR, d))
    ]
    if len(matches) > 1:
        raise FileExistsError(
            f"⛔ Output folders {', '.join(sorted(matches))} all belong to '{clean}'. "
            "Remove or merge all but one."
        )
    if not matches or matches[0] == clean:
        return

    os.rename(os.path.join(OUTPUT_DIR, matches[0]), output_path)
    print(f"Renamed output folder '{matches[0]}' to '{clean}'.")

    # the CSVs hold absolute paths through the old folder name, so rebuild them
    stale = list_csvs(output_path)
    for csv in stale:
        os.remove(os.path.join(output_path, csv))
    if stale:
        create_csv(output_path, count_sets(output_path))


def process(filename, steps, force):
    filename = clean_input(filename)
    input_path = os.path.join(INPUT_DIR, filename)
    output_path = os.path.join(OUTPUT_DIR, filename[:-4])

    print(f"Processing {filename} " + "=" * max(0, 58 - len(filename)))
    clean_output(output_path)
    cards = parse_xml(input_path)

    if "download" in steps:
        print("Requesting files " + "=" * 53)
        expected, missing = get_missing_ids(output_path, cards)
        if force:
            missing = expected
        if count_sets(output_path) and not force:
            print("✅ Images already organized, skipping download.")
        elif not missing:
            print("✅ Download already done, skipping.")
        else:
            if missing != expected:
                print(
                    f"Resuming: {len(expected) - len(missing)} images already "
                    f"downloaded, fetching the remaining {len(missing)}."
                )
            download_images(output_path, missing, card_names(input_path))

    if "organize" in steps:
        print("Organizing sets " + "=" * 54)
        if count_sets(output_path) and not force:
            print("✅ Sets already organized, skipping.")
        else:
            _, missing = get_missing_ids(output_path, cards)
            if missing:
                print(f"⛔ {len(missing)} images missing, run the download first (-d).")
            else:
                for i in range(count_sets(output_path)):
                    shutil.rmtree(os.path.join(output_path, f"set{i + 1}"))
                organize_sets(output_path, cards)

    if "csv" in steps:
        print("Building data merge files " + "=" * 44)
        n_sets = count_sets(output_path)
        if not n_sets:
            print("⛔ No sets found, run the organization first (-o).")
        elif list_csvs(output_path) and not force:
            print("✅ CSV files already created, skipping.")
        else:
            create_csv(output_path, n_sets)


def run(argv=None):
    args = parse_args(argv)

    if args.file == "clean":
        clean()
        return

    steps = []
    if args.d:
        steps.append("download")
    if args.o:
        steps.append("organize")
    if args.c:
        steps.append("csv")
    if not steps:
        steps = ["download", "organize", "csv"]

    if args.all:
        files = sorted(f for f in os.listdir(INPUT_DIR) if f.lower().endswith(".xml"))
        if not files:
            raise FileNotFoundError(f"⛔ No XML files found in {INPUT_DIR}.")
    else:
        file = args.file
        files = [file if file.lower().endswith(".xml") else file + ".xml"]

    for filename in files:
        process(filename, steps, args.f)


if __name__ == "__main__":
    try:
        # piped output on Windows defaults to cp1252, which can't print emojis
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")
    except AttributeError:
        pass
    run()
