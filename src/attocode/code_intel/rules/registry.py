"""Rule registry — stores, indexes, and queries UnifiedRule instances."""

from __future__ import annotations

import logging
import threading
from collections import defaultdict

from attocode.code_intel.rules.model import (
    RuleCategory,
    RuleSeverity,
    RuleSource,
    RuleTier,
    UnifiedRule,
)

logger = logging.getLogger(__name__)

_SEV_RANK: dict[str, int] = {"critical": 0, "high": 1, "medium": 2, "low": 3, "info": 4}


class RuleRegistry:
    """Thread-safe registry of analysis rules.

    Supports registration from builtins, language packs, and user plugins.
    Provides filtered queries by language, category, severity, pack, etc.
    """

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._rules: dict[str, UnifiedRule] = {}  # qualified_id -> rule
        self._by_language: dict[str, list[str]] = defaultdict(list)
        self._by_category: dict[RuleCategory, list[str]] = defaultdict(list)
        self._by_pack: dict[str, list[str]] = defaultdict(list)
        self._by_severity: dict[RuleSeverity, list[str]] = defaultdict(list)

    def register(self, rule: UnifiedRule) -> None:
        """Register a rule. Overwrites if qualified_id already exists."""
        with self._lock:
            qid = rule.qualified_id
            was_update = qid in self._rules
            if was_update:
                self._unindex(qid)
            self._rules[qid] = rule
            self._index(rule)
        if was_update:
            logger.debug("Updated rule %s", qid)
        else:
            logger.debug("Registered rule %s", qid)

    def register_many(self, rules: list[UnifiedRule]) -> int:
        """Register multiple rules. Returns count registered."""
        for rule in rules:
            self.register(rule)
        return len(rules)

    def get(self, qualified_id: str) -> UnifiedRule | None:
        return self._rules.get(qualified_id)

    def remove(self, qualified_id: str) -> bool:
        """Remove a rule by qualified ID. Returns True if found."""
        with self._lock:
            if qualified_id not in self._rules:
                return False
            self._unindex(qualified_id)
            del self._rules[qualified_id]
            return True

    def enable(self, qualified_id: str) -> bool:
        with self._lock:
            rule = self._rules.get(qualified_id)
            if rule is None:
                return False
            rule.enabled = True
            return True

    def disable(self, qualified_id: str) -> bool:
        with self._lock:
            rule = self._rules.get(qualified_id)
            if rule is None:
                return False
            rule.enabled = False
            return True

    @property
    def count(self) -> int:
        return len(self._rules)

    def all_rules(self, *, enabled_only: bool = True) -> list[UnifiedRule]:
        if enabled_only:
            return [r for r in self._rules.values() if r.enabled]
        return list(self._rules.values())

    def query(
        self,
        *,
        language: str = "",
        category: RuleCategory | str = "",
        severity: RuleSeverity | str = "",
        pack: str = "",
        source: RuleSource | str = "",
        tier: RuleTier | str = "",
        tags: list[str] | None = None,
        enabled_only: bool = True,
        min_confidence: float = 0.0,
    ) -> list[UnifiedRule]:
        """Query rules with optional filters. All filters are AND-combined."""
        # Snapshot under lock
        with self._lock:
            if language:
                candidates = set(self._by_language.get(language, []))
                for qid, rule in self._rules.items():
                    if not rule.languages:
                        candidates.add(qid)
            else:
                candidates = set(self._rules.keys())
            rules_snapshot = {qid: self._rules[qid] for qid in candidates if qid in self._rules}

        results: list[UnifiedRule] = []
        for qid, rule in rules_snapshot.items():
            if enabled_only and not rule.enabled:
                continue
            if category and rule.category != category:
                continue
            if severity and _SEV_RANK.get(rule.severity, 9) > _SEV_RANK.get(str(severity), 9):
                continue
            if pack and rule.pack != pack:
                continue
            if source and rule.source != source:
                continue
            if tier and rule.tier != tier:
                continue
            if min_confidence > 0.0 and rule.confidence < min_confidence:
                continue
            if tags and not set(tags).issubset(set(rule.tags)):
                continue
            results.append(rule)

        _severity_order = {"critical": 0, "high": 1, "medium": 2, "low": 3, "info": 4}
        results.sort(key=lambda r: (_severity_order.get(r.severity, 9), r.qualified_id))
        return results

    def languages(self) -> list[str]:
        return sorted(self._by_language.keys())

    def packs(self) -> list[str]:
        return sorted(self._by_pack.keys())

    def categories(self) -> list[tuple[RuleCategory, int]]:
        return sorted(
            [(cat, len(ids)) for cat, ids in self._by_category.items()],
            key=lambda x: x[1],
            reverse=True,
        )

    def stats(self) -> dict[str, int | dict[str, int]]:
        by_sev = {str(sev): len(ids) for sev, ids in self._by_severity.items()}
        by_cat = {str(cat): len(ids) for cat, ids in self._by_category.items()}
        by_src: dict[str, int] = defaultdict(int)
        by_tier_d: dict[str, int] = defaultdict(int)
        enabled = sum(1 for r in self._rules.values() if r.enabled)
        for r in self._rules.values():
            by_src[str(r.source)] += 1
            by_tier_d[str(r.tier)] += 1
        return {
            "total": len(self._rules),
            "enabled": enabled,
            "by_severity": dict(by_sev),
            "by_category": by_cat,
            "by_source": dict(by_src),
            "by_tier": dict(by_tier_d),
            "languages": len(self._by_language),
            "packs": len(self._by_pack),
        }

    # --- Internal indexing ---

    def _index(self, rule: UnifiedRule) -> None:
        qid = rule.qualified_id
        for lang in rule.languages:
            self._by_language[lang].append(qid)
        self._by_category[rule.category].append(qid)
        self._by_severity[rule.severity].append(qid)
        if rule.pack:
            self._by_pack[rule.pack].append(qid)

    def _unindex(self, qualified_id: str) -> None:
        rule = self._rules.get(qualified_id)
        if rule is None:
            return
        qid = rule.qualified_id
        for lang in rule.languages:
            lst = self._by_language.get(lang, [])
            if qid in lst:
                lst.remove(qid)
        cat_list = self._by_category.get(rule.category, [])
        if qid in cat_list:
            cat_list.remove(qid)
        sev_list = self._by_severity.get(rule.severity, [])
        if qid in sev_list:
            sev_list.remove(qid)
        if rule.pack:
            pack_list = self._by_pack.get(rule.pack, [])
            if qid in pack_list:
                pack_list.remove(qid)
