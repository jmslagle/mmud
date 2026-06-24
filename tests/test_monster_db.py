from mmud.data.monster_db import MonsterDB


def _db(data_dir):
    return MonsterDB.from_file(data_dir / "MONSTERS.MD")


def test_lookup_exact(data_dir):
    db = _db(data_dir)
    m = db.find("giant rat")
    assert m is not None and m.name == "giant rat"


def test_lookup_strips_article_and_case(data_dir):
    db = _db(data_dir)
    assert db.find("A Giant Rat").name == "giant rat"
    assert db.find("the giant rat").name == "giant rat"


def test_lookup_depluralizes(data_dir):
    db = _db(data_dir)
    # "2 orc warriors" room text yields plural name
    m = db.find("orc warriors")
    assert m is not None


def test_lookup_strips_leading_adjectives(data_dir):
    # MegaMud (monster_db_lookup_by_name @0x4544d0) matches the DB base name as a
    # word-boundary substring, so leading moods/adjectives are absorbed.
    db = _db(data_dir)
    assert db.find("happy guardsman").name == "guardsman"
    assert db.find("a large giant rat").name == "giant rat"
    assert db.find("the angry kobold thief").name == "kobold thief"


def test_lookup_prefers_longest_match(data_dir):
    # "giant rat" must not be hijacked by a shorter "rat"-style record.
    db = _db(data_dir)
    assert db.find("vicious giant rat").name == "giant rat"


def test_unknown_returns_none(data_dir):
    assert _db(data_dir).find("zzz frobnitz") is None


def test_exp_lookup(data_dir):
    db = _db(data_dir)
    assert db.exp_value("giant rat") > 0
    assert db.exp_value("zzz frobnitz") == 0
