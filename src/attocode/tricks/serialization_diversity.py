"""Serialization diversity for cache-busting (Trick T).

Varies JSON serialization style to prevent the LLM from
over-fitting to specific formatting patterns.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any, Callable


@dataclass
class SerializationStyle:
    """A serialization style configuration."""

    indent: int | None = 2
    sort_keys: bool = True
    key_sort_order: str = "asc"  # asc, desc, random
    space_after_colon: bool = True
    omit_null: bool = False
    array_style: str = "expanded"  # compact, expanded


@dataclass
class DiversityStats:
    """Statistics about serialization diversity."""

    total_serializations: int = 0
    style_distribution: dict[str, int] = field(default_factory=dict)


@dataclass
class DiverseSerializerConfig:
    """Configuration for diverse serialization."""

    variation_level: float = 0.3  # 0.0 = no variation, 1.0 = max variation
    preserve_semantics: bool = True
    vary_key_order: bool = True
    vary_indentation: bool = True
    omit_nullish: bool = True
    vary_array_format: bool = True
    seed: int | None = None


DiverseSerializerEventListener = Callable[[str, dict[str, Any]], None]


class _SeededRandom:
    """Simple seeded PRNG for deterministic variation."""

    def __init__(self, seed: int) -> None:
        self._seed = seed & 0x7FFFFFFF

    def next_float(self) -> float:
        """Get next random float in [0, 1)."""
        self._seed = (self._seed * 1103515245 + 12345) & 0x7FFFFFFF
        return self._seed / 0x7FFFFFFF

    def next_bool(self, probability: float = 0.5) -> bool:
        """Get next random boolean with given probability."""
        return self.next_float() < probability

    def next_int(self, low: int, high: int) -> int:
        """Get next random int in [low, high]."""
        return low + int(self.next_float() * (high - low + 1))


class DiverseSerializer:
    """Serializes data with controlled style variation.

    Varies indentation, key ordering, spacing, and array formatting
    while preserving semantic equivalence.
    """

    def __init__(self, config: DiverseSerializerConfig | None = None) -> None:
        self._config = config or DiverseSerializerConfig()
        import time
        seed = self._config.seed if self._config.seed is not None else int(time.time() * 1000)
        self._rng = _SeededRandom(seed)
        self._stats = DiversityStats()
        self._listeners: list[DiverseSerializerEventListener] = []

    def serialize(self, data: Any) -> str:
        """Serialize with a randomly generated style."""
        style = self.generate_style()
        result = self.serialize_with_style(data, style)
        self._stats.total_serializations += 1

        # Track style distribution
        style_key = f"{style.indent}-{style.sort_keys}-{style.key_sort_order}"
        self._stats.style_distribution[style_key] = (
            self._stats.style_distribution.get(style_key, 0) + 1
        )

        self._emit("serialization.performed", {"style": style_key})
        return result

    def serialize_with_style(self, data: Any, style: SerializationStyle) -> str:
        """Serialize data with a specific style."""
        # Process the data (omit nulls, sort keys, etc.)
        processed = self._process_value(data, style)

        indent = style.indent
        separators = None
        if not style.space_after_colon:
            separators = (",", ":")
        elif indent is None:
            separators = (", ", ": ")

        return json.dumps(
            processed,
            indent=indent,
            sort_keys=False,  # We handle sorting ourselves
            ensure_ascii=False,
            separators=separators,
        )

    def generate_style(self) -> SerializationStyle:
        """Generate a randomized style based on variation level."""
        level = self._config.variation_level
        style = SerializationStyle()

        if self._config.vary_indentation and self._rng.next_bool(level):
            style.indent = self._rng.next_int(0, 4)
            if style.indent == 0:
                style.indent = None  # compact

        if self._config.vary_key_order and self._rng.next_bool(level):
            choices = ["asc", "desc", "random"]
            idx = self._rng.next_int(0, 2)
            style.key_sort_order = choices[idx]
            style.sort_keys = style.key_sort_order != "random"

        if self._rng.next_bool(level * 0.5):
            style.space_after_colon = not style.space_after_colon

        if self._config.omit_nullish and self._rng.next_bool(level):
            style.omit_null = True

        return style

    def get_consistent_style(self) -> SerializationStyle:
        """Get a deterministic baseline style."""
        return SerializationStyle(
            indent=2,
            sort_keys=True,
            key_sort_order="asc",
            space_after_colon=True,
            omit_null=False,
            array_style="expanded",
        )

    def get_stats(self) -> DiversityStats:
        """Get diversity statistics."""
        return DiversityStats(
            total_serializations=self._stats.total_serializations,
            style_distribution=dict(self._stats.style_distribution),
        )

    def reset_stats(self) -> None:
        """Reset statistics."""
        self._stats = DiversityStats()

    def set_variation_level(self, level: float) -> None:
        """Set the variation level (0.0 to 1.0)."""
        self._config.variation_level = max(0.0, min(1.0, level))

    def on(self, listener: DiverseSerializerEventListener) -> Callable[[], None]:
        """Subscribe to serializer events."""
        self._listeners.append(listener)

        def unsubscribe() -> None:
            try:
                self._listeners.remove(listener)
            except ValueError:
                pass

        return unsubscribe

    def _process_value(self, value: Any, style: SerializationStyle) -> Any:
        """Recursively process a value according to the style."""
        if isinstance(value, dict):
            result: dict[str, Any] = {}
            keys = list(value.keys())

            if style.key_sort_order == "asc":
                keys.sort()
            elif style.key_sort_order == "desc":
                keys.sort(reverse=True)
            elif style.key_sort_order == "random":
                # Shuffle with seeded RNG
                for i in range(len(keys) - 1, 0, -1):
                    j = self._rng.next_int(0, i)
                    keys[i], keys[j] = keys[j], keys[i]

            for k in keys:
                v = value[k]
                if style.omit_null and v is None:
                    continue
                result[k] = self._process_value(v, style)
            return result
        elif isinstance(value, list):
            return [self._process_value(item, style) for item in value]
        else:
            return value

    def _emit(self, event: str, data: dict[str, Any]) -> None:
        for listener in self._listeners:
            try:
                listener(event, data)
            except Exception:
                pass


def serialize_with_variation(data: Any, variation_level: float = 0.3) -> str:
    """One-shot diverse serialization."""
    serializer = DiverseSerializer(DiverseSerializerConfig(variation_level=variation_level))
    return serializer.serialize(data)


def generate_variations(data: Any, count: int, variation_level: float = 0.5) -> list[str]:
    """Generate multiple different serializations of the same data."""
    serializer = DiverseSerializer(DiverseSerializerConfig(variation_level=variation_level))
    return [serializer.serialize(data) for _ in range(count)]


def are_semantic_equivalent(json1: str, json2: str) -> bool:
    """Check if two JSON strings are semantically equivalent."""
    try:
        obj1 = json.loads(json1)
        obj2 = json.loads(json2)
        # Normalize by re-serializing with sorted keys
        norm1 = json.dumps(obj1, sort_keys=True)
        norm2 = json.dumps(obj2, sort_keys=True)
        return norm1 == norm2
    except (json.JSONDecodeError, TypeError):
        return False


def find_most_compact(data: Any, max_attempts: int = 10) -> tuple[str, SerializationStyle]:
    """Find the most compact serialization for data.

    Tries multiple styles and returns the shortest output.
    Useful for minimizing token usage in constrained contexts.
    """
    serializer = DiverseSerializer(DiverseSerializerConfig(
        variation_level=0.8,
        vary_indentation=True,
        vary_key_order=True,
        vary_array_format=True,
    ))

    best_result = ""
    best_style = serializer.get_consistent_style()
    best_len = float("inf")

    # Always try the compact baseline
    compact_style = SerializationStyle(
        indent=None,
        sort_keys=True,
        key_sort_order="asc",
        space_after_colon=False,
        omit_null=True,
        array_style="compact",
    )
    compact_result = serializer.serialize_with_style(data, compact_style)
    if len(compact_result) < best_len:
        best_result = compact_result
        best_style = compact_style
        best_len = len(compact_result)

    # Try random variations
    for _ in range(max_attempts):
        style = serializer.generate_style()
        result = serializer.serialize_with_style(data, style)
        if len(result) < best_len:
            best_result = result
            best_style = style
            best_len = len(result)

    return best_result, best_style


def measure_compression_ratio(data: Any) -> dict[str, Any]:
    """Measure the compression ratio between different serialization styles."""
    # Baseline: pretty-printed
    pretty = json.dumps(data, indent=2, sort_keys=True)
    # Compact: no whitespace
    compact = json.dumps(data, separators=(",", ":"), sort_keys=True)

    # Diverse
    serializer = DiverseSerializer(DiverseSerializerConfig(variation_level=0.5))
    diverse = serializer.serialize(data)

    return {
        "pretty_length": len(pretty),
        "compact_length": len(compact),
        "diverse_length": len(diverse),
        "compact_ratio": len(compact) / max(1, len(pretty)),
        "diverse_ratio": len(diverse) / max(1, len(pretty)),
        "savings_chars": len(pretty) - len(compact),
        "savings_tokens_approx": (len(pretty) - len(compact)) // 4,
    }


class AdaptiveSerializer(DiverseSerializer):
    """Serializer that adapts variation level based on context.

    Increases variation when the LLM seems to be repeating patterns,
    decreases it when the output is already diverse.
    """

    def __init__(self, config: DiverseSerializerConfig | None = None) -> None:
        super().__init__(config)
        self._recent_styles: list[str] = []
        self._max_style_history: int = 20

    def serialize(self, data: Any) -> str:
        """Serialize with adaptive variation."""
        # Check if we're in a repetition rut
        if self._is_style_repetitive():
            # Temporarily boost variation
            saved = self._config.variation_level
            self._config.variation_level = min(1.0, saved + 0.3)
            result = super().serialize(data)
            self._config.variation_level = saved
        else:
            result = super().serialize(data)

        # Track the style used
        style = f"{self._stats.total_serializations}"
        self._recent_styles.append(style)
        if len(self._recent_styles) > self._max_style_history:
            self._recent_styles.pop(0)

        return result

    def _is_style_repetitive(self) -> bool:
        """Check if recent styles are too similar."""
        if len(self._recent_styles) < 5:
            return False
        # Check if the last 5 styles are all the same
        last_5 = self._recent_styles[-5:]
        unique = len(set(last_5))
        return unique <= 2
