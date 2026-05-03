"""Code World Model experiment ground (EXPERIMENTAL).

Loads a VICReg/JEPA-trained code world model from Crucible checkpoints
and exposes encode/predict operations for code state transitions.

Model source: ~/.crucible-hub/taps/crucible-community-tap/architectures/
PyTorch backend is a temporary shim — will be replaced by a lighter binary.

Usage:
    python -m eval.codewm smoke --ckpt /tmp/vicreg_sota_step14500.pt
    python -m eval.codewm.eval_codeintel --ckpt ... --repo /path/to/repo
"""

from eval.codewm.backend import CodeWMBackend, CodeWMConfig

__all__ = ["CodeWMBackend", "CodeWMConfig"]
