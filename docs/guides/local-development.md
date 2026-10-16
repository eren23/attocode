# Local intelligence development

Follow [contributing](../contributing.md) for a bounded installation and test run.
The root is a virtual workspace; target `--package attocode-code-intel` when
selecting extras. PostgreSQL/Redis development infrastructure is described in
[service deployment](../intelligence.md). No global agent install is needed.

Use the existing clean-wheel and Docker CI checks for packaging changes. Keep
models optional and use [the quality controller](../intelligence-quality.md)
for large corpus work. Do not delete shared caches or frozen studies.
