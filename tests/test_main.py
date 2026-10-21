import builtins
import os

import pytest
import xmltodict

import main


def card(id, slots, name=None):
    return {"id": id, "slots": slots, "name": name or f"{id}.png", "query": id.lower()}


def write_order_xml(path, fronts, backs=None, cardback=None):
    n_slots = sum(len(c["slots"].split(",")) for c in fronts)
    order = {
        "order": {
            "details": {
                "quantity": n_slots,
                "bracket": 18,
                "stock": "(S30) Standard Smooth",
                "foil": "false",
            },
            "fronts": {"card": fronts},
        }
    }
    if backs:
        order["order"]["backs"] = {"card": backs}
    if cardback:
        order["order"]["cardback"] = cardback
    with open(path, "w", encoding="utf-8") as file:
        file.write(xmltodict.unparse(order, pretty=True))


def touch(path, content=""):
    with open(path, "w", encoding="utf-8") as file:
        file.write(content)


@pytest.fixture
def fake_dirs(tmp_path, monkeypatch):
    input_dir = tmp_path / "input"
    output_dir = tmp_path / "output"
    input_dir.mkdir()
    output_dir.mkdir()
    monkeypatch.setattr(main, "INPUT_DIR", str(input_dir))
    monkeypatch.setattr(main, "OUTPUT_DIR", str(output_dir))
    return input_dir, output_dir


@pytest.fixture
def project(fake_dirs):
    input_dir, output_dir = fake_dirs
    write_order_xml(input_dir / "proj.xml", [card("A", "0")], cardback="CB")
    out = output_dir / "proj"
    out.mkdir()
    return input_dir, out


# ---------------- parse_args ----------------


def test_parse_args_defaults():
    args = main.parse_args(["toino1"])
    assert args.file == "toino1"
    assert not args.d and not args.o and not args.c and not args.f and not args.all


def test_parse_args_flags():
    args = main.parse_args(["toino1", "-d", "-f"])
    assert args.d and args.f
    assert not args.o and not args.c


def test_parse_args_all():
    args = main.parse_args(["-all"])
    assert args.all
    assert args.file is None


def test_parse_args_requires_file_or_all():
    with pytest.raises(SystemExit):
        main.parse_args([])


def test_parse_args_rejects_file_with_all():
    with pytest.raises(SystemExit):
        main.parse_args(["toino1", "-all"])


# ---------------- download_counter / parse_xml ----------------


def test_download_counter_single_front_needs_cardback():
    data = {"fronts": {"card": card("A", "0")}, "cardback": "CB"}
    fronts, backs, cardback = main.download_counter(data)
    assert fronts == {0: "A"}
    assert backs == {}
    assert cardback == "CB"


def test_download_counter_backs_cover_all_slots():
    data = {
        "fronts": {"card": [card("A", "0"), card("B", "1")]},
        "backs": {"card": card("BK", "0,1")},
        "cardback": "CB",
    }
    fronts, backs, cardback = main.download_counter(data)
    assert fronts == {0: "A", 1: "B"}
    assert backs == {"BK": [0, 1]}
    assert cardback is None


def test_download_counter_multiple_slots_per_card():
    data = {"fronts": {"card": card("A", "2,0,1")}, "cardback": "CB"}
    fronts, _, _ = main.download_counter(data)
    assert list(fronts.keys()) == [0, 1, 2]
    assert set(fronts.values()) == {"A"}


def test_parse_xml_roundtrip(tmp_path):
    xml_path = tmp_path / "order.xml"
    write_order_xml(xml_path, [card("A", "0"), card("B", "1")], cardback="CB")
    fronts, backs, cardback = main.parse_xml(str(xml_path))
    assert fronts == {0: "A", 1: "B"}
    assert backs == {}
    assert cardback == "CB"


# ---------------- get_missing_ids ----------------


def test_get_missing_ids(tmp_path):
    cards = ({0: "A", 1: "B"}, {"BK": [0]}, "CB")
    expected, missing = main.get_missing_ids(str(tmp_path), cards)
    assert expected == {"A", "B", "BK", "CB"}
    assert missing == expected

    touch(tmp_path / "A.png")
    touch(tmp_path / "BK.png")
    _, missing = main.get_missing_ids(str(tmp_path), cards)
    assert missing == {"B", "CB"}


def test_get_missing_ids_without_cardback(tmp_path):
    cards = ({0: "A"}, {"BK": [0]}, None)
    expected, _ = main.get_missing_ids(str(tmp_path), cards)
    assert expected == {"A", "BK"}


