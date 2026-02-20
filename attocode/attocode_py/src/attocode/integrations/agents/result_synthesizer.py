"""Result synthesizer for merging outputs from multiple agents.

Structured merging of results from multiple agents. Goes beyond
simple concatenation to intelligently combine outputs with:
- Code merging: Intelligent merge of code changes from multiple agents
- Finding synthesis: Combine research findings, deduplicate insights
- Conflict detection: Identify contradictions between results
- Conflict resolution: Strategies for resolving disagreements
- Confidence weighting: Weight results by agent confidence and authority
"""

from __future__ import annotations

import re
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any

from attocode.types.agent import AgentResult


# =============================================================================
# Enums
# =============================================================================


class OutputType(StrEnum):
    """Type of agent output."""

    CODE = "code"
    RESEARCH = "research"
    ANALYSIS = "analysis"
    REVIEW = "review"
    PLAN = "plan"
    DOCUMENTATION = "documentation"
    MIXED = "mixed"


class ConflictType(StrEnum):
    """Type of conflict between agent results."""

    CODE_OVERLAP = "code_overlap"
    LOGIC_CONTRADICTION = "logic_contradiction"
    APPROACH_MISMATCH = "approach_mismatch"
    FACT_DISAGREEMENT = "fact_disagreement"
    PRIORITY_CONFLICT = "priority_conflict"
    NAMING_CONFLICT = "naming_conflict"


class ConflictSeverity(StrEnum):
    """Severity of a detected conflict."""

    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"


class ResolutionStrategy(StrEnum):
    """Strategy used to resolve a conflict."""

    CHOOSE_HIGHEST_CONFIDENCE = "choose_highest_confidence"
    CHOOSE_HIGHEST_AUTHORITY = "choose_highest_authority"
    MERGE_BOTH = "merge_both"
    HUMAN_DECISION = "human_decision"
    LLM_DECISION = "llm_decision"
    VOTING = "voting"
    DISCARD_ALL = "discard_all"


class SynthesisMethod(StrEnum):
    """Method used for synthesis."""

    CONCATENATE = "concatenate"
    DEDUPLICATE = "deduplicate"
    MERGE_STRUCTURED = "merge_structured"
    SYNTHESIZE_LLM = "synthesize_llm"
    MAJORITY_VOTE = "majority_vote"


# =============================================================================
# Data Types
# =============================================================================


@dataclass(slots=True)
class FileChange:
    """A file change from an agent."""

    path: str
    type: str  # 'create' | 'modify' | 'delete'
    new_content: str
    original_content: str | None = None


@dataclass(slots=True)
class AgentOutput:
    """A result from an agent that can be synthesized."""

    agent_id: str
    content: str
    type: OutputType
    confidence: float  # 0.0 - 1.0
    authority: float = 0.5  # 0.0 - 1.0
    files_modified: list[FileChange] = field(default_factory=list)
    findings: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class ConflictResolution:
    """Resolution applied to a conflict."""

    strategy: ResolutionStrategy
    chosen_agent_id: str | None = None
    merged_content: str | None = None
    explanation: str = ""
    resolved_at: float = field(default_factory=time.monotonic)


@dataclass(slots=True)
class FileConflict:
    """A detected conflict between agent results."""

    id: str
    type: ConflictType
    agent_ids: list[str]
    description: str
    conflicting_content: list[str]
    severity: ConflictSeverity = ConflictSeverity.MEDIUM
    file_path: str | None = None
    lines: list[int] | None = None
    suggested_resolution: str | None = None
    resolution: ConflictResolution | None = None


@dataclass(slots=True)
class SynthesisStats:
    """Statistics about the synthesis process."""

    input_count: int = 0
    total_content_length: int = 0
    synthesized_length: int = 0
    deduplication_rate: float = 0.0
    conflicts_detected: int = 0
    conflicts_resolved: int = 0
    agreement_rate: float = 1.0


@dataclass(slots=True)
class SynthesisResult:
    """Result of synthesis from multiple agent outputs."""

    output: str
    type: OutputType = OutputType.MIXED
    confidence: float = 0.0
    file_changes: list[FileChange] = field(default_factory=list)
    findings: list[str] = field(default_factory=list)
    conflicts: list[FileConflict] = field(default_factory=list)
    stats: SynthesisStats = field(default_factory=SynthesisStats)
    method: SynthesisMethod = SynthesisMethod.CONCATENATE


# =============================================================================
# LLM Synthesis Types
# =============================================================================


@dataclass(slots=True)
class LLMSynthesisResult:
    """Result from LLM-based synthesis."""

    content: str
    findings: list[str] = field(default_factory=list)
    resolutions: list[dict[str, str]] = field(default_factory=list)
    confidence: float = 0.0


