"""Tests for the intra-procedural data flow taint analysis engine.

Validates that tainted data from sources (user input, request params)
is correctly tracked through assignments to dangerous sinks.

NOTE: Test strings contain intentionally vulnerable code patterns
for DETECTOR testing. No dangerous code is executed.
"""

from __future__ import annotations

from attocode.integrations.security.dataflow import (
    DataFlowFinding,
    DataFlowReport,
    _extract_function_bodies,
    _extract_variables_from_expr,
    analyze_file,
    format_report,
)


class TestExtractVariables:
    def test_fstring_variable(self):
        result = _extract_variables_from_expr('f"SELECT * FROM {table}"')
        assert "table" in result

    def test_format_variable(self):
        result = _extract_variables_from_expr('"SELECT * FROM {}".format(table)')
        assert "table" in result

    def test_concat_variable(self):
        result = _extract_variables_from_expr('"SELECT * FROM " + table')
        assert "table" in result

    def test_template_literal(self):
        result = _extract_variables_from_expr('`SELECT * FROM ${table}`')
        assert "table" in result

    def test_filters_keywords(self):
        result = _extract_variables_from_expr("if True and x")
        assert "True" not in result
        assert "x" in result

    def test_simple_identifier(self):
        result = _extract_variables_from_expr("user_input")
        assert "user_input" in result


class TestFunctionExtraction:
    def test_python_functions(self):
        code = "def hello():\n    pass\n\ndef world():\n    pass\n"
        funcs = _extract_function_bodies(code, "python")
        assert len(funcs) == 2
        assert funcs[0][0] == "hello"
        assert funcs[1][0] == "world"

    def test_python_methods(self):
        code = "class Foo:\n    def bar(self):\n        pass\n    def baz(self):\n        pass\n"
        funcs = _extract_function_bodies(code, "python")
        assert len(funcs) == 2
        names = {f[0] for f in funcs}
        assert names == {"bar", "baz"}

    def test_js_function_keyword(self):
        code = "function hello() {\n  return 1;\n}\n"
        funcs = _extract_function_bodies(code, "javascript")
        assert len(funcs) >= 1
        assert funcs[0][0] == "hello"

    def test_js_arrow_function(self):
        code = "const handler = (req, res) => {\n  return 1;\n};\n"
        funcs = _extract_function_bodies(code, "javascript")
        assert len(funcs) >= 1
        assert funcs[0][0] == "handler"


class TestPythonTaint:
    """Test Python source-to-sink taint tracking.

    Each test writes a code snippet to a temp file and runs analyze_file.
    The snippets are DETECTOR test cases with intentionally vulnerable patterns.
    """

    def test_sqli_fstring(self, tmp_path):
        code = (
            "def get_user(uid):\n"
            "    data = request.args.get('id')\n"
            "    query = f'SELECT * FROM users WHERE id = {data}'\n"
            "    cursor.execute(query)\n"
        )
        (tmp_path / "v.py").write_text(code)
        findings = analyze_file(str(tmp_path / "v.py"), "python")
        assert any(f.cwe == "CWE-89" for f in findings)

    def test_cmdi(self, tmp_path):
        # Detector test: request data flowing to shell command
        code = (
            "def run():\n"
            "    cmd = request.form.get('c')\n"
            "    subprocess.call(cmd)\n"
        )
        (tmp_path / "c.py").write_text(code)
        findings = analyze_file(str(tmp_path / "c.py"), "python")
        assert any(f.cwe == "CWE-78" for f in findings)

    def test_path_traversal(self, tmp_path):
        code = (
            "def dl():\n"
            "    fname = request.args.get('f')\n"
            "    open(fname)\n"
        )
        (tmp_path / "p.py").write_text(code)
        findings = analyze_file(str(tmp_path / "p.py"), "python")
        assert any(f.cwe == "CWE-22" for f in findings)

    def test_safe_parameterized(self, tmp_path):
        code = (
            "def safe(uid):\n"
            "    cursor.execute('SELECT * FROM u WHERE id = ?', (uid,))\n"
        )
        (tmp_path / "s.py").write_text(code)
        findings = analyze_file(str(tmp_path / "s.py"), "python")
        assert not any(f.cwe == "CWE-89" for f in findings)

    def test_taint_propagation(self, tmp_path):
        code = (
            "def indirect():\n"
            "    raw = request.args.get('q')\n"
            "    cleaned = raw.strip()\n"
            "    q = 'SELECT * FROM t WHERE x = ' + cleaned\n"
            "    cursor.execute(q)\n"
        )
        (tmp_path / "t.py").write_text(code)
        findings = analyze_file(str(tmp_path / "t.py"), "python")
        assert len(findings) >= 1

    def test_safe_hardcoded(self, tmp_path):
        code = (
            "def safe():\n"
            "    name = 'hardcoded'\n"
            "    cursor.execute('SELECT * FROM u WHERE n = ?', (name,))\n"
        )
        (tmp_path / "s2.py").write_text(code)
        findings = analyze_file(str(tmp_path / "s2.py"), "python")
        assert len(findings) == 0

    def test_ssrf(self, tmp_path):
        code = (
            "def fetch():\n"
            "    url = request.args.get('url')\n"
            "    requests.get(url)\n"
        )
        (tmp_path / "ssrf.py").write_text(code)
        findings = analyze_file(str(tmp_path / "ssrf.py"), "python")
        assert any(f.cwe == "CWE-918" for f in findings)


class TestJavaScriptTaint:
    def test_sqli(self, tmp_path):
        code = (
            "function getUser(req, res) {\n"
            "  const uid = req.params.id;\n"
            '  const q = "SELECT * FROM u WHERE id = " + uid;\n'
            "  db.query(q);\n"
            "}\n"
        )
        (tmp_path / "v.js").write_text(code)
        findings = analyze_file(str(tmp_path / "v.js"), "javascript")
        assert any(f.cwe == "CWE-89" for f in findings)

    def test_safe_no_findings(self, tmp_path):
        code = (
            "function safe() {\n"
            '  const name = "hardcoded";\n'
            "  console.log(name);\n"
            "}\n"
        )
        (tmp_path / "s.js").write_text(code)
        findings = analyze_file(str(tmp_path / "s.js"), "javascript")
        assert len(findings) == 0


class TestFormatReport:
    def test_empty_report(self):
        report = DataFlowReport(findings=[], functions_analyzed=0, files_analyzed=5)
        text = format_report(report)
        assert "No data flow vulnerabilities detected" in text

    def test_report_with_findings(self):
        finding = DataFlowFinding(
            file_path="app.py", function_name="handler",
            source_line=5, source_desc="request_param",
            sink_line=8, sink_desc="sql_execute",
            tainted_var="query", cwe="CWE-89",
            message="SQL injection: tainted data reaches SQL execution",
        )
        report = DataFlowReport(findings=[finding], functions_analyzed=1, files_analyzed=1)
        text = format_report(report)
        assert "SQL Injection" in text
        assert "CWE-89" in text
        assert "app.py:8" in text

    def test_unsupported_language(self, tmp_path):
        (tmp_path / "main.go").write_text("package main\nfunc main() {}\n")
        findings = analyze_file(str(tmp_path / "main.go"), "go")
        assert findings == []
