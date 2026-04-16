"""Unit tests for the rule-bench corpus loader."""

from __future__ import annotations

from pathlib import Path

import pytest

from eval.meta_harness.rule_bench.corpus import CorpusLoader


def _write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


@pytest.fixture()
def synthetic_corpus(tmp_path: Path) -> dict[str, Path]:
    """Build a 3-source synthetic corpus inside tmp_path."""
    community = tmp_path / "community"
    attocode = tmp_path / "attocode"
    legacy = tmp_path / "legacy"

    # Community: pack-a + pack-b
    _write(
        community / "pack-a" / "manifest.yaml",
        "name: pack-a\nversion: '1.0.0'\nlanguages: [python]\n",
    )
    _write(
        community / "pack-a" / "fixtures" / "rule-x" / "positive.py",
        "value = compute()  # expect: rule-x\n",
    )
    _write(
        community / "pack-a" / "fixtures" / "rule-x" / "negative.py",
        "value = safe_compute()  # ok: rule-x\n",
    )
    _write(
        community / "pack-b" / "manifest.yaml",
        "name: pack-b\nversion: '1.0.0'\nlanguages: [go]\n",
    )
    _write(
        community / "pack-b" / "fixtures" / "rule-y" / "positive.go",
        "package main\nfunc f() { format(s) } // expect: rule-y\n",
    )

    # Attocode hand-labeled
    _write(
        attocode / "python" / "py-foo.py",
        "x = 1  # expect: py-foo\ny = 2  # ok: py-foo\n",
    )

    # Legacy CWE-organized
    _write(
        legacy / "python" / "CWE-89" / "tp_sqli.py",
        "execute(query)  # expect: sqli-rule\n",
    )

    return {
        "community_dir": community,
        "attocode_dir": attocode,
        "legacy_dir": legacy,
    }


class TestCorpusLoader:
    def test_disable_community(self, synthetic_corpus: dict[str, Path]) -> None:
        loader = CorpusLoader(
            include_community=False,
            community_dir=synthetic_corpus["community_dir"],
            attocode_dir=synthetic_corpus["attocode_dir"],
            legacy_dir=synthetic_corpus["legacy_dir"],
        )
        samples = list(loader.iter_samples())
        for s in samples:
            assert s.pack not in {"pack-a", "pack-b"}

    def test_disable_attocode(self, synthetic_corpus: dict[str, Path]) -> None:
        loader = CorpusLoader(
            include_community=False,
            include_attocode=False,
            community_dir=synthetic_corpus["community_dir"],
            attocode_dir=synthetic_corpus["attocode_dir"],
            legacy_dir=synthetic_corpus["legacy_dir"],
        )
        samples = list(loader.iter_samples())
        # Only legacy left
        for s in samples:
            assert s.pack == "legacy"

    def test_disable_legacy(self, synthetic_corpus: dict[str, Path]) -> None:
        loader = CorpusLoader(
            include_community=False,
            include_legacy=False,
            community_dir=synthetic_corpus["community_dir"],
            attocode_dir=synthetic_corpus["attocode_dir"],
            legacy_dir=synthetic_corpus["legacy_dir"],
        )
        samples = list(loader.iter_samples())
        for s in samples:
            assert s.pack == "attocode"

    def test_skips_files_without_annotations(self, tmp_path: Path) -> None:
        attocode = tmp_path / "attocode"
        _write(attocode / "python" / "scaffold.py", "import json\nx = json.loads('{}')\n")
        loader = CorpusLoader(
            include_community=False,
            include_legacy=False,
            attocode_dir=attocode,
        )
        samples = list(loader.iter_samples())
        assert samples == []

    def test_parses_expect_and_ok(
        self, synthetic_corpus: dict[str, Path],
    ) -> None:
        loader = CorpusLoader(
            include_community=False,
            include_legacy=False,
            attocode_dir=synthetic_corpus["attocode_dir"],
        )
        samples = list(loader.iter_samples())
        assert len(samples) == 1
        sample = samples[0]
        assert sample.language == "python"
        kinds = {f.kind for f in sample.expected_findings}
        assert "expect" in kinds
        assert "ok" in kinds
        assert sample.has_negative_assertions is True

    def test_parses_ruleid_alias(self, tmp_path: Path) -> None:
        # semgrep "# ruleid:" alias should map to "expect" via Step-1 normalization
        attocode = tmp_path / "attocode"
        _write(
            attocode / "python" / "semgrep_compat.py",
            "value = something()  # ruleid: dangerous-call\n",
        )
        loader = CorpusLoader(
            include_community=False,
            include_legacy=False,
            attocode_dir=attocode,
        )
        samples = list(loader.iter_samples())
        assert len(samples) == 1
        finding = samples[0].expected_findings[0]
        assert finding.kind == "expect"  # normalized from "ruleid"
        assert finding.rule_id == "dangerous-call"

    def test_legacy_corpus_attaches_cwe(
        self, synthetic_corpus: dict[str, Path],
    ) -> None:
        loader = CorpusLoader(
            include_community=False,
            include_attocode=False,
            legacy_dir=synthetic_corpus["legacy_dir"],
        )
        samples = list(loader.iter_samples())
        assert len(samples) == 1
        assert samples[0].cwe == "CWE-89"
        assert samples[0].pack == "legacy"

    def test_sample_count_by_language(
        self, synthetic_corpus: dict[str, Path],
    ) -> None:
        loader = CorpusLoader(
            include_community=False,
            attocode_dir=synthetic_corpus["attocode_dir"],
            legacy_dir=synthetic_corpus["legacy_dir"],
        )
        counts = loader.sample_count_by_language()
        assert counts.get("python") == 2  # 1 attocode + 1 legacy

    def test_handles_missing_directories(self, tmp_path: Path) -> None:
        loader = CorpusLoader(
            community_dir=tmp_path / "nope1",
            attocode_dir=tmp_path / "nope2",
            legacy_dir=tmp_path / "nope3",
        )
        samples = list(loader.iter_samples())
        assert samples == []
