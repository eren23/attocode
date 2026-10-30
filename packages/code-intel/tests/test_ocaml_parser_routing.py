"""OCaml interface grammar routing, provider identity and cache boundaries."""
import importlib
import sys
from types import SimpleNamespace

import pytest
import tree_sitter as ts
from attocode_intel._internal.integrations.context import syntax_evidence, ts_parser

ROUTES = [('api.mli', 'ocaml', 'ocaml_interface'), ('api.ml', 'ocaml', 'ocaml'),
          ('view.tsx', 'typescript', 'tsx'), ('api.mli', 'go', 'go'),
          ('api.mli.ts', 'typescript', 'typescript')]


@pytest.mark.parametrize('path,language,expected', ROUTES)
def test_structure_parser_route(path, language, expected, monkeypatch):
    selected = []
    monkeypatch.setattr(ts_parser, '_get_parser', lambda name: selected.append(name))
    assert ts_parser.ts_parse_file(path, '', language) is None
    assert selected == [expected], 'ocaml interface: structure uses wrong grammar'


@pytest.mark.parametrize('path,language,expected', ROUTES)
def test_reference_parser_route(path, language, expected, monkeypatch):
    selected = []
    monkeypatch.setattr(ts_parser, '_get_parser', lambda name: selected.append(name))
    assert syntax_evidence.syntax_tree(path, '', language) is None
    assert selected == [expected], 'ocaml interface: references use wrong grammar'


def providers(monkeypatch, missing=False):
    monkeypatch.setattr(ts_parser, '_TS_AVAILABLE', True)
    monkeypatch.setattr(ts_parser, '_PARSERS', SimpleNamespace())
    monkeypatch.setattr(ts, 'Language', lambda capsule: capsule)
    monkeypatch.setattr(ts, 'Parser', lambda language: SimpleNamespace(language=language))
    original = importlib.import_module
    module = SimpleNamespace(language_ocaml=lambda: 'implementation',
                             language_ocaml_interface=lambda: 'interface')
    def load(name, *args, **kwargs):
        if name == 'tree_sitter_ocaml':
            if missing:
                raise ImportError('individual grammar intentionally absent')
            return module
        return original(name, *args, **kwargs)
    monkeypatch.setattr(importlib, 'import_module', load)


def test_individual_interface_parser_has_its_own_cached_variant(monkeypatch):
    providers(monkeypatch)
    implementation = ts_parser._get_parser('ocaml')
    interface = ts_parser._get_parser('ocaml_interface')
    assert interface is not None, 'ocaml interface: declared grammar variant unavailable'
    assert implementation.language == 'implementation' and interface.language == 'interface'
    assert interface is not implementation
    assert ts_parser._get_parser('ocaml') is implementation
    assert ts_parser._get_parser('ocaml_interface') is interface


def test_missing_interface_cache_never_acquires_or_substitutes_implementation(monkeypatch):
    providers(monkeypatch, missing=True)
    unexpected = []
    pack = SimpleNamespace(downloaded_languages=lambda: ['ocaml'],
                           get_language=lambda name: unexpected.append(name),
                           download=lambda names: unexpected.append(names))
    monkeypatch.setitem(sys.modules, 'tree_sitter_language_pack', pack)
    assert ts_parser._get_parser('ocaml_interface') is None
    assert ts_parser._get_parser('ocaml_interface') is None
    assert not unexpected, 'ocaml interface: missing grammar triggered acquisition/substitution'


def test_generic_individual_variants_do_not_alias_one_cache_entry(monkeypatch):
    providers(monkeypatch)
    extractor = ts_parser.GenericTreeSitterExtractor()
    assert extractor._get_language_obj('tree_sitter_ocaml', 'ocaml') == 'implementation'
    assert extractor._get_language_obj('tree_sitter_ocaml', 'ocaml_interface') == 'interface', 'ocaml interface: generic individual variant aliases implementation'


def test_generic_cached_pack_variants_do_not_alias_one_cache_entry(monkeypatch):
    providers(monkeypatch, missing=True)
    selected = []
    def cached(name):
        selected.append(name)
        return name
    monkeypatch.setattr(ts_parser, '_cached_pack_language', cached)
    extractor = ts_parser.GenericTreeSitterExtractor()
    assert extractor._get_language_obj('tree_sitter_ocaml', 'ocaml') == 'ocaml'
    assert extractor._get_language_obj('tree_sitter_ocaml', 'ocaml_interface') == 'ocaml_interface', 'ocaml interface: generic cached variant aliases implementation'
    assert selected == ['ocaml', 'ocaml_interface']