def test_get_missing_ids_missing_output_dir(tmp_path):
    cards = ({0: "A"}, {}, "CB")
    expected, missing = main.get_missing_ids(str(tmp_path / "nope"), cards)
    assert missing == expected


# ---------------- build_partial_xml ----------------


def test_build_partial_xml(tmp_path):
    input_xml = tmp_path / "order.xml"
    write_order_xml(
        input_xml,
        [card("A", "0"), card("B", "1")],
        backs=[card("BK", "1")],
        cardback="CB",
    )
    out_dir = tmp_path / "out"
    resume_path = main.build_partial_xml(str(input_xml), str(out_dir), {"B", "BK", "CB"})

    with open(resume_path, encoding="utf-8") as file:
        order = xmltodict.parse(file.read())["order"]

    entries = order["fronts"]["card"]
    assert {e["id"] for e in entries} == {"B", "BK", "CB"}
    assert sorted(int(e["slots"]) for e in entries) == [0, 1, 2]
    assert int(order["details"]["quantity"]) == 3
    assert order["cardback"] == "CB"
    assert "backs" not in order


def test_build_partial_xml_single_missing_card(tmp_path):
    input_xml = tmp_path / "order.xml"
    write_order_xml(input_xml, [card("A", "0"), card("B", "1")], cardback="CB")
    resume_path = main.build_partial_xml(str(input_xml), str(tmp_path / "out"), {"B"})

    with open(resume_path, encoding="utf-8") as file:
        order = xmltodict.parse(file.read())["order"]

    entry = order["fronts"]["card"]
    assert entry["id"] == "B"
    assert entry["slots"] == "0"
    assert int(order["details"]["quantity"]) == 1


# ---------------- organize_sets / create_csv ----------------


def test_organize_sets(tmp_path):
    out = tmp_path / "proj"
    out.mkdir()
    for id in ["A", "B", "C", "BK", "CB"]:
        touch(out / f"{id}.png", content=id)

    cards = ({0: "A", 1: "B", 2: "C"}, {"BK": [1]}, "CB")
    n_sets = main.organize_sets(str(out), cards)

    assert n_sets == 2
    assert (out / "set1" / "zzback.png").read_text() == "BK"
    assert (out / "set1" / "1.png").read_text() == "B"
    assert (out / "set2" / "zzback.png").read_text() == "CB"
    assert (out / "set2" / "2.png").read_text() == "A"
    assert (out / "set2" / "3.png").read_text() == "C"
    # loose files are cleaned up afterwards
    assert not list(out.glob("*.png"))


def test_create_csv(tmp_path):
    out = tmp_path / "proj"
    (out / "set1").mkdir(parents=True)
    touch(out / "set1" / "1.png")
    touch(out / "set1" / "zzback.png")

    main.create_csv(str(out), 1)

    lines = (out / "proj_set1.csv").read_text().splitlines()
    assert lines[0] == "@image"
    assert {os.path.basename(line) for line in lines[1:]} == {"1.png", "zzback.png"}
    assert all(os.path.isabs(line) for line in lines[1:])


def test_count_sets_and_list_csvs(tmp_path):
    assert main.count_sets(str(tmp_path / "nope")) == 0
    assert main.list_csvs(str(tmp_path / "nope")) == []

    (tmp_path / "set1").mkdir()
    (tmp_path / "set2").mkdir()
    (tmp_path / "settings").mkdir()  # not a set
    touch(tmp_path / "set3")  # a file, not a folder
    assert main.count_sets(str(tmp_path)) == 2

    touch(tmp_path / "proj_set1.csv")
    assert main.list_csvs(str(tmp_path)) == ["proj_set1.csv"]


# ---------------- clean ----------------


def test_clean_aborts_without_confirmation(fake_dirs, monkeypatch):
    input_dir, _ = fake_dirs
    touch(input_dir / "a.xml")
    monkeypatch.setattr(builtins, "input", lambda _: "n")
    main.clean()
    assert (input_dir / "a.xml").exists()


def test_clean_aborts_on_eof(fake_dirs, monkeypatch):
    input_dir, _ = fake_dirs
    touch(input_dir / "a.xml")

    def raise_eof(_):
        raise EOFError

    monkeypatch.setattr(builtins, "input", raise_eof)
    main.clean()
    assert (input_dir / "a.xml").exists()


