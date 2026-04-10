"""Shared pytest fixtures for photo-workflow tests."""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest
from PIL import Image


@pytest.fixture(scope="session")
def sharp_image(tmp_path_factory: pytest.TempPathFactory) -> Path:
    """256×256 checkerboard PNG — high Laplacian variance (sharp)."""
    p = tmp_path_factory.mktemp("fixtures") / "sharp.png"
    # np.indices returns (2, H, W); summing axis=0 gives a checkerboard of 0/1
    arr = np.indices((256, 256)).sum(axis=0) % 2
    Image.fromarray((arr * 255).astype(np.uint8), mode="L").save(p)
    return p


@pytest.fixture(scope="session")
def blurry_image(tmp_path_factory: pytest.TempPathFactory) -> Path:
    """256×256 solid gray PNG — near-zero Laplacian variance (blurry)."""
    p = tmp_path_factory.mktemp("fixtures") / "blurry.png"
    arr = np.full((256, 256), 128, dtype=np.uint8)
    Image.fromarray(arr, mode="L").save(p)
    return p
