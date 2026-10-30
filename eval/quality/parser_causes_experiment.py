"""Temporary GHA-only raw observations for previously captured parser failures."""
from __future__ import annotations

import argparse
import hashlib
import importlib.metadata
import json
import os
import shutil
import subprocess
import sys
import threading
import urllib.request
import warnings
from dataclasses import asdict
from pathlib import Path
from unittest.mock import patch

from eval.quality.experiment_evidence import Journal, assert_engine, read_source
from eval.quality.native_experiment import ParserObserver, distribution_identity, grammar_identity
from eval.quality.runner import REPO, write_json

DESIGN = Path(__file__).with_name('experiments') / 'parser-causes.json'


def language_identity(language):
    return {name: getattr(language, name, None) for name in
            ('name', 'abi_version', 'semantic_version', 'node_kind_count', 'parse_state_count')}


def worker(root, index):
    import tree_sitter as ts
    import tree_sitter_language_pack as pack
    from attocode_intel._internal.integrations.context import ts_parser
    from attocode_intel._internal.integrations.context.codebase_ast import (
        detect_language,
        parse_file,
    )

    frozen = json.loads(DESIGN.read_bytes())
    spec = frozen['inputs'][index]
    selected = Path(os.environ['ATTOCODE_EXPERIMENT_ENGINE'])
    journal = Journal(root / 'evidence' / f'input-{index:02d}' / 'journal', 4 * 2**20)
    state = {'index': index, 'path': spec['path'], 'pid': os.getpid(),
             'thread_id': threading.get_ident(), 'phase': 'identity', 'generation': 0}

    def record(request, value):
        return journal.response({**state, **request}, value)

    cache = Path(os.environ['QUALITY_GRAMMAR_CACHE'])
    pack.configure(cache_dir=str(cache))
    record({'event': 'origin_before'}, assert_engine(selected))
    record({'event': 'grammar_before'}, grammar_identity(cache))
    raw_path = root / 'work' / 'inputs' / str(index)
    raw = raw_path.read_bytes()
    if len(raw) != spec['bytes'] or hashlib.sha256(raw).hexdigest() != spec['sha256']:
        raise ValueError('selected raw source identity mismatch')
    content = read_source(raw_path, **frozen['decode'])
    source = content.encode('utf-8')
    record({'event': 'input'}, {'spec': spec, 'raw_bytes': len(raw),
           'raw_sha256': hashlib.sha256(raw).hexdigest(), 'canonical_bytes': len(source),
           'canonical_sha256': hashlib.sha256(source).hexdigest(), 'decode': frozen['decode']})
    language = detect_language(spec['path'])
    base = ts_parser._get_parser(language)
    if base is None:
        grammar_module = ts_parser.EXTRA_GRAMMAR_MODULES.get(language)
        lang = ts_parser.GenericTreeSitterExtractor()._get_language_obj(grammar_module, language)
    else:
        lang = base.language
        base.reset()
    if lang is None:
        raise ValueError('selected product grammar unavailable')
    record({'event': 'language'}, {'language': language, 'identity': language_identity(lang),
           'individual_module': (ts_parser.LANGUAGE_CONFIGS[language].grammar_module
                                 if language in ts_parser.LANGUAGE_CONFIGS else grammar_module)})
    modules = {'html': 'tree-sitter-html', 'yaml': 'tree-sitter-yaml', 'json': 'tree-sitter-json',
               'go': 'tree-sitter-go', 'rust': 'tree-sitter-rust', 'ocaml': 'tree-sitter-ocaml'}
    try:
        record({'event': 'individual_distribution'}, distribution_identity((modules[language],)))
    except importlib.metadata.PackageNotFoundError:
        record({'event': 'individual_distribution'}, {'absent': modules[language]})

    def attempt(data, grammar, variant, budget, label):
        state.update(phase='isolated', generation=state['generation'] + 1,
                     variant=variant, budget=budget, label=label)
        parser = ts.Parser(grammar)
        proxy = ParserObserver(parser, record, language)
        record({'event': 'constructed'}, {'grammar': language_identity(grammar),
               'parser_id': id(parser), 'source_sha256': hashlib.sha256(data).hexdigest(),
               'bytes': len(data)})
        proxy.reset()
        proxy.timeout_micros = budget
        tree = None
        try:
            tree = proxy.parse(data)
        except ValueError:
            # A native abort is an observation; reset/capture faults remain fatal.
            pass
        finally:
            proxy.reset()
        record({'event': 'tree'}, None if tree is None else {
            'root_type': tree.root_node.type, 'end_byte': tree.root_node.end_byte,
            'start_byte': tree.root_node.start_byte, 'has_error': tree.root_node.has_error})
        del tree, proxy, parser

    for budget in frozen['budgets_micros']:
        attempt(source, lang, 'product', budget, 'selected_input')
    if language == 'ocaml':
        implementation = ts_parser._cached_pack_language('ocaml')
        interface = ts_parser._cached_pack_language('ocaml_interface')
        if implementation is None or interface is None:
            raise ValueError('explicitly acquired OCaml variants missing')
        record({'event': 'ocaml_variants'}, {
            'product_equals_pack_implementation': lang == implementation,
            'implementation': language_identity(implementation), 'interface': language_identity(interface)})
        for budget in frozen['budgets_micros']:
            attempt(source, interface, 'ocaml_interface', budget, 'selected_input')
        for control in frozen['controls']:
            data = control['source'].encode()
            for variant, grammar in (('ocaml', implementation), ('ocaml_interface', interface)):
                attempt(data, grammar, variant, frozen['production_timeout_micros'], control['name'])

    state.update(phase='product', label='parse_file', variant='unchanged',
                 budget=frozen['production_timeout_micros'])
    original = ts_parser.bounded_parse

    def observe(parser, data):
        return original(ParserObserver(parser, record, language), data)

    if frozen['production_timeout_micros'] != ts_parser.PARSE_TIMEOUT_MICROS:
        raise ValueError('production parser policy changed')
    with patch.object(ts_parser, 'bounded_parse', observe):
        result = parse_file(spec['path'], content)
    record({'event': 'product'}, {'parsing_tier': result.parsing_tier,
           'symbol_count': result.symbol_count, 'content_sha256': result.content_sha256,
           'failures': [asdict(f) for f in result.parse_failures]})
    record({'event': 'grammar_after'}, grammar_identity(cache))
    record({'event': 'origin_after'}, assert_engine(selected))
    write_json(root / 'evidence' / f'input-{index:02d}' / 'complete.json',
               {'complete': True, 'index': index, 'pid': os.getpid(),
                'isolated_attempts': state['generation'], 'journal_bytes': journal.bytes})


