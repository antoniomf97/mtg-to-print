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
            os.path.join(output_path, f"set{set_counter}", "zzback.png")
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
            os.path.join(output_path, f"set{set_counter}", "zzback.png")
        )
        for slot, id in fronts.items():
            if slot not in used_slots:
                shutil.copy2(
                    os.path.join(output_path, id + ".png"),
                    os.path.join(output_path, f"set{set_counter}", f"{card_counter}.png")
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
            for filename in os.listdir(path):
                full_path = os.path.abspath(os.path.join(path, filename))
                if os.path.isfile(full_path):
                    file.write(full_path + "\n")

        print(f"✅ CSV file created successfully at {path}")


def run():
    print("Parsing arguments " + "=" * 52)
    input_path, output_path = parse_args()
    download_count, cards = parse_xml(input_path)

    print("Requesting files " + "=" * 53)
    request_mpcfill(input_path, output_path, download_count)

    print("Organizing sets " + "=" * 54)
    n_sets = organize_sets(output_path, cards)

    print("Building data merge files " + "=" * 44)          
    create_csv(output_path, n_sets)


if __name__ == "__main__":
    run()
