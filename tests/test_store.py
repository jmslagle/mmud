import json
from mmud.data.store import GameStore, STORE_VERSION


def test_fresh_store_has_empty_schema(tmp_path):
    s = GameStore(tmp_path / "gamedb.json")
    assert s.data["version"] == STORE_VERSION
    assert s.data["sources"] == {}
    for section in ("monsters", "items", "spells", "players"):
        assert s.data[section] == {}
    assert s.data["exits"] == []
    assert s.data["marks"] == {"ungettable": [], "no_auto_equip": [], "non_enemy": []}
    assert s.data["collisions"] == []


def test_save_and_reload_roundtrip(tmp_path):
    p = tmp_path / "gamedb.json"
    s = GameStore(p)
    s.data["monsters"]["1"] = {"name": "giant rat", "origin": "md"}
    s.save()
    s2 = GameStore(p)
    assert s2.data["monsters"]["1"]["name"] == "giant rat"


def test_save_is_atomic_no_partial_file(tmp_path):
    p = tmp_path / "gamedb.json"
    s = GameStore(p)
    s.save()
    # the temp file must not linger
    assert [f.name for f in tmp_path.iterdir()] == ["gamedb.json"]
    assert json.loads(p.read_text())["version"] == STORE_VERSION


def test_corrupt_file_starts_fresh(tmp_path):
    p = tmp_path / "gamedb.json"
    p.write_text("{not json")
    s = GameStore(p)
    assert s.data["version"] == STORE_VERSION   # fresh, no crash


def test_marks_api(tmp_path):
    s = GameStore(tmp_path / "gamedb.json")
    s.add_mark("ungettable", "Fountain")
    s.add_mark("ungettable", "fountain")        # dedup, case-insensitive
    assert s.marks("ungettable") == ["fountain"]


def test_exits_api(tmp_path):
    s = GameStore(tmp_path / "gamedb.json")
    s.add_exit("AAAA0001", "n", "BBBB0002")
    s.add_exit("AAAA0001", "n", "BBBB0002")     # dedup
    assert s.exits() == [("AAAA0001", "n", "BBBB0002")]
