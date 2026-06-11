from mmud.data.macros_md import Macro, load_macros, vk_to_key_name


def test_load_real_macros(data_dir):
    macros = load_macros(data_dir / "MACROS.MD")
    assert len(macros) == 11
    by_key = {m.key_code: m for m in macros}
    assert by_key[110].command == "d" and by_key[110].press_enter
    assert by_key[101].command == "rest"
    assert by_key[104].command == "n"
    assert all(not (m.shift or m.ctrl or m.alt) for m in macros)


def test_missing_file_returns_empty(tmp_path):
    assert load_macros(tmp_path / "MACROS.MD") == []


def test_malformed_lines_skipped(tmp_path):
    p = tmp_path / "MACROS.MD"
    p.write_text("not a macro\n96:0:0:0:u^M\n")
    macros = load_macros(p)
    assert len(macros) == 1 and macros[0].key_code == 96


def test_vk_to_key_name():
    assert vk_to_key_name(96) == "kp_0"
    assert vk_to_key_name(105) == "kp_9"
    assert vk_to_key_name(110) == "kp_decimal"
    assert vk_to_key_name(42) is None
