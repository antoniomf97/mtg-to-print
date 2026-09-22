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
import shutil

import xmltodict
from playwright.sync_api import sync_playwright
from tqdm import tqdm

INPUT_DIR = "./input"
OUTPUT_DIR = "./output"


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


def build_partial_xml(input_path, output_path, missing_ids):
    with open(input_path, "r", encoding="utf-8") as file:
        data = xmltodict.parse(file.read())["order"]

    entries = []
    seen = set()
    for section in ["fronts", "backs"]:
        cards = data.get(section)
        if not cards:
            continue
        cards = cards["card"]
        cards = cards if type(cards) == list else [cards]
        for card in cards:
            if card["id"] in missing_ids and card["id"] not in seen:
                entries.append(
                    {
                        "id": card["id"],
                        "slots": str(len(entries)),
                        "name": card["name"],
                        "query": card.get("query"),
                    }
                )
                seen.add(card["id"])

    cardback = data.get("cardback")
    if cardback and cardback in missing_ids and cardback not in seen:
        entries.append(
            {
                "id": cardback,
                "slots": str(len(entries)),
                "name": "cardback.png",
                "query": None,
            }
        )

    order = {
        "order": {
            "details": {
                "quantity": len(entries),
                "bracket": data["details"]["bracket"],
                "stock": data["details"]["stock"],
                "foil": data["details"]["foil"],
            },
            "fronts": {"card": entries},
        }
    }
    if cardback:
        order["order"]["cardback"] = cardback

    os.makedirs(output_path, exist_ok=True)
    resume_path = os.path.join(output_path, "_resume.xml")
    with open(resume_path, "w", encoding="utf-8") as file:
        file.write(xmltodict.unparse(order, pretty=True))

    return resume_path


def request_mpcfill(upload_path, output_path, missing_ids):

    with sync_playwright() as p:
        print("Lauching browser...")
        browser = p.firefox.launch(headless=True)
        context = browser.new_context(accept_downloads=True)
        page = context.new_page()

        print("Opening MPCFill editor...")
        page.goto("https://mpcfill.com/editor", timeout=600000)

        page.get_by_role("button", name="Add Cards").click()
        page.get_by_text("XML", exact=True).click()
        page.get_by_text("Retain Selected Cardback", exact=True).click()
        page.get_by_text("Retain Selected Finish Settings", exact=True).click()

        print("Uploading XML file...")
        page.locator("input[type='file']").set_input_files(upload_path)

        print("Waiting for upload to settle...")
        page.wait_for_timeout(10000)  # adjust if needed (e.g., 3–10 seconds)

        downloads = []
        page.on("download", lambda d: downloads.append(d))

        def file_id(download):
            found = re.findall(r"\((.*?)\)", download.suggested_filename)
            if found:
                return found[-1]
            return os.path.splitext(download.suggested_filename)[0]

        print("Starting downloads...")
        page.locator("button.dropdown-toggle:has-text('Download')").click()
        page.get_by_text("Card Images", exact=True).click()

        print("Waiting for downloads...")
        stall_limit = 240  # seconds without a new download before giving up
        stalled = 0.0
        with tqdm(total=len(missing_ids)) as progress:
            while progress.n < len(missing_ids):
                page.wait_for_timeout(500)
                received = len(missing_ids & {file_id(d) for d in downloads})
                if received > progress.n:
                    progress.update(received - progress.n)
                    stalled = 0.0
                else:
                    stalled += 0.5
                    if stalled >= stall_limit:
                        print(f"⚠️ No new download for {stall_limit}s, giving up.")
                        break

        print(f"Received {len(downloads)} files.")

        print(f"Saving files at '{output_path}'.")
        os.makedirs(output_path, exist_ok=True)
        for download in downloads:
            save_path = os.path.join(output_path, file_id(download) + ".png")
            download.save_as(save_path)

        print("Closing browser...")
        browser.close()

        still_missing = missing_ids - {file_id(d) for d in downloads}
        if still_missing:
            raise RuntimeError(
                f"⛔ Still missing {len(still_missing)} of {len(missing_ids)} images. "
                "Run the same command again to fetch just the missing ones."
            )


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


def process(filename, steps, force):
    input_path = os.path.join(INPUT_DIR, filename)
    output_path = os.path.join(OUTPUT_DIR, filename[:-4])

    if not os.path.exists(input_path):
        raise FileNotFoundError(f"⛔ Path {input_path} does not exist.")

    print(f"Processing {filename} " + "=" * max(0, 58 - len(filename)))
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
            upload_path = input_path
            if missing != expected:
                print(
                    f"Resuming: {len(expected) - len(missing)} images already "
                    f"downloaded, fetching the remaining {len(missing)}."
                )
                upload_path = build_partial_xml(input_path, output_path, missing)
            request_mpcfill(upload_path, output_path, missing)

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
        files = sorted(f for f in os.listdir(INPUT_DIR) if f.endswith(".xml"))
        if not files:
            raise FileNotFoundError(f"⛔ No XML files found in {INPUT_DIR}.")
    else:
        files = [args.file if args.file.endswith(".xml") else args.file + ".xml"]

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
