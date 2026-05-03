"""CodeWM backend protocol — swap point for PyTorch vs binary impl."""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Any, Protocol, runtime_checkable

if TYPE_CHECKING:
    import numpy as np


# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

_DEFAULT_TAPS = Path.home() / ".crucible-hub" / "taps" / "crucible-community-tap" / "architectures"


@dataclass(slots=True)
class CodeWMConfig:
    """Configuration for loading a code world model checkpoint."""

    ckpt_path: str = ""
    src_path: str = ""  # dir containing code_wm/ and wm_base/ subdirs
    device: str = "cpu"
    pool_mode: str = "attn"  # "attn" or "cls"

    def __post_init__(self) -> None:
        if not self.src_path:
            self.src_path = os.environ.get("CODEWM_SRC", str(_DEFAULT_TAPS))
        if not self.ckpt_path:
            self.ckpt_path = os.environ.get("CODEWM_CKPT", "")


# ---------------------------------------------------------------------------
# Backend Protocol
# ---------------------------------------------------------------------------

@runtime_checkable
class CodeWMBackend(Protocol):
    """Swappable backend for code world model inference.

    PyTorch impl today, lighter binary tomorrow.
    """

    @property
    def config(self) -> dict[str, Any]:
        """Model config from checkpoint (model_dim, vocab_size, etc.)."""
        ...

    def encode_state(self, token_ids: np.ndarray) -> np.ndarray:
        """Encode token sequence → latent vector.

        Args:
            token_ids: int array [batch, seq_len] with values in [0, vocab_size).

        Returns:
            float32 array [batch, model_dim].
        """
        ...

    def encode_action(self, action: np.ndarray) -> np.ndarray:
        """Encode action vector → latent vector.

        Args:
            action: float32 array [batch, action_dim].

        Returns:
            float32 array [batch, model_dim].
        """
        ...

    def predict_next_state(
        self, state_z: np.ndarray, action_z: np.ndarray
    ) -> np.ndarray:
        """Predict next-state latent from current state + action latents.

        Args:
            state_z: float32 array [batch, model_dim].
            action_z: float32 array [batch, model_dim].

        Returns:
            float32 array [batch, model_dim].
        """
        ...
