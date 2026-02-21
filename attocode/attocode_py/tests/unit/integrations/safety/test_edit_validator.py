"""Tests for the edit validator module."""

from attocode.integrations.safety.edit_validator import (
    EditValidator,
    ValidationResult,
    LANGUAGE_MAP,
)


class TestValidationResult:
    def test_defaults(self):
        r = ValidationResult(valid=True)
        assert r.valid is True
        assert r.language == ""
        assert r.errors == []
        assert r.warnings == []


class TestEditValidatorPython:
    def setup_method(self):
        self.validator = EditValidator()

    def test_valid_python(self):
        result = self.validator.validate("test.py", "x = 1\nprint(x)\n")
        assert result.valid is True
        assert result.language == "python"
        assert result.errors == []

    def test_invalid_python(self):
        result = self.validator.validate("test.py", "def foo(\n")
        assert result.valid is False
        assert result.language == "python"
        assert len(result.errors) == 1

    def test_empty_python(self):
        result = self.validator.validate("test.py", "")
        assert result.valid is True
        assert result.language == "python"


class TestEditValidatorJSON:
    def setup_method(self):
        self.validator = EditValidator()

    def test_valid_json(self):
        result = self.validator.validate("data.json", '{"key": "value"}')
        assert result.valid is True
        assert result.language == "json"

    def test_invalid_json(self):
        result = self.validator.validate("data.json", '{"key": }')
        assert result.valid is False
        assert result.language == "json"
        assert len(result.errors) == 1

    def test_json_array(self):
        result = self.validator.validate("data.json", '[1, 2, 3]')
        assert result.valid is True


class TestEditValidatorYAML:
    def setup_method(self):
        self.validator = EditValidator()

    def test_valid_yaml(self):
        result = self.validator.validate("config.yaml", "key: value\nlist:\n  - item1\n")
        assert result.valid is True
        assert result.language == "yaml"

    def test_invalid_yaml(self):
        result = self.validator.validate("config.yml", ":\n  - :\n    bad: [unclosed")
        assert result.valid is False
        assert result.language == "yaml"

    def test_yml_extension(self):
        result = self.validator.validate("file.yml", "a: 1")
        assert result.language == "yaml"


class TestEditValidatorUnknown:
    def setup_method(self):
        self.validator = EditValidator()

    def test_unknown_extension(self):
        result = self.validator.validate("file.xyz", "anything")
        assert result.valid is True
        assert result.language == "unknown"

    def test_no_extension(self):
        result = self.validator.validate("Makefile", "all: build")
        assert result.valid is True
        assert result.language == "unknown"


class TestValidateEdit:
    def setup_method(self):
        self.validator = EditValidator()

    def test_valid_edit(self):
        result = self.validator.validate_edit("test.py", "x = 1", "x = 2")
        assert result.valid is True
        assert result.errors == []

    def test_edit_introduces_error(self):
        result = self.validator.validate_edit("test.py", "x = 1", "def foo(")
        assert result.valid is False
        assert len(result.errors) > 0

    def test_edit_preserves_preexisting_error(self):
        # Both original and edited are invalid -- downgrade to warning
        result = self.validator.validate_edit("test.py", "def bar(", "def foo(")
        assert result.valid is True
        assert result.errors == []
        assert len(result.warnings) > 0

    def test_language_map_coverage(self):
        assert LANGUAGE_MAP[".py"] == "python"
        assert LANGUAGE_MAP[".json"] == "json"
        assert LANGUAGE_MAP[".ts"] == "typescript"
        assert LANGUAGE_MAP[".yaml"] == "yaml"
