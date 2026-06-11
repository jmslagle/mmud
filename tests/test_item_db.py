from mmud.data.item_db import ItemDB


def _db(data_dir):
    return ItemDB.from_file(data_dir / "ITEMS.MD")


def test_find_known_item(data_dir):
    db = _db(data_dir)
    item = db.find("a statue of a bard")
    assert item is not None


def test_find_strips_article_and_case(data_dir):
    db = _db(data_dir)
    a = db.find("A Statue Of A Bard".lower())
    b = db.find("statue of a bard")
    assert a is not None and b is not None and a.record_id == b.record_id


def test_unknown_returns_none(data_dir):
    assert _db(data_dir).find("zzz frobnitz") is None


def test_equip_slot_exposed(data_dir):
    db = _db(data_dir)
    item = db.find("a statue of a bard")
    assert isinstance(item.equip_slot, int)
