#!/usr/bin/env python3
"""Record authority inputs without altering the original project."""
import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PROJECT = ROOT.parents[1]
FILES = [
    '00-交付说明.md', 'prototype/mouse-voice/README.md',
    'prototype/mouse-voice/interaction.js', 'prototype/src/reference-product.js',
    'prototype/src/internal-stack.js', 'hardware/src/data.js',
    'docs/结构堆叠-CMF-制造约束.md', 'docs/engineering/05-接口与待定项.md',
    'docs/软硬件交互图-2026-09-16/README.md',
    'reference/selected-ID01-six-views.png',
]
records = []
for name in FILES:
    p = PROJECT / name
    raw = p.read_bytes()
    records.append({'path': str(p), 'bytes': len(raw), 'sha256': hashlib.sha256(raw).hexdigest()})
(ROOT / 'spec/source-manifest.json').write_text(json.dumps(records, ensure_ascii=False, indent=2) + '\n')
print(f'Recorded {len(records)} authority input hashes')