def run(root):
    frozen = json.loads(DESIGN.read_bytes())
    cache = root / 'cache' / 'grammars'
    shutil.copytree(Path(os.environ['QUALITY_GRAMMAR_CACHE']), cache)
    os.environ['QUALITY_GRAMMAR_CACHE'] = str(cache)
    inputs = root / 'work' / 'inputs'
    inputs.mkdir()
    for index, spec in enumerate(frozen['inputs']):
        url = f"https://raw.githubusercontent.com/{spec['repo']}/{spec['commit']}/{spec['path']}"
        with urllib.request.urlopen(url, timeout=20) as response:
            raw = response.read(spec['bytes'] + 1)
        if len(raw) != spec['bytes'] or hashlib.sha256(raw).hexdigest() != spec['sha256']:
            raise ValueError(f'raw source identity mismatch: {index}')
        (inputs / str(index)).write_bytes(raw)
        write_json(root / 'evidence' / f'acquired-{index:02d}.json',
                   {'spec': spec, 'bytes': len(raw), 'sha256': hashlib.sha256(raw).hexdigest(),
                    'url': url})
        subprocess.run([sys.executable, '-m', 'eval.quality.parser_causes_experiment',
                        '--root', str(root), '--worker', str(index)],
                       cwd=REPO, env=os.environ.copy(), check=True, timeout=35)
    write_json(root / 'evidence' / 'protocol-complete.json',
               {'inputs': len(frozen['inputs']), 'isolated_attempts': frozen['expected_attempts'],
                'production_timeout_micros': frozen['production_timeout_micros'],
                'interpretation': 'Raw observations only; independent admission required.'})


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root', type=Path, required=True)
    parser.add_argument('--worker', type=int, required=True)
    args = parser.parse_args()
    warnings.filterwarnings('ignore', category=DeprecationWarning)
    worker(args.root, args.worker)