LLMSynthesizeFunction = Callable[
    [list[AgentOutput], list[FileConflict]],
    LLMSynthesisResult,
]


# =============================================================================
# Configuration
# =============================================================================


@dataclass
class ResultSynthesizerConfig:
    """Configuration for the result synthesizer."""

    default_method: SynthesisMethod = SynthesisMethod.DEDUPLICATE
    conflict_resolution: ResolutionStrategy = ResolutionStrategy.CHOOSE_HIGHEST_CONFIDENCE
    deduplication_threshold: float = 0.8
    use_llm: bool = False
    llm_synthesizer: LLMSynthesizeFunction | None = None
    prefer_higher_confidence: bool = True
    prefer_higher_authority: bool = True


# =============================================================================
# Event Types
# =============================================================================


@dataclass(slots=True)
class SynthesizerEvent:
    """Event emitted by the result synthesizer."""

    type: str
    data: dict[str, Any] = field(default_factory=dict)


SynthesizerEventListener = Callable[[SynthesizerEvent], None]


# =============================================================================
# Result Synthesizer
# =============================================================================


class ResultSynthesizer:
    """Synthesizes results from multiple agents into a coherent output.

    Supports multiple synthesis strategies: deduplication, structured merge,
    LLM-assisted synthesis, and majority vote. Detects and resolves conflicts
    between agent outputs.

    Example::

        synthesizer = ResultSynthesizer()

        result = await synthesizer.synthesize([
            AgentOutput(
                agent_id="agent-a",
                content="Found auth logic in src/auth.ts",
                type=OutputType.RESEARCH,
                confidence=0.9,
                findings=["JWT tokens used", "Session stored in Redis"],
            ),
            AgentOutput(
                agent_id="agent-b",
                content="Auth implemented in src/auth.ts using JWT",
                type=OutputType.RESEARCH,
                confidence=0.85,
                findings=["JWT tokens used", "Password hashing with bcrypt"],
            ),
        ])
    """

    def __init__(self, config: ResultSynthesizerConfig | None = None) -> None:
        self._config = config or ResultSynthesizerConfig()
        self._listeners: list[SynthesizerEventListener] = []
        self._conflict_counter = 0

    # =========================================================================
    # Synthesis
    # =========================================================================

    async def synthesize(self, outputs: list[AgentOutput]) -> SynthesisResult:
        """Synthesize multiple agent outputs into a coherent result."""
        self._emit(SynthesizerEvent(
            type="synthesis.started",
            data={"output_count": len(outputs)},
        ))

        if len(outputs) == 0:
            return self._create_empty_result()

        if len(outputs) == 1:
            return self._create_single_result(outputs[0])

        # Detect conflicts
        conflicts = self.detect_conflicts(outputs)
        for conflict in conflicts:
            self._emit(SynthesizerEvent(
                type="conflict.detected",
                data={"conflict_id": conflict.id, "type": conflict.type},
            ))

        # Determine synthesis method
        method = self._determine_method(outputs)

        if method == SynthesisMethod.MERGE_STRUCTURED:
            result = await self._merge_structured(outputs, conflicts)
        elif method == SynthesisMethod.SYNTHESIZE_LLM:
            result = await self._synthesize_llm(outputs, conflicts)
        elif method == SynthesisMethod.MAJORITY_VOTE:
            result = self._majority_vote(outputs, conflicts)
        elif method == SynthesisMethod.DEDUPLICATE:
            result = self._deduplicate_merge(outputs, conflicts)
        else:
            result = self._concatenate_merge(outputs, conflicts)

        self._emit(SynthesizerEvent(
            type="synthesis.completed",
            data={"method": result.method, "confidence": result.confidence},
        ))

        return result

    async def synthesize_code(self, outputs: list[AgentOutput]) -> SynthesisResult:
        """Synthesize code changes from multiple agents."""
        code_outputs = [
            o for o in outputs
            if o.type == OutputType.CODE or o.files_modified
        ]

        if not code_outputs:
            return self._create_empty_result()

        # Collect all file changes by path
        changes_by_file: dict[str, list[FileChange]] = {}
        for output in code_outputs:
            for change in output.files_modified:
                changes_by_file.setdefault(change.path, []).append(change)

        # Merge changes per file
        merged_changes: list[FileChange] = []
        conflicts: list[FileConflict] = []

        for file_path, changes in changes_by_file.items():
            if len(changes) == 1:
                merged_changes.append(changes[0])
            else:
                merge_result = self._merge_file_changes(
                    file_path, changes, code_outputs
                )
                if merge_result["merged"] is not None:
                    merged_changes.append(merge_result["merged"])
                conflicts.extend(merge_result["conflicts"])

        # Build output content
        output_parts: list[str] = []
        for change in merged_changes:
            output_parts.append(f"# File: {change.path}")
            output_parts.append(change.new_content)
            output_parts.append("")

        output_text = "\n".join(output_parts)

        return SynthesisResult(
            output=output_text,
            type=OutputType.CODE,
            confidence=self._calculate_combined_confidence(code_outputs),
            file_changes=merged_changes,
            findings=[],
            conflicts=conflicts,
            stats=self._calculate_stats(code_outputs, output_text, conflicts),
            method=SynthesisMethod.MERGE_STRUCTURED,
        )

    def synthesize_findings(self, outputs: list[AgentOutput]) -> SynthesisResult:
        """Synthesize research findings from multiple agents."""
        all_findings: list[dict[str, Any]] = []

        for output in outputs:
            for finding in output.findings:
                all_findings.append({
                    "finding": finding,
                    "agent_id": output.agent_id,
                    "confidence": output.confidence,
                })

            # Also extract findings from content
            extracted = self._extract_findings_from_content(output.content)
            for finding in extracted:
                all_findings.append({
                    "finding": finding,
                    "agent_id": output.agent_id,
                    "confidence": output.confidence * 0.8,
                })

        # Deduplicate findings
        deduplicated = self._deduplicate_findings(all_findings)

        self._emit(SynthesizerEvent(
            type="deduplication.performed",
            data={
                "original": len(all_findings),
                "deduplicated": len(deduplicated),
            },
        ))

        # Build output
        output_lines = ["## Synthesized Findings", ""]
        for i, f in enumerate(deduplicated, 1):
            pct = f["confidence"] * 100
            output_lines.append(f"{i}. {f['finding']} (confidence: {pct:.0f}%)")

        # Detect contradictions
        conflicts = self._detect_finding_contradictions(deduplicated)

        output_text = "\n".join(output_lines)

        return SynthesisResult(
            output=output_text,
            type=OutputType.RESEARCH,
            confidence=self._calculate_combined_confidence(outputs),
            file_changes=[],
            findings=[f["finding"] for f in deduplicated],
            conflicts=conflicts,
            stats=self._calculate_stats(outputs, output_text, conflicts),
            method=SynthesisMethod.DEDUPLICATE,
        )

    # =========================================================================
    # Conflict Detection
    # =========================================================================

    def detect_conflicts(self, outputs: list[AgentOutput]) -> list[FileConflict]:
        """Detect conflicts between agent outputs."""
        conflicts: list[FileConflict] = []
        conflicts.extend(self._detect_code_overlaps(outputs))
        conflicts.extend(self._detect_logic_contradictions(outputs))
        conflicts.extend(self._detect_approach_mismatches(outputs))
        return conflicts

    def _detect_code_overlaps(self, outputs: list[AgentOutput]) -> list[FileConflict]:
        """Detect overlapping code changes."""
        conflicts: list[FileConflict] = []
        changes_by_file: dict[str, list[tuple[FileChange, str]]] = {}

        for output in outputs:
            for change in output.files_modified:
                changes_by_file.setdefault(change.path, []).append(
                    (change, output.agent_id)
                )

        for file_path, changes in changes_by_file.items():
            if len(changes) <= 1:
                continue

            for i in range(len(changes)):
                for j in range(i + 1, len(changes)):
                    change_a, agent_a = changes[i]
                    change_b, agent_b = changes[j]

                    if (
                        change_a.type == "modify"
                        and change_b.type == "modify"
                    ):
                        similarity = self._calculate_similarity(
                            change_a.new_content, change_b.new_content
                        )
                        if similarity < 0.9:
                            self._conflict_counter += 1
                            conflicts.append(FileConflict(
                                id=f"conflict-{self._conflict_counter}",
                                type=ConflictType.CODE_OVERLAP,
                                agent_ids=[agent_a, agent_b],
                                description=f"Overlapping changes to {file_path}",
                                conflicting_content=[
                                    change_a.new_content,
                                    change_b.new_content,
                                ],
                                severity=ConflictSeverity.HIGH,
                                file_path=file_path,
                                suggested_resolution=(
                                    "Review both changes and merge manually "
                                    "or choose one"
                                ),
                            ))

        return conflicts

    def _detect_logic_contradictions(
        self, outputs: list[AgentOutput]
    ) -> list[FileConflict]:
        """Detect logic contradictions in findings."""
        conflicts: list[FileConflict] = []

        for i in range(len(outputs)):
            for j in range(i + 1, len(outputs)):
                contradictions = self._find_contradictions(
                    outputs[i].content, outputs[j].content
                )
                for contradiction in contradictions:
                    self._conflict_counter += 1
                    conflicts.append(FileConflict(
                        id=f"conflict-{self._conflict_counter}",
                        type=ConflictType.LOGIC_CONTRADICTION,
                        agent_ids=[outputs[i].agent_id, outputs[j].agent_id],
                        description=contradiction["description"],
                        conflicting_content=[
                            contradiction["content_a"],
                            contradiction["content_b"],
                        ],
                        severity=ConflictSeverity.MEDIUM,
                        suggested_resolution=(
                            "Verify which conclusion is correct"
                        ),
                    ))

        return conflicts

    def _detect_approach_mismatches(
        self, outputs: list[AgentOutput]
    ) -> list[FileConflict]:
        """Detect different approaches to the same problem."""
        conflicts: list[FileConflict] = []
        code_outputs = [o for o in outputs if o.type == OutputType.CODE]

        if len(code_outputs) <= 1:
            return conflicts

        for i in range(len(code_outputs)):
            for j in range(i + 1, len(code_outputs)):
                similarity = self._calculate_similarity(
                    code_outputs[i].content, code_outputs[j].content
                )
                len_a = len(code_outputs[i].content)
                len_b = len(code_outputs[j].content)
                length_ratio = min(len_a, len_b) / max(len_a, len_b) if max(len_a, len_b) > 0 else 1.0

                if length_ratio > 0.5 and similarity < 0.3:
                    self._conflict_counter += 1
                    conflicts.append(FileConflict(
                        id=f"conflict-{self._conflict_counter}",
                        type=ConflictType.APPROACH_MISMATCH,
                        agent_ids=[
                            code_outputs[i].agent_id,
                            code_outputs[j].agent_id,
                        ],
                        description="Different approaches to the same implementation",
                        conflicting_content=[
                            code_outputs[i].content[:200],
                            code_outputs[j].content[:200],
                        ],
                        severity=ConflictSeverity.MEDIUM,
                        suggested_resolution=(
                            "Review both approaches and select the best one"
                        ),
                    ))

        return conflicts

    def _find_contradictions(
        self, text_a: str, text_b: str
    ) -> list[dict[str, str]]:
        """Find contradicting statements between two texts."""
        contradictions: list[dict[str, str]] = []

        negation_pairs = [
            ("is", "is not"),
            ("does", "does not"),
            ("can", "cannot"),
            ("should", "should not"),
            ("will", "will not"),
            ("works", "does not work"),
            ("exists", "does not exist"),
            ("found", "not found"),
        ]

        sentences_a = [
            s.strip().lower()
            for s in re.split(r"[.!?]+", text_a)
            if s.strip()
        ]
        sentences_b = [
            s.strip().lower()
            for s in re.split(r"[.!?]+", text_b)
            if s.strip()
        ]

        for sent_a in sentences_a:
            for sent_b in sentences_b:
                for pos, neg in negation_pairs:
                    if (
                        (pos in sent_a and neg in sent_b)
                        or (neg in sent_a and pos in sent_b)
                    ):
                        stripped_a = sent_a.replace(pos, "").replace(neg, "")
                        stripped_b = sent_b.replace(pos, "").replace(neg, "")
                        similarity = self._calculate_similarity(
                            stripped_a, stripped_b
                        )
                        if similarity > 0.5:
                            contradictions.append({
                                "description": (
                                    f'Contradiction about: "{sent_a[:50]}..."'
                                ),
                                "content_a": sent_a,
                                "content_b": sent_b,
                            })

        return contradictions

    # =========================================================================
    # Conflict Resolution
    # =========================================================================

    def resolve_conflict(
        self, conflict: FileConflict, outputs: list[AgentOutput]
    ) -> ConflictResolution:
        """Resolve a conflict using the configured strategy."""
        strategy = self._config.conflict_resolution

        if strategy == ResolutionStrategy.CHOOSE_HIGHEST_CONFIDENCE:
            return self._resolve_by_confidence(conflict, outputs)
        elif strategy == ResolutionStrategy.CHOOSE_HIGHEST_AUTHORITY:
            return self._resolve_by_authority(conflict, outputs)
        elif strategy == ResolutionStrategy.MERGE_BOTH:
            return self._resolve_merge_both(conflict)
        elif strategy == ResolutionStrategy.VOTING:
            return self._resolve_by_voting(conflict, outputs)
        else:
            return ConflictResolution(
                strategy=ResolutionStrategy.DISCARD_ALL,
                explanation="No resolution strategy available",
            )

    def _resolve_by_confidence(
        self, conflict: FileConflict, outputs: list[AgentOutput]
    ) -> ConflictResolution:
        relevant = [
            o for o in outputs if o.agent_id in conflict.agent_ids
        ]
        if not relevant:
            return ConflictResolution(
                strategy=ResolutionStrategy.DISCARD_ALL,
                explanation="No relevant agents found",
            )
        winner = max(relevant, key=lambda o: o.confidence)
        return ConflictResolution(
            strategy=ResolutionStrategy.CHOOSE_HIGHEST_CONFIDENCE,
            chosen_agent_id=winner.agent_id,
            explanation=(
                f"Chose {winner.agent_id} with confidence {winner.confidence}"
            ),
        )

    def _resolve_by_authority(
        self, conflict: FileConflict, outputs: list[AgentOutput]
    ) -> ConflictResolution:
        relevant = [
            o for o in outputs if o.agent_id in conflict.agent_ids
        ]
        if not relevant:
            return ConflictResolution(
                strategy=ResolutionStrategy.DISCARD_ALL,
                explanation="No relevant agents found",
            )
        winner = max(relevant, key=lambda o: o.authority)
        return ConflictResolution(
            strategy=ResolutionStrategy.CHOOSE_HIGHEST_AUTHORITY,
            chosen_agent_id=winner.agent_id,
            explanation=(
                f"Chose {winner.agent_id} with authority {winner.authority}"
            ),
        )

    def _resolve_merge_both(self, conflict: FileConflict) -> ConflictResolution:
        merged = "\n\n# --- Alternative ---\n\n".join(
            conflict.conflicting_content
        )
        return ConflictResolution(
            strategy=ResolutionStrategy.MERGE_BOTH,
            merged_content=merged,
            explanation="Merged both versions",
        )

    def _resolve_by_voting(
        self, conflict: FileConflict, _outputs: list[AgentOutput]
    ) -> ConflictResolution:
        votes: dict[str, int] = {}
        for agent_id in conflict.agent_ids:
            votes[agent_id] = votes.get(agent_id, 0) + 1

        winner = max(votes, key=lambda k: votes[k])
        return ConflictResolution(
            strategy=ResolutionStrategy.VOTING,
            chosen_agent_id=winner,
            explanation=f"{winner} won by vote",
        )

    # =========================================================================
    # Merge Strategies
    # =========================================================================

    def _deduplicate_merge(
        self, outputs: list[AgentOutput], conflicts: list[FileConflict]
    ) -> SynthesisResult:
        """Merge with deduplication."""
        all_parts: list[dict[str, Any]] = []

        for output in outputs:
            parts = re.split(r"\n\n+", output.content)
            for part in parts:
                stripped = part.strip()
                if len(stripped) > 20:
                    all_parts.append({
                        "content": stripped,
                        "confidence": output.confidence,
                    })

        # Deduplicate
        deduplicated: list[dict[str, Any]] = []
        for part in all_parts:
            is_duplicate = any(
                self._calculate_similarity(d["content"], part["content"])
                > self._config.deduplication_threshold
                for d in deduplicated
            )
            if not is_duplicate:
                deduplicated.append(part)

        deduplicated.sort(key=lambda d: d["confidence"], reverse=True)
        output_text = "\n\n".join(d["content"] for d in deduplicated)

        return SynthesisResult(
            output=output_text,
            type=self._determine_output_type(outputs),
            confidence=self._calculate_combined_confidence(outputs),
            file_changes=self._merge_all_file_changes(outputs),
            findings=self._extract_all_findings(outputs),
            conflicts=conflicts,
            stats=self._calculate_stats(outputs, output_text, conflicts),
            method=SynthesisMethod.DEDUPLICATE,
        )

    def _concatenate_merge(
        self, outputs: list[AgentOutput], conflicts: list[FileConflict]
    ) -> SynthesisResult:
        """Simple concatenation merge."""
        parts = [f"## From {o.agent_id}\n\n{o.content}" for o in outputs]
        output_text = "\n\n---\n\n".join(parts)

        return SynthesisResult(
            output=output_text,
            type=OutputType.MIXED,
            confidence=self._calculate_combined_confidence(outputs),
            file_changes=self._merge_all_file_changes(outputs),
            findings=self._extract_all_findings(outputs),
            conflicts=conflicts,
            stats=self._calculate_stats(outputs, output_text, conflicts),
            method=SynthesisMethod.CONCATENATE,
        )

    async def _merge_structured(
        self, outputs: list[AgentOutput], conflicts: list[FileConflict]
    ) -> SynthesisResult:
        """Structured merge for code."""
        for conflict in conflicts:
            if conflict.resolution is None:
                conflict.resolution = self.resolve_conflict(conflict, outputs)
                self._emit(SynthesizerEvent(
                    type="conflict.resolved",
                    data={"conflict_id": conflict.id},
                ))

        merged_changes = self._merge_all_file_changes(outputs)
        output_parts: list[str] = []
        for change in merged_changes:
            output_parts.append(f"# File: {change.path}")
            output_parts.append(change.new_content)

        output_text = "\n\n".join(output_parts)

        return SynthesisResult(
            output=output_text,
            type=OutputType.CODE,
            confidence=self._calculate_combined_confidence(outputs),
            file_changes=merged_changes,
            findings=[],
            conflicts=conflicts,
            stats=self._calculate_stats(outputs, output_text, conflicts),
            method=SynthesisMethod.MERGE_STRUCTURED,
        )

    async def _synthesize_llm(
        self, outputs: list[AgentOutput], conflicts: list[FileConflict]
    ) -> SynthesisResult:
        """LLM-assisted synthesis."""
        if self._config.llm_synthesizer is None:
            return self._deduplicate_merge(outputs, conflicts)

        try:
            llm_result = self._config.llm_synthesizer(outputs, conflicts)

            # Apply LLM conflict resolutions
            for resolution in llm_result.resolutions:
                conflict_id = resolution.get("conflict_id", "")
                matching = [c for c in conflicts if c.id == conflict_id]
                for conflict in matching:
                    if conflict.resolution is None:
                        conflict.resolution = ConflictResolution(
                            strategy=ResolutionStrategy.LLM_DECISION,
                            merged_content=resolution.get("resolution", ""),
                            explanation=resolution.get("explanation", ""),
                        )
                        self._emit(SynthesizerEvent(
                            type="conflict.resolved",
                            data={"conflict_id": conflict.id},
                        ))

            return SynthesisResult(
                output=llm_result.content,
                type=self._determine_output_type(outputs),
                confidence=llm_result.confidence,
                file_changes=self._merge_all_file_changes(outputs),
                findings=llm_result.findings,
                conflicts=conflicts,
                stats=self._calculate_stats(
                    outputs, llm_result.content, conflicts
                ),
                method=SynthesisMethod.SYNTHESIZE_LLM,
            )
        except Exception:
            return self._deduplicate_merge(outputs, conflicts)

    def _majority_vote(
        self, outputs: list[AgentOutput], conflicts: list[FileConflict]
    ) -> SynthesisResult:
        """Majority vote synthesis."""
        groups: list[dict[str, Any]] = []

        for output in outputs:
            added = False
            for group in groups:
                if (
                    self._calculate_similarity(
                        output.content, group["representative"].content
                    )
                    > 0.7
                ):
                    group["outputs"].append(output)
                    if output.confidence > group["representative"].confidence:
                        group["representative"] = output
                    added = True
                    break

            if not added:
                groups.append({
                    "outputs": [output],
                    "representative": output,
                })

        groups.sort(key=lambda g: len(g["outputs"]), reverse=True)
        winner: AgentOutput = groups[0]["representative"]
        vote_ratio = len(groups[0]["outputs"]) / len(outputs)

        return SynthesisResult(
            output=winner.content,
            type=winner.type,
            confidence=winner.confidence * vote_ratio,
            file_changes=winner.files_modified,
            findings=winner.findings,
            conflicts=conflicts,
            stats=self._calculate_stats(outputs, winner.content, conflicts),
            method=SynthesisMethod.MAJORITY_VOTE,
        )

    # =========================================================================
    # File Change Merging
    # =========================================================================

    def _merge_all_file_changes(
        self, outputs: list[AgentOutput]
    ) -> list[FileChange]:
        """Merge all file changes from outputs."""
        by_file: dict[str, list[FileChange]] = {}
        for output in outputs:
            for change in output.files_modified:
                by_file.setdefault(change.path, []).append(change)

        merged: list[FileChange] = []
        for changes in by_file.values():
            if len(changes) == 1:
                merged.append(changes[0])
            else:
                # Take the one with most content
                best = max(changes, key=lambda c: len(c.new_content))
                merged.append(best)

        return merged

    def _merge_file_changes(
        self,
        file_path: str,
        changes: list[FileChange],
        outputs: list[AgentOutput],
    ) -> dict[str, Any]:
        """Merge file changes for a single file."""
        conflicts: list[FileConflict] = []

        # Take the change with highest confidence
        best_change = changes[0]
        best_confidence = 0.0

        for change in changes:
            for output in outputs:
                if any(
                    f.path == file_path
                    and f.new_content == change.new_content
                    for f in output.files_modified
                ):
                    if output.confidence > best_confidence:
                        best_confidence = output.confidence
                        best_change = change
                    break

        # Detect significant differences
        for i in range(len(changes)):
            for j in range(i + 1, len(changes)):
                similarity = self._calculate_similarity(
                    changes[i].new_content, changes[j].new_content
                )
                if similarity < 0.8:
                    self._conflict_counter += 1
                    agent_ids = [
                        o.agent_id
                        for o in outputs
                        if any(f.path == file_path for f in o.files_modified)
                    ]
                    conflicts.append(FileConflict(
                        id=f"conflict-{self._conflict_counter}",
                        type=ConflictType.CODE_OVERLAP,
                        agent_ids=agent_ids,
                        description=f"Different versions of {file_path}",
                        conflicting_content=[
                            changes[i].new_content[:200],
                            changes[j].new_content[:200],
                        ],
                        severity=ConflictSeverity.HIGH,
                        file_path=file_path,
                    ))

        return {"merged": best_change, "conflicts": conflicts}

    # =========================================================================
    # Findings
    # =========================================================================

    def _extract_all_findings(self, outputs: list[AgentOutput]) -> list[str]:
        """Extract all findings from outputs, deduplicated."""
        all_findings: list[str] = []
        for output in outputs:
            all_findings.extend(output.findings)
        return list(dict.fromkeys(all_findings))  # Deduplicate, preserve order

    def _extract_findings_from_content(self, content: str) -> list[str]:
        """Extract findings from content text."""
        findings: list[str] = []
        for line in content.split("\n"):
            trimmed = line.strip()
            if (
                re.match(r"^[-*\u2022]\s+", trimmed)
                or re.match(r"^\d+\.\s+", trimmed)
                or "found:" in trimmed.lower()
                or "discovered:" in trimmed.lower()
            ):
                finding = re.sub(r"^[-*\u2022\d.]+\s+", "", trimmed)
                if len(finding) > 10:
                    findings.append(finding)
        return findings

    def _deduplicate_findings(
        self, findings: list[dict[str, Any]]
    ) -> list[dict[str, Any]]:
        """Deduplicate findings, keeping highest confidence."""
        deduplicated: list[dict[str, Any]] = []

        for f in findings:
            existing = None
            for d in deduplicated:
                if (
                    self._calculate_similarity(d["finding"], f["finding"])
                    > self._config.deduplication_threshold
                ):
                    existing = d
                    break

            if existing is not None:
                if f["confidence"] > existing["confidence"]:
                    existing["confidence"] = f["confidence"]
            else:
                deduplicated.append({
                    "finding": f["finding"],
                    "confidence": f["confidence"],
                })

        return deduplicated

    def _detect_finding_contradictions(
        self, findings: list[dict[str, Any]]
    ) -> list[FileConflict]:
        """Detect contradictions between findings."""
        conflicts: list[FileConflict] = []

        for i in range(len(findings)):
            for j in range(i + 1, len(findings)):
                contradictions = self._find_contradictions(
                    findings[i]["finding"], findings[j]["finding"]
                )
                for c in contradictions:
                    self._conflict_counter += 1
                    conflicts.append(FileConflict(
                        id=f"conflict-{self._conflict_counter}",
                        type=ConflictType.FACT_DISAGREEMENT,
                        agent_ids=[],
                        description=c["description"],
                        conflicting_content=[
                            c["content_a"],
                            c["content_b"],
                        ],
                        severity=ConflictSeverity.MEDIUM,
                    ))

        return conflicts

    # =========================================================================
    # Utilities
    # =========================================================================

    def _calculate_similarity(self, a: str, b: str) -> float:
        """Calculate content similarity using Jaccard index."""
        words_a = set(a.lower().split())
        words_b = set(b.lower().split())

        if not words_a and not words_b:
            return 1.0
        if not words_a or not words_b:
            return 0.0

        intersection = words_a & words_b
        union = words_a | words_b

        return len(intersection) / len(union) if union else 0.0

    def _calculate_combined_confidence(
        self, outputs: list[AgentOutput]
    ) -> float:
        """Calculate combined confidence from multiple outputs."""
        if not outputs:
            return 0.0

        total_weight = sum(o.confidence for o in outputs)
        avg_confidence = total_weight / len(outputs)

        # Boost if agents agree
        agreement_boost = self._calculate_agreement(outputs) * 0.1

        return min(1.0, avg_confidence + agreement_boost)

    def _calculate_agreement(self, outputs: list[AgentOutput]) -> float:
        """Calculate agreement rate between outputs."""
        if len(outputs) <= 1:
            return 1.0

        total_similarity = 0.0
        pairs = 0

        for i in range(len(outputs)):
            for j in range(i + 1, len(outputs)):
                total_similarity += self._calculate_similarity(
                    outputs[i].content, outputs[j].content
                )
                pairs += 1

        return total_similarity / pairs if pairs > 0 else 0.0

    def _determine_method(self, outputs: list[AgentOutput]) -> SynthesisMethod:
        """Determine synthesis method based on output types."""
        types = [o.type for o in outputs]

        if all(t == OutputType.CODE for t in types):
            return SynthesisMethod.MERGE_STRUCTURED

        if all(t == OutputType.RESEARCH for t in types):
            return SynthesisMethod.DEDUPLICATE

        if self._config.use_llm and self._config.llm_synthesizer is not None:
            return SynthesisMethod.SYNTHESIZE_LLM

        return self._config.default_method

    def _determine_output_type(self, outputs: list[AgentOutput]) -> OutputType:
        """Determine output type from multiple outputs."""
        types = {o.type for o in outputs}
        if len(types) == 1:
            return next(iter(types))
        return OutputType.MIXED

    def _calculate_stats(
        self,
        outputs: list[AgentOutput],
        synthesized_content: str,
        conflicts: list[FileConflict],
    ) -> SynthesisStats:
        """Calculate synthesis statistics."""
        total_content_length = sum(len(o.content) for o in outputs)
        synthesized_length = len(synthesized_content)

        return SynthesisStats(
            input_count=len(outputs),
            total_content_length=total_content_length,
            synthesized_length=synthesized_length,
            deduplication_rate=(
                1 - synthesized_length / total_content_length
                if total_content_length > 0
                else 0.0
            ),
            conflicts_detected=len(conflicts),
            conflicts_resolved=sum(
                1 for c in conflicts if c.resolution is not None
            ),
            agreement_rate=self._calculate_agreement(outputs),
        )

    def _create_empty_result(self) -> SynthesisResult:
        """Create an empty synthesis result."""
        return SynthesisResult(
            output="",
            type=OutputType.MIXED,
            confidence=0.0,
            stats=SynthesisStats(agreement_rate=1.0),
        )

    def _create_single_result(self, output: AgentOutput) -> SynthesisResult:
        """Create result from a single output."""
        return SynthesisResult(
            output=output.content,
            type=output.type,
            confidence=output.confidence,
            file_changes=list(output.files_modified),
            findings=list(output.findings),
            stats=SynthesisStats(
                input_count=1,
                total_content_length=len(output.content),
                synthesized_length=len(output.content),
                agreement_rate=1.0,
            ),
        )

    # =========================================================================
    # Events
    # =========================================================================

    def on(self, listener: SynthesizerEventListener) -> Callable[[], None]:
        """Subscribe to synthesizer events. Returns unsubscribe function."""
        self._listeners.append(listener)

        def unsubscribe() -> None:
            try:
                self._listeners.remove(listener)
            except ValueError:
                pass

        return unsubscribe

    def _emit(self, event: SynthesizerEvent) -> None:
        """Emit an event to all listeners."""
        for listener in self._listeners:
            try:
                listener(event)
            except Exception:
                pass


