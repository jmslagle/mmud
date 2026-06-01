import pathlib
import pytest

DATA_DIR = pathlib.Path(__file__).parent.parent / "extractions/mm103s.exe.extracted/45DAD/Default"

@pytest.fixture
def data_dir():
    return DATA_DIR
