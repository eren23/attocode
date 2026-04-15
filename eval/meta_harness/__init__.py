"""Meta-harness optimization for code-intel search and retrieval.

Adapts the Stanford IRIS Lab meta-harness pattern (arXiv:2603.28052) to
automatically optimize code-intel scoring parameters via an outer loop
(Claude proposes configs) and inner loop (benchmark evaluates them).
"""
