"""PyTorch backend for CodeWM — temporary until lighter binary is available."""

from __future__ import annotations

import importlib.util
import logging
import os
import sys
from pathlib import Path
from typing import Any

import numpy as np

logger = logging.getLogger(__name__)

_EXPERIMENTAL_BANNER = (
    "[codewm] EXPERIMENTAL: PyTorch backend — will be replaced by compiled binary"
)


def _lazy_torch():
    """Lazy-import torch with clear error."""
    try:
        import torch
        return torch
    except ImportError:
        raise ImportError(
            "PyTorch backend requires torch. Install with: pip install torch"
        ) from None


def _load_module_from_path(name: str, filepath: str):
    """Dynamic import of a .py file (avoids polluting sys.path permanently)."""
    spec = importlib.util.spec_from_file_location(name, filepath)
    if spec is None or spec.loader is None:
        raise FileNotFoundError(f"Cannot load module from {filepath}")
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


class PyTorchCodeWMBackend:
    """Loads CodeWorldModel from crucible tap source + .pt checkpoint.

    Exposes numpy-in / numpy-out interface matching CodeWMBackend protocol.
    """

    def __init__(self, ckpt_path: str, src_path: str, *, device: str = "cpu", pool_mode: str = "attn") -> None:
        logger.warning(_EXPERIMENTAL_BANNER)

        torch = _lazy_torch()
        self._torch = torch
        self._device = device

        # Resolve source paths
        src = Path(src_path)
        wm_base_py = src / "wm_base" / "wm_base.py"
        code_wm_py = src / "code_wm" / "code_wm.py"
        for p in (wm_base_py, code_wm_py):
            if not p.exists():
                raise FileNotFoundError(f"Required source not found: {p}")

        # Set pool mode before importing (CodeStateEncoder reads env at __init__)
        os.environ["WM_POOL_MODE"] = pool_mode

        # Dynamic import chain: wm_base first (code_wm imports from it)
        _load_module_from_path("wm_base", str(wm_base_py))
        code_wm_mod = _load_module_from_path("code_wm", str(code_wm_py))

        # Load checkpoint
        ckpt = torch.load(ckpt_path, map_location=device, weights_only=False)
        self._config: dict[str, Any] = dict(ckpt["config"])
        cfg = self._config

        logger.info(
            "[codewm] Loading step=%s loss=%.4f config=%s",
            ckpt.get("step", "?"),
            ckpt.get("loss", float("nan")),
            {k: v for k, v in cfg.items() if k in ("model_dim", "vocab_size", "action_dim", "encoder_loops", "num_loops")},
        )

        # Build model
        model = code_wm_mod.CodeWorldModel(
            vocab_size=cfg["vocab_size"],
            max_seq_len=cfg["max_seq_len"],
            encoder_loops=cfg["encoder_loops"],
            model_dim=cfg["model_dim"],
            num_loops=cfg["num_loops"],
            num_heads=cfg["num_heads"],
            predictor_depth=2,
            ema_decay=cfg.get("ema_decay", 0.996),
            action_dim=cfg["action_dim"],
            mlp_ratio=4.0,
            dropout=0.1,
        )
        res = model.load_state_dict(ckpt["model_state_dict"], strict=False)
        if res.missing_keys:
            logger.warning("[codewm] Missing keys: %s", res.missing_keys)
        if res.unexpected_keys:
            logger.warning("[codewm] Unexpected keys: %s", res.unexpected_keys)

        model.to(device)
        model.train(False)  # inference mode
        # Kill dropout
        for mod in model.modules():
            if isinstance(mod, torch.nn.Dropout):
                mod.p = 0.0
        self._model = model
        self._step = ckpt.get("step", -1)

    # -- Protocol impl --

    @property
    def config(self) -> dict[str, Any]:
        return self._config

    def encode_state(self, token_ids: np.ndarray) -> np.ndarray:
        torch = self._torch
        t = torch.from_numpy(token_ids).long().to(self._device)
        with torch.no_grad():
            z = self._model.state_encoder(t)
        return z.cpu().numpy()

    def encode_action(self, action: np.ndarray) -> np.ndarray:
        torch = self._torch
        t = torch.from_numpy(action).float().to(self._device)
        with torch.no_grad():
            z = self._model.action_encoder(t)
        return z.cpu().numpy()

    def predict_next_state(self, state_z: np.ndarray, action_z: np.ndarray) -> np.ndarray:
        torch = self._torch
        sz = torch.from_numpy(state_z).float().to(self._device)
        az = torch.from_numpy(action_z).float().to(self._device)
        with torch.no_grad():
            # predictor expects [B, 2, D] stacked input
            x = torch.stack([sz, az], dim=1)
            for block in self._model.predictor.blocks:
                for _ in range(self._model.predictor.num_loops):
                    h2 = block.norm1(x)
                    h_attn, _ = block.attn(h2, h2, h2, need_weights=False)
                    x = x + h_attn
                    h2 = block.norm2(x)
                    h2 = block.mlp(h2)
                    x = x + h2
            z_next = self._model.predictor.norm(x[:, 0])
        return z_next.cpu().numpy()
