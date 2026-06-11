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


def test_unknown_returns_none(data_dir):
    assert _db(data_dir).find("zzz frobnitz") is None


def test_exp_lookup(data_dir):
    db = _db(data_dir)
    assert db.exp_value("giant rat") > 0
    assert db.exp_value("zzz frobnitz") == 0
