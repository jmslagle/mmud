from mmud.data.store import GameStore, import_md, record_hash


def test_initial_import_pins_real_counts(tmp_path, data_dir):
    s = GameStore(tmp_path / "gamedb.json")
    report = import_md(s, data_dir)
    assert report.added["monsters"] == 788
    assert report.added["items"] == 667
    assert report.added["spells"] == 936
    assert report.collisions == 0
    assert s.data["monsters"]["1"]["name"] == "giant rat"
    assert s.data["monsters"]["1"]["origin"] == "md"


def test_second_import_skips_unchanged(tmp_path, data_dir):
    s = GameStore(tmp_path / "gamedb.json")
    import_md(s, data_dir)
    report = import_md(s, data_dir)
    assert report.skipped_sources >= 3      # fingerprints unchanged
    assert sum(report.added.values()) == 0


def test_md_origin_record_follows_source(tmp_path, data_dir):
    s = GameStore(tmp_path / "gamedb.json")
    import_md(s, data_dir)
    s.data["monsters"]["1"]["name"] = "tampered"        # still origin=md
    s.data["sources"]["MONSTERS.MD"]["fingerprint"] = "stale"
    report = import_md(s, data_dir)
    assert s.data["monsters"]["1"]["name"] == "giant rat"   # replaced
    assert report.collisions == 0


def test_override_survives_and_collides(tmp_path, data_dir):
    s = GameStore(tmp_path / "gamedb.json")
    import_md(s, data_dir)
    rec = s.data["monsters"]["1"]
    rec["origin"] = "override"
    rec["exp_value"] = 99999                # local edit
    rec["md_hash"] = "sha256:old-version"   # pretend MD changed since our edit
    s.data["sources"]["MONSTERS.MD"]["fingerprint"] = "stale"
    report = import_md(s, data_dir)
    assert s.data["monsters"]["1"]["exp_value"] == 99999    # local wins
    assert report.collisions == 1
    assert s.data["collisions"][0]["db"] == "monsters"
    assert s.data["collisions"][0]["record_id"] == 1


def test_record_hash_is_stable():
    a = {"name": "rat", "exp_value": 10, "origin": "md", "md_hash": "x"}
    b = {"exp_value": 10, "name": "rat", "origin": "override", "md_hash": "y"}
    # origin/md_hash excluded from hashing; field order irrelevant
    assert record_hash(a) == record_hash(b)
