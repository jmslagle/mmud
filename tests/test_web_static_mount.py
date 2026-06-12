from __future__ import annotations
import pathlib
from mmud.web.server import _FRONTEND_DIST


def test_static_mount_path_points_at_dist():
    assert _FRONTEND_DIST.name == "dist"
    assert _FRONTEND_DIST.parent.name == "frontend"
    assert isinstance(_FRONTEND_DIST, pathlib.Path)
