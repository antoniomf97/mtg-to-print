import os, sys, time, re
import xmltodict
from playwright.sync_api import sync_playwright
from tqdm import tqdm
import shutil


def parse_args():
    if len(sys.argv) != 2:
        raise ValueError(
            f"⛔ Invalid input. Run as: 'python {sys.argv[0]} <input_file>'"
        )

    filename = sys.argv[1] + ".xml" if ".xml" not in sys.argv[1] else sys.argv[1]

    input_path = "./input/" + filename
    output_path = "./output/" + filename[:-4]

    if not os.path.exists(input_path):
        raise FileNotFoundError(f"⛔ Path {input_path} does not exist.")

    # if os.path.exists(output_path):
    #     raise FileNotFoundError(f"⛔ Path {output_path} already exists.")

    return input_path, output_path


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

    return len(fronts) + len(backs) + cardback_bool, (front_dict, back_dict, cardback)


def parse_xml(file_path):
    print("Reading input file...")
    with open(file_path, "r", encoding="utf-8") as file:
        xml_file = file.read()

    print("Parsing XML...")
    data_dict = xmltodict.parse(xml_file)["order"]

    return download_counter(data_dict)


def request_mpcfill(input_path, output_path, download_count):

    with sync_playwright() as p:
        print("Lauching browser...")
        browser = p.firefox.launch(headless=True)
        context = browser.new_context(accept_downloads=True)
        page = context.new_page()
        idle_time = 5

        print("Opening MPCFill editor...")
        page.goto("https://mpcfill.com/editor", timeout=600000)

        page.get_by_role("button", name="Add Cards").click()
        page.get_by_text("XML", exact=True).click()
        page.get_by_text("Retain Selected Cardback", exact=True).click()
        page.get_by_text("Retain Selected Finish Settings", exact=True).click()

        print("Uploading XML file...")
        page.locator("input[type='file']").set_input_files(input_path)

        print("Waiting for upload to settle...")
        time.sleep(5)  # adjust if needed (e.g., 3–10 seconds)

        downloads = []
        page.on("download", lambda d: downloads.append(d))

        print("Starting downloads...")
        page.locator("button.dropdown-toggle:has-text('Download')").click()
        page.get_by_text("Card Images", exact=True).click()

        print("Waiting for downloads...")
        for _ in tqdm(range(download_count)):
            page.wait_for_event("download")

        print(f"Received {len(downloads)} files.")

        print(f"Saving files at '{output_path}'.")
        os.makedirs(output_path, exist_ok=True)
        for download in downloads:
            suggested_name = (
                re.findall(r"\((.*?)\)", download.suggested_filename)[-1] + ".png"
            )
            save_path = os.path.join(output_path, suggested_name)
            download.save_as(save_path)

        print("Closing browser...")
        browser.close()


def create_csv(input_file):
    # parse arguments
    deck_name = parse_args()
    input = "./input/" + deck_name
    output = "./output/" + deck_name + ".csv"

    # check if directory exists
    if not os.path.exists(input):
        print(f"⛔ Directory {input} does not exist.")
        exit()

    # check if output already exists
    if os.path.exists(output):
        print(f"⛔ File {output} already exists.")
        exit()

    # get filenames from input directory
    paths = []
    for dirpath, _, filenames in os.walk(input):
        for filename in filenames:
            # get absolute path and remove spaces and commas
            path = os.path.abspath(os.path.join(dirpath, filename))
            new_path = (
                path.replace(" ", "")
                .replace(",", "")
                .replace("'", "")
                .replace("ǵ", "")
                .replace("ń", "")
            )

            # rename files and append paths
            os.rename(path, new_path)
            paths.append(new_path)

    # writing output csv
    with open(output, "w") as f:
        f.write("@image" + "\n")
        for path in paths:
            # print(f"Path: {path}")
            f.write(path + "\n")

    print(f"✅ CSV file created successfully at {output}")


def organize_sets(output_path, cards):
    fronts, backs, cardback = cards
    used_slots = []
    card_counter = 1
    set_counter = 1
    for id, slots in backs.items():
        os.makedirs(f"{output_path}/set{set_counter}", exist_ok=True)
        shutil.copy2(
            f"{output_path}/{id}.png", f"{output_path}/set{set_counter}/zzback.png"
        )
        for slot in slots:
            shutil.copy2(
                f"{output_path}/{fronts[slot]}.png",
                f"{output_path}/set{set_counter}/{card_counter}.png",
            )
            used_slots.append(slot)
            card_counter += 1
        set_counter += 1

    if cardback:
        os.makedirs(f"{output_path}/set{set_counter}", exist_ok=True)
        shutil.copy2(
            f"{output_path}/{cardback}.png",
            f"{output_path}/set{set_counter}/zzback.png",
        )
        for slot, id in fronts.items():
            if slot not in used_slots:
                shutil.copy2(
                    f"{output_path}/{id}.png",
                    f"{output_path}/set{set_counter}/{card_counter}.png",
                )
                card_counter += 1
        set_counter += 1

    print(f"Created {set_counter-1} sets of cards.")
    print("Cleaning files...")

    for filename in os.listdir(output_path):
        file_path = os.path.join(output_path, filename)
        if os.path.isfile(file_path):
            os.remove(file_path)


def run():
    print("Parsing arguments " + "=" * 50)
    input_path, output_path = parse_args()
    download_count, cards = parse_xml(input_path)

    print("Requesting files " + "=" * 50)
    request_mpcfill(input_path, output_path, download_count)

    print("Organizing sets " + "=" * 50)
    organize_sets(output_path, cards)


if __name__ == "__main__":
    run()
