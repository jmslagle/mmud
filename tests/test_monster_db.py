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


def test_learned_record_does_not_shadow_real_base():
    # A bogus learned "happy guardsman" (negative id, kill_type 0) must NOT win
    # over the real "guardsman" record reachable via adjective matching.
    from mmud.data.binary import Monster
    from mmud.data.monster_db import MonsterDB
    learned = Monster(record_id=-1, name="happy guardsman", level=0, exp_value=0,
                      combat_rating=0, alignment=0, hp_estimate=0,
                      short_name1="", short_name2="", flags=0)
    real = Monster(record_id=14, name="guardsman", level=10, exp_value=200,
                   combat_rating=2, alignment=80, hp_estimate=0,
                   short_name1="", short_name2="", flags=0x40000000)
    db = MonsterDB([learned, real])
    m = db.find("happy guardsman")
    assert m.record_id == 14 and m.combat_rating == 2


def test_genuinely_unknown_learned_still_returned():
    # A learned record with no real base still resolves (so unknown mobs work).
    from mmud.data.binary import Monster
    from mmud.data.monster_db import MonsterDB
    learned = Monster(record_id=-1, name="weird thing", level=0, exp_value=0,
                      combat_rating=0, alignment=0, hp_estimate=0,
                      short_name1="", short_name2="", flags=0)
    db = MonsterDB([learned])
    assert db.find("weird thing").record_id == -1


def test_unknown_returns_none(data_dir):
    assert _db(data_dir).find("zzz frobnitz") is None


def test_exp_lookup(data_dir):
    db = _db(data_dir)
    assert db.exp_value("giant rat") > 0
    assert db.exp_value("zzz frobnitz") == 0