def test_clean_deletes_everything_on_yes(fake_dirs, monkeypatch):
    input_dir, output_dir = fake_dirs
    touch(input_dir / "a.xml")
    (output_dir / "proj" / "set1").mkdir(parents=True)
    touch(output_dir / "proj" / "set1" / "1.png")
    monkeypatch.setattr(builtins, "input", lambda _: "y")
    main.clean()
    assert list(input_dir.iterdir()) == []
    assert list(output_dir.iterdir()) == []


# ---------------- process: step skipping ----------------


def test_process_skips_download_when_all_images_present(project, monkeypatch):
    _, out = project
    touch(out / "A.png")
    touch(out / "CB.png")
    calls = []
    monkeypatch.setattr(main, "request_mpcfill", lambda *a: calls.append(a))
    main.process("proj.xml", ["download"], force=False)
    assert calls == []


def test_process_resumes_with_partial_xml(project, monkeypatch):
    _, out = project
    touch(out / "A.png")
    calls = []
    monkeypatch.setattr(main, "request_mpcfill", lambda *a: calls.append(a))
    main.process("proj.xml", ["download"], force=False)

    ((upload_path, output_path, missing),) = calls
    assert upload_path.endswith("_resume.xml")
    assert missing == {"CB"}


def test_process_force_redownloads_everything(project, monkeypatch):
    _, out = project
    touch(out / "A.png")
    touch(out / "CB.png")
    calls = []
    monkeypatch.setattr(main, "request_mpcfill", lambda *a: calls.append(a))
    main.process("proj.xml", ["download"], force=True)

    ((upload_path, _, missing),) = calls
    assert upload_path == os.path.join(main.INPUT_DIR, "proj.xml")
    assert missing == {"A", "CB"}


def test_process_skips_download_when_already_organized(project, monkeypatch):
    _, out = project
    (out / "set1").mkdir()
    calls = []
    monkeypatch.setattr(main, "request_mpcfill", lambda *a: calls.append(a))
    main.process("proj.xml", ["download"], force=False)
    assert calls == []


def test_process_organize_requires_images(project):
    _, out = project
    main.process("proj.xml", ["organize"], force=False)
    assert main.count_sets(str(out)) == 0


def test_process_csv_requires_sets(project):
    _, out = project
    main.process("proj.xml", ["csv"], force=False)
    assert main.list_csvs(str(out)) == []


def test_process_organize_and_csv_offline(project):
    _, out = project
    touch(out / "A.png", content="A")
    touch(out / "CB.png", content="CB")

    main.process("proj.xml", ["organize", "csv"], force=False)

    assert main.count_sets(str(out)) == 1
    assert (out / "set1" / "zzback.png").read_text() == "CB"
    assert (out / "set1" / "1.png").read_text() == "A"
    assert main.list_csvs(str(out)) == ["proj_set1.csv"]

    # a second run skips both steps and leaves the results untouched
    before = (out / "proj_set1.csv").read_text()
    main.process("proj.xml", ["organize", "csv"], force=False)
    assert (out / "proj_set1.csv").read_text() == before


def test_process_missing_input_file(fake_dirs):
    with pytest.raises(FileNotFoundError):
        main.process("nope.xml", ["download"], force=False)


# ---------------- run ----------------


def test_run_appends_xml_extension(fake_dirs, monkeypatch):
    processed = []
    monkeypatch.setattr(main, "process", lambda f, steps, force: processed.append(f))
    main.run(["proj"])
    assert processed == ["proj.xml"]


def test_run_default_steps_are_all_steps(fake_dirs, monkeypatch):
    seen = []
    monkeypatch.setattr(
        main, "process", lambda f, steps, force: seen.append((tuple(steps), force))
    )
    main.run(["proj.xml"])
    assert seen == [(("download", "organize", "csv"), False)]


def test_run_all_processes_every_input_sorted(fake_dirs, monkeypatch):
    input_dir, _ = fake_dirs
    write_order_xml(input_dir / "b.xml", [card("A", "0")], cardback="CB")
    write_order_xml(input_dir / "a.xml", [card("B", "0")], cardback="CB")
    processed = []
    monkeypatch.setattr(
        main, "process", lambda f, steps, force: processed.append((f, tuple(steps), force))
    )
    main.run(["-all", "-c", "-f"])
    assert processed == [("a.xml", ("csv",), True), ("b.xml", ("csv",), True)]


def test_run_all_with_empty_input(fake_dirs):
    with pytest.raises(FileNotFoundError):
        main.run(["-all"])


def test_run_clean(monkeypatch):
    called = []
    monkeypatch.setattr(main, "clean", lambda: called.append(True))
    main.run(["clean"])
    assert called == [True]
