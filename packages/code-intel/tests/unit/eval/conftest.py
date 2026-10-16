"""Disk admission for tiny synthetic matrix fixtures, independent of host free space."""
import pytest

from eval.matrix import run as matrix


@pytest.fixture(autouse=True)
def synthetic_matrix_capacity(request, monkeypatch):
    # These three modules create only a handful of tiny local source files. The
    # production 25 GiB reserve is tested separately and remains unchanged.
    if request.node.path.stem in {"test_matrix_dense", "test_matrix_rerank", "test_matrix_retrieve"}:
        monkeypatch.setattr(matrix, "_free", lambda _path: 64 * 1024**3)
