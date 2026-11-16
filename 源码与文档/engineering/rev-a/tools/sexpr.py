"""Small, dependency-free helpers; KiCad files remain the source of truth."""
import copy
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import uuid

ROOT = Path(__file__).resolve().parents[1]
APP = Path(os.environ.get('KICAD_APP', '/Applications/KiCad/KiCad.app'))
SHARE = APP / 'Contents/SharedSupport'
CLI = os.environ.get('KICAD_CLI', str(APP / 'Contents/MacOS/kicad-cli'))
KP = os.environ.get('KICAD_PYTHON', str(APP / 'Contents/Frameworks/Python.framework/Versions/Current/bin/python3'))

class Atom(str):
    pass

def parse(s):
    tokens = re.findall(r'"(?:\\.|[^"\\])*"|[()]|[^\s()]+', s)
    stack = []
    root = None
    for token in tokens:
        if token == '(':
            node = []
            if stack:
                stack[-1].append(node)
            else:
                if root is not None:
                    raise ValueError('Multiple S-expressions')
                root = node
            stack.append(node)
        elif token == ')':
            if not stack:
                raise ValueError('Unbalanced close')
            stack.pop()
        else:
            if not stack:
                raise ValueError('Unexpected token')
            stack[-1].append(json.loads(token) if token.startswith('"') else Atom(token))
    if stack or root is None:
        raise ValueError('Unbalanced expression')
    return root

def dump(x, level=0):
    if isinstance(x, Atom):
        return str(x)
    if not isinstance(x, list):
        return json.dumps(x, ensure_ascii=False)
    head, subs = [], []
    for c in x:
        (subs if isinstance(c, list) else head).append(c)
    if not subs:
        return '(' + ' '.join(dump(c) for c in head) + ')'
    return '(' + ' '.join(dump(c) for c in head) + '\n' + '\n'.join('  '*(level+1) + dump(c, level+1) for c in subs) + '\n' + '  '*level + ')'

def children(x, key):
    return [c for c in x if isinstance(c, list) and c and c[0] == key]

def one(x, key, default=None):
    return next(iter(children(x, key)), default)

def prop(x, key, default=''):
    return next((str(p[2]) for p in children(x, 'property') if p[1] == key), default)

def set_prop(x, name, val):
    for p in children(x, 'property'):
        if p[1] == name:
            p[2] = val
            return
    x.append(parse('(property %s %s (at 0 0 0) (hide yes) (effects (font (size 1.27 1.27))))' % (json.dumps(name), json.dumps(val))))

def uid(name):
    return str(uuid.uuid5(uuid.NAMESPACE_URL, 'aikey-rev-a/' + name))

def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()

def save_json(path, data):
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    Path(path).write_text(json.dumps(data, ensure_ascii=False, indent=2) + '\n')

def run(args, cwd=None):
    result = subprocess.run([str(a) for a in args], cwd=cwd, text=True, capture_output=True)
    if result.returncode:
        raise RuntimeError('%s\n%s\n%s' % (' '.join(map(str, args)), result.stdout, result.stderr))
    return result.stdout

def project(path):
    p = Path(path).resolve()
    if p.is_file():
        p = p.parent
    files = list(p.glob('*.kicad_pro'))
    if len(files) != 1:
        raise ValueError('Expected one .kicad_pro in ' + str(p))
    return p, files[0].stem

def source_digest(p):
    paths = [f for f in p.rglob('*') if f.is_file() and 'build' not in f.relative_to(p).parts and
             (f.suffix in ('.kicad_sch', '.kicad_pcb', '.kicad_pro', '.kicad_dru', '.kicad_sym', '.kicad_mod') or
              f.name in ('sym-lib-table', 'fp-lib-table', 'requirements.json', 'simulation.json', 'procurement.json', 'placement_overrides.json'))]
    payload = {str(f.relative_to(p)): sha(f) for f in sorted(paths)}
    return hashlib.sha256(json.dumps(payload, sort_keys=True).encode()).hexdigest(), payload