# =============================================================================
# Prompt Builder
# =============================================================================


def build_synthesis_prompt(
    outputs: list[AgentOutput], conflicts: list[FileConflict]
) -> str:
    """Create an LLM prompt for synthesis.

    Builds a structured prompt that asks an LLM to synthesize
    results from multiple agents, resolving any detected conflicts.
    """
    parts = [
        "You are synthesizing results from multiple AI agents. "
        "Combine their findings into a coherent, unified response.",
        "",
        "## Agent Outputs",
        "",
    ]

    for output in outputs:
        parts.append(
            f"### Agent: {output.agent_id} (confidence: {output.confidence})"
        )
        parts.append("")
        parts.append(output.content)
        parts.append("")

    if conflicts:
        parts.append("## Detected Conflicts")
        parts.append("")
        for conflict in conflicts:
            parts.append(f"- {conflict.type}: {conflict.description}")
        parts.append("")
        parts.append("Please resolve these conflicts in your synthesis.")

    parts.append("")
    parts.append("## Instructions")
    parts.append("1. Combine the key insights from all agents")
    parts.append("2. Remove duplicate information")
    parts.append("3. Resolve any contradictions")
    parts.append("4. Provide a unified, coherent response")
    parts.append("")
    parts.append(
        'Respond with JSON: { "content": "...", "findings": [...], '
        '"resolutions": [...], "confidence": 0.X }'
    )

    return "\n".join(parts)


# =============================================================================
# Factory
# =============================================================================


def create_result_synthesizer(
    config: ResultSynthesizerConfig | None = None,
) -> ResultSynthesizer:
    """Create a result synthesizer.

    Example::

        synthesizer = create_result_synthesizer(
            ResultSynthesizerConfig(
                conflict_resolution=ResolutionStrategy.CHOOSE_HIGHEST_CONFIDENCE,
                deduplication_threshold=0.85,
            )
        )

        result = await synthesizer.synthesize(agent_outputs)
    """
    return ResultSynthesizer(config)
