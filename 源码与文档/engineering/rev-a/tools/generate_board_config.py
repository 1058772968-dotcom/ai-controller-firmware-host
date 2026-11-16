#!/usr/bin/env python3
import json
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
b=json.loads((ROOT/'spec/board.json').read_text())
pins=b['pins']; values=list(pins.values())
assert len(values)==len(set(values)), 'GPIO collision'
assert not set(values).intersection(b['reserved_gpio']), 'Reserved/PSRAM GPIO assigned'
assert pins['USB_DM']==19 and pins['USB_DP']==20
lines=['/* Generated from spec/board.json. Do not edit. */','#ifndef AIKEY_BOARD_CONFIG_H','#define AIKEY_BOARD_CONFIG_H',f'#define AK_BOARD_REVISION "{b["revision"]}"']
lines += [f'#define AK_PIN_{name} {pin}' for name,pin in pins.items()]
lines += [f'#define AK_{name.upper()}_MS {value}u' for name,value in b['timing_ms'].items()]
lines += [f'#define AK_MIC_SETTLE_MS {b["audio"]["settle_ms"]}u','#endif','']
target=ROOT/'firmware/core/board_config.h';target.write_text('\n'.join(lines))
print(f'Validated {len(pins)} pins and generated {target.name}')
