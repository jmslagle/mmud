import pathlib
from mmud.config.schema import MudConfig
from mmud.tui.app import MegaMudApp


def test_app_threads_config_path_into_service(tmp_path):
    p = tmp_path / "char.toml"
    app = MegaMudApp(config=MudConfig(), host="h", port=23, config_path=p)
    assert app._config_service._path == p


def test_app_config_path_defaults_none():
    app = MegaMudApp(config=MudConfig(), host="h", port=23)
    assert app._config_service._path is None
