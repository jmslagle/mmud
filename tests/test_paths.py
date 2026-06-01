import pathlib
from mmud.data.paths import PathStep, GamePath, load_paths, load_mp_file


def test_load_paths_md(data_dir):
    paths = load_paths(data_dir / "PATHS.MD")
    assert len(paths) > 5


def test_path_fields(data_dir):
    paths = load_paths(data_dir / "PATHS.MD")
    # HOME to CLKR
    p = next(p for p in paths if p.from_code == "HOME" and p.to_code == "CLKR")
    assert p.from_region == "Silvermere"
    assert p.to_code == "CLKR"
    assert len(p.steps) == 1
    assert p.steps[0].command == "s"


def test_load_mp_file(data_dir):
    mp_files = list(data_dir.glob("*.MP"))
    assert len(mp_files) > 0
    path = load_mp_file(mp_files[0])
    assert path.from_code != ""
    assert len(path.steps) > 0


def test_load_all_mp_files(data_dir):
    paths = []
    for mp in data_dir.glob("*.MP"):
        paths.append(load_mp_file(mp))
    assert len(paths) > 100
