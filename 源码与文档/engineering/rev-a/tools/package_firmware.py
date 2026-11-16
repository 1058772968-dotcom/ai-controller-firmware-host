#!/usr/bin/env python3
"""Package only the current hash-verified build; never opens/flashes a device."""
from pathlib import Path
import hashlib,json,shutil,zipfile
R=Path(__file__).resolve().parents[1];B=Path.home()/'.cache/ai-key-rev-a/build'
sha=lambda p:hashlib.sha256(p.read_bytes()).hexdigest()
checkpoint=json.loads((R/'reports/firmware-build-current.json').read_text())
for name,digest in checkpoint['sources'].items():
    assert sha(R/name)==digest,'Source changed since the validated build: '+name
for item in checkpoint['artifacts']:
    assert sha(Path(item['path']))==item['sha256']
elf_sha=sha(B/'aikey_rev_a.elf')
for name in ('usb-descriptor-check','ble-descriptor-check','wifi-elf-check'):
    report=json.loads((R/'reports'/(name+'.json')).read_text())
    assert report['elf_sha256']==elf_sha and report['status'].endswith('PASS')
args=json.loads((B/'flasher_args.json').read_text())
assert args['extra_esptool_args']['chip']=='esp32s3'
dest=R/'firmware/dist'/('aikey-rev-a-'+elf_sha[:12]);dest.mkdir(parents=True,exist_ok=True)
files={}
for offset,name in args['flash_files'].items():
    src=B/name;out=dest/name;out.parent.mkdir(parents=True,exist_ok=True);shutil.copy2(src,out)
    files[name]={'offset':offset,'bytes':out.stat().st_size,'sha256':sha(out)}
shutil.copy2(B/'aikey_rev_a.elf',dest/'aikey_rev_a.elf')
files['aikey_rev_a.elf']={'bytes':(dest/'aikey_rev_a.elf').stat().st_size,'sha256':elf_sha}
manifest={'status':'HASH_VERIFIED_DEVELOPMENT_BUILD_NO_PHYSICAL_FLASH_TEST','chip':'esp32s3','module':'ESP32-S3-WROOM-1U-N16R8',
          'sdk':'ESP-IDF 5.2.3, preserving existing user SDK modifications','files':files,'flash_settings':args['flash_settings'],
          'source_hashes':checkpoint['sources'],'evidence':checkpoint['evidence'],'physical_flash_or_validation':False}
(dest/'manifest.json').write_text(json.dumps(manifest,indent=2)+'\n')
(dest/'README.md').write_text('''# AIKEY REV A 开发固件构建包

本包来自已经完成编译、原生行为测试和 ELF 审计的 ESP32-S3 构建。尚未在样机烧录；不作为已通过实物验收或量产的版本。

- 模组：ESP32-S3-WROOM-1U-N16R8，16 MB Flash / 8 MB PSRAM。
- 包含 USB HID/UAC/设置、BLE HID/GATT、Wi-Fi TLS 语音、IMU、受扳机约束的收音及降低起始驱动电压的 LRA 控制。
- USB VID/PID 是开发用途；BLE 配对、UAC 枚举、射频、音频、充电、热及实际动作待样机测试。
- `manifest.json` 给出所有二进制校验值、真实编译源哈希和 Flash 参数。`aikey_rev_a.elf` 用于调试，其他三个 BIN 按下述偏移写入。

本次没有执行烧录。样机准备好后，在已配置的 ESP-IDF 5.2.3 Python 环境中，进入本目录，将端口替换为实际 ESP32-S3 端口：

```sh
python -m esptool --chip esp32s3 --port /dev/cu.ACTUAL_PORT --before default_reset --after hard_reset write_flash --flash_mode dio --flash_size 16MB --flash_freq 80m 0x0 bootloader/bootloader.bin 0x8000 partition_table/partition-table.bin 0x10000 aikey_rev_a.bin
```

这个命令写入引导程序、分区表和应用。首次配网与显式重新绑定参照上级工程 `host/README.md`；不包含任何用户 Wi-Fi 密码或 PSK。所有源码保留在工程的 `firmware/`，构建方式在工程 README 与 `tools/idf.sh` 中。
''')
archive=dest.with_suffix('.zip')
with zipfile.ZipFile(archive,'w',zipfile.ZIP_DEFLATED) as z:
    for file in sorted(dest.rglob('*')):
        if file.is_file():z.write(file,str(Path(dest.name)/file.relative_to(dest)))
with zipfile.ZipFile(archive) as z:
    assert z.testzip() is None
    for name,item in files.items():assert hashlib.sha256(z.read(dest.name+'/'+name)).hexdigest()==item['sha256']
report={'status':'PACKAGE_HASH_AND_ZIP_READBACK_PASS','directory':str(dest),'zip':str(archive),'zip_sha256':sha(archive),'elf_sha256':elf_sha,'physical_flash_executed':False}
(R/'reports/firmware-package.json').write_text(json.dumps(report,indent=2)+'\n');print(json.dumps(report),flush=True)
