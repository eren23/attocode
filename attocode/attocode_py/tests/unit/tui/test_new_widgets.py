"""Tests for new TUI widget dataclasses and data models.

Tests the data structures used by TUI widgets without requiring
Textual rendering infrastructure.
"""

from attocode.tui.widgets.error_detail_panel import ErrorDetail
from attocode.tui.widgets.file_change_summary import FileChange
from attocode.tui.widgets.diagnostics_panel import DiagnosticItem
from attocode.tui.widgets.collapsible_diff import CollapsibleFile
from attocode.tui.widgets.side_by_side_diff import SideBySideLine


class TestErrorDetail:
    def test_defaults(self):
        e = ErrorDetail(title="Syntax error", message="Unexpected token")
        assert e.title == "Syntax error"
        assert e.message == "Unexpected token"
        assert e.error_type == "error"
        assert e.tool_name == ""
        assert e.stack_trace == ""
        assert e.suggestion == ""
        assert e.timestamp == 0.0
        assert e.recoverable is True

    def test_custom_fields(self):
        e = ErrorDetail(
            title="Warning",
            message="Deprecated API",
            error_type="warning",
            tool_name="bash",
            suggestion="Use new API",
            recoverable=False,
        )
        assert e.error_type == "warning"
        assert e.tool_name == "bash"
        assert e.suggestion == "Use new API"
        assert e.recoverable is False

    def test_info_type(self):
        e = ErrorDetail(title="Notice", message="Cache hit", error_type="info")
        assert e.error_type == "info"


class TestFileChange:
    def test_defaults(self):
        fc = FileChange(path="src/main.py", change_type="modified")
        assert fc.path == "src/main.py"
        assert fc.change_type == "modified"
        assert fc.additions == 0
        assert fc.deletions == 0
        assert fc.tool_name == ""

    def test_with_line_counts(self):
        fc = FileChange(path="new.py", change_type="created", additions=50)
        assert fc.additions == 50
        assert fc.deletions == 0

    def test_deleted_file(self):
        fc = FileChange(path="old.py", change_type="deleted", deletions=30)
        assert fc.change_type == "deleted"
        assert fc.deletions == 30

    def test_renamed_file(self):
        fc = FileChange(path="renamed.py", change_type="renamed")
        assert fc.change_type == "renamed"


class TestDiagnosticItem:
    def test_ok_status(self):
        d = DiagnosticItem(name="Provider", status="ok", value="anthropic")
        assert d.name == "Provider"
        assert d.status == "ok"
        assert d.value == "anthropic"
        assert d.details == ""

    def test_warning_status(self):
        d = DiagnosticItem(name="Budget", status="warning", value="85%", details="Near limit")
        assert d.status == "warning"
        assert d.details == "Near limit"

    def test_error_status(self):
        d = DiagnosticItem(name="Loop", status="error", value="DETECTED")
        assert d.status == "error"


class TestCollapsibleFile:
    def test_defaults(self):
        f = CollapsibleFile(path="app.py", change_type="modified")
        assert f.path == "app.py"
        assert f.change_type == "modified"
        assert f.additions == 0
        assert f.deletions == 0
        assert f.diff_text == ""
        assert f.expanded is False

    def test_with_diff(self):
        f = CollapsibleFile(
            path="lib.py",
            change_type="modified",
            additions=5,
            deletions=2,
            diff_text="+new line\n-old line",
            expanded=True,
        )
        assert f.expanded is True
        assert f.additions == 5
        assert f.deletions == 2
        assert "+new line" in f.diff_text

    def test_created_file(self):
        f = CollapsibleFile(path="new.py", change_type="created", additions=100)
        assert f.change_type == "created"
        assert f.additions == 100


class TestSideBySideLine:
    def test_context_line(self):
        line = SideBySideLine(
            left_no=1, left_text="hello", left_type="context",
            right_no=1, right_text="hello", right_type="context",
        )
        assert line.left_no == 1
        assert line.right_no == 1
        assert line.left_type == "context"
        assert line.right_type == "context"

    def test_defaults(self):
        line = SideBySideLine()
        assert line.left_no is None
        assert line.left_text == ""
        assert line.left_type == "context"
        assert line.right_no is None
        assert line.right_text == ""
        assert line.right_type == "context"

    def test_remove_line(self):
        line = SideBySideLine(
            left_no=5, left_text="old code", left_type="remove",
            right_type="empty",
        )
        assert line.left_type == "remove"
        assert line.right_type == "empty"

    def test_add_line(self):
        line = SideBySideLine(
            left_type="empty",
            right_no=3, right_text="new code", right_type="add",
        )
        assert line.left_type == "empty"
        assert line.right_type == "add"
        assert line.right_text == "new code"

    def test_replace_line(self):
        line = SideBySideLine(
            left_no=10, left_text="old", left_type="remove",
            right_no=10, right_text="new", right_type="add",
        )
        assert line.left_type == "remove"
        assert line.right_type == "add"
