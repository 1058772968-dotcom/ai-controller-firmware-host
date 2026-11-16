#!/usr/bin/env python3
"""Verify that the current MCU ELF contains the actual Wi-Fi/TLS/configuration path."""
import hashlib,json
from pathlib import Path
from elftools.elf.elffile import ELFFile
r=Path(__file__).resolve().parents[1];path=Path.home()/'.cache/ai-key-rev-a/build/aikey_rev_a.elf'
required=['ak_wifi_audio_init','ak_wifi_audio_context','ak_wifi_audio_push','ak_audio_frame','ak_audio_ack','esp_wifi_connect','esp_tls_conn_new_sync','mbedtls_ssl_conf_psk','ak_settings_process','ak_settings_load','ak_ble_forget_bonds']
with path.open('rb') as stream:
    elf=ELFFile(stream);table=elf.get_section_by_name('.symtab')
    symbols={s.name:s for s in table.iter_symbols() if s.name in required}
    for name in required:assert name in symbols and symbols[name]['st_shndx']!='SHN_UNDEF' and symbols[name]['st_size']>0,name
config=(r/'firmware/sdkconfig').read_text()
for flag in ('CONFIG_ESP_TLS_PSK_VERIFICATION=y','CONFIG_MBEDTLS_KEY_EXCHANGE_PSK=y','CONFIG_ESP_WIFI_ENABLED=y'):assert flag in config,flag
result={'status':'WIFI_TLS_SETTINGS_LINKED_ELF_PASS','elf':str(path),'elf_sha256':hashlib.sha256(path.read_bytes()).hexdigest(),'linked_symbols':required,
 'sdkconfig_sha256':hashlib.sha256(config.encode()).hexdigest(),'scope':'Real Xtensa build/link and selected SDK capabilities; no radio connection, actual NVS write, microphone or physical pairing executed.'}
(r/'reports/wifi-elf-check.json').write_text(json.dumps(result,indent=2)+'\n');print(result['status'])
