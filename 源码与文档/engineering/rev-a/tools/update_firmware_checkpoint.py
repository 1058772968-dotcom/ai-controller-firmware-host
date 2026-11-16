#!/usr/bin/env python3
"""Record the current validated firmware build without claiming hardware tests."""
import argparse,hashlib,json
from pathlib import Path
r=Path(__file__).resolve().parents[1]
p=argparse.ArgumentParser();p.add_argument('--log',required=True);a=p.parse_args()
if 'Project build complete.' not in (r/a.log).read_text():raise SystemExit('No successful build in supplied log')
path=r/'reports/firmware-build-current.json';b=json.loads(path.read_text());sha=lambda p:hashlib.sha256(p.read_bytes()).hexdigest()
elf=Path.home()/'.cache/ai-key-rev-a/build/aikey_rev_a.elf'
for name in ('usb-descriptor-check.json','ble-descriptor-check.json','wifi-elf-check.json'):
    evidence=json.loads((r/'reports'/name).read_text())
    if not evidence['status'].endswith('PASS') or evidence['elf_sha256']!=sha(elf):raise SystemExit('ELF evidence stale: '+name)
native=json.loads((r/'reports/firmware-native-tests.json').read_text());assert native['status']=='PASS'
for case in native['tests']:
    for name,digest in case['source_sha256'].items():assert sha(r/name)==digest,'Native test source changed: '+name
b.update(status='BUILD_AND_NATIVE_TESTS_PASS_FEATURES_INCOMPLETE',features=[
 'USB mouse + control + UAC2 mono16k; separate USB-only settings report ID 3',
 'BLE HOGP + encrypted GATT; one persisted bond; explicit USB re-pair command',
 'USB priority and transport-generation held-key quarantine',
 'IMU SPI relative pointing; held-trigger PDM audio; MAX17048 and DRV2605L state machines',
 'Staged, validated 160-byte Wi-Fi configuration; NVS commit; apply on next EN reset',
 'Wi-Fi STA + PSK TLS audio, per-frame ACK, held-trigger gate and link-loss cutoff'],
 incomplete=['Physical pairing/enumeration/NVS/audio/sensors/actuation unavailable without prototype','Production USB identity and physical power/RF/performance qualification'],
 evidence=[a.log,'reports/firmware-native-tests.json','reports/usb-descriptor-check.json','reports/ble-descriptor-check.json','reports/wifi-elf-check.json','reports/wifi-audio-validation.json','reports/wifi-browser-validation.json'],physical_validation=False)
files=sorted((r/'firmware/core').glob('*.[ch]'))+sorted((r/'firmware/main').glob('*.[ch]'))+[r/n for n in ('spec/board.json','firmware/sdkconfig','firmware/sdkconfig.defaults','firmware/dependencies.lock','firmware/partitions.csv','firmware/main/CMakeLists.txt')]
b['sources']={str(p.relative_to(r)):sha(p) for p in files}
for artifact in b['artifacts']:
    p=Path(artifact['path']);artifact.update(bytes=p.stat().st_size,sha256=sha(p))
path.write_text(json.dumps(b,indent=2)+'\n');print(b['status'],len(native['tests']),'native suites')
