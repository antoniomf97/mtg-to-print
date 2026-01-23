import os, sys


def parse_args():
    if len(sys.argv) != 2:
        raise ValueError(f"Invalid input. Run as: 'python {sys.argv[0]} <input_folder>'")
    return sys.argv[1]


def run():
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
            new_path = path.replace(" ", "").replace(",", "").replace("'", "").replace("ǵ", "").replace("ń", "")

            # rename files and append paths
            os.rename(path, new_path)
            paths.append(new_path)

    # writing output csv
    with open(output, 'w') as f:
        f.write("@image" + "\n")
        for path in paths:
            # print(f"Path: {path}")
            f.write(path + "\n")

    print(f"✅ CSV file created successfully at {output}")
    

if __name__ == "__main__":
    run()