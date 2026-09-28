"""Run a Python file inside the live UEFN editor via the 8765 listener (uefn_listener.py).

Usage:
    python uefn_exec.py script.py            # prints the JSON response
    python uefn_exec.py - < script.py        # read code from stdin

The script runs with the listener's globals (unreal, actor_sub, asset_sub, level_sub);
assign to `result` to return a value.
"""

import json
import sys
import urllib.request

PORT = 8765


def main() -> int:
    if len(sys.argv) < 2:
        print(__doc__)
        return 2
    code = sys.stdin.read() if sys.argv[1] == '-' else open(sys.argv[1], encoding='utf-8').read()
    body = json.dumps({'command': 'execute_python', 'params': {'code': code}}).encode()
    req = urllib.request.Request(f'http://127.0.0.1:{PORT}', data=body,
                                 headers={'Content-Type': 'application/json'})
    with urllib.request.urlopen(req, timeout=300) as resp:
        data = json.loads(resp.read())
    print(json.dumps(data, indent=1, ensure_ascii=False))
    inner = data.get('result') or {}
    return 0 if data.get('success') and not inner.get('stderr') else 1


if __name__ == '__main__':
    sys.exit(main())
