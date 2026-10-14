"""Two-phase wheel upgrade check. Run prepare under the old installed version.

Run verify with the same interpreter after installing the candidate. This never
starts a client/model or writes outside the explicitly supplied disposable root.
"""
from __future__ import annotations

import argparse
import asyncio
import hashlib
import importlib.metadata
import json
from pathlib import Path


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


async def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('phase', choices=['prepare', 'verify'])
    parser.add_argument('root', type=Path)
    args = parser.parse_args()
    root = args.root.resolve()
    state_path = root / 'upgrade-state.json'
    from attocode_intel.gateway import OperationGateway
    from attocode_intel.onboarding import configure_client, diagnose
    if args.phase == 'prepare':
        root.mkdir(exist_ok=False, parents=True)
        (root / 'helper.py').write_text('def retained_helper(): return 1\n')
        configs = {}
        for client in ('codex', 'claude', 'cursor'):
            result = configure_client(client, str(root), profile='daily')
            config = result['config']
            configs[str(Path(config).relative_to(root))] = digest(config)
        state = {'old_version': importlib.metadata.version('attocode-code-intel'), 'configs': configs}
    else:
        state = json.loads(state_path.read_text())
        assert {name:digest(root/name) for name in state['configs']} == state['configs']
        for client in ('codex', 'claude', 'cursor'):
            result = await diagnose(client, str(root))
            assert result['status'] != 'not configured', result
    gateway = OperationGateway(str(root), 'daily', watch=False)
    try:
        response = await gateway.execute('inspect_symbol', {'symbol_name':'retained_helper', 'file_path':'helper.py'})
        assert not response.isError and response.structuredContent['data']['definition']['file_path'] == 'helper.py'
        if args.phase == 'verify':
            (root / 'helper.py').write_text('def upgraded_helper(): return 2\n')
            old = await gateway.execute('search_symbols', {'name':'retained_helper'})
            assert all(r['name'] != 'retained_helper' for r in old.structuredContent['data'])
            new = await gateway.execute('inspect_symbol', {'symbol_name':'upgraded_helper', 'file_path':'helper.py'})
            assert 'return 2' in json.dumps(new.structuredContent['data'])
    finally:
        await gateway.close()
    if args.phase == 'prepare':
        state_path.write_text(json.dumps(state, indent=2) + '\n')
    print(json.dumps({'phase':args.phase, 'from':state['old_version'],
                      'installed':importlib.metadata.version('attocode-code-intel'), 'passed':True}))


if __name__ == '__main__':
    asyncio.run(main())
