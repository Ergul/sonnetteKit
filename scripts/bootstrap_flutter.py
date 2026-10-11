#!/usr/bin/env python3
"""Generate platform runners without replacing the maintained demo or package."""
import argparse
from pathlib import Path
import shutil
import subprocess
import tempfile

p = argparse.ArgumentParser()
p.add_argument('--platforms', default='web,android,windows,macos')
a = p.parse_args()
root = Path(__file__).resolve().parents[1]
app = root / 'apps/flutter_client'
with tempfile.TemporaryDirectory(prefix='sonnette-flutter-') as tmp:
    generated = Path(tmp) / 'demo'
    subprocess.run(['flutter', 'create', '--project-name', 'sonnette_demo', '--org', 'ch.cdsengineering',
                    '--platforms', a.platforms, str(generated)], check=True)
    for name in a.platforms.split(','):
        source, target = generated / name, app / name
        if source.exists() and not target.exists():
            shutil.copytree(source, target)
    # .metadata helps Flutter tooling; never replace the app's pubspec or lib/.
    if not (app / '.metadata').exists():
        shutil.copy2(generated / '.metadata', app / '.metadata')
manifest = app / 'android/app/src/main/AndroidManifest.xml'
if manifest.exists():
    s = manifest.read_text()
    permissions = ['INTERNET', 'CAMERA', 'RECORD_AUDIO', 'ACCESS_NETWORK_STATE',
                   'CHANGE_NETWORK_STATE', 'MODIFY_AUDIO_SETTINGS']
    additions = ''.join(f'    <uses-permission android:name="android.permission.{v}"/>\n'
                        for v in permissions if f'android.permission.{v}' not in s)
    s = s.replace('    <application', additions + '    <application', 1)
    manifest.write_text(s)
plist = app / 'macos/Runner/Info.plist'
if plist.exists():
    s = plist.read_text()
    if 'NSCameraUsageDescription' not in s:
        s = s.replace('</dict>', '<key>NSCameraUsageDescription</key><string>Video calls</string>\n'
                      '<key>NSMicrophoneUsageDescription</key><string>Audio calls</string>\n</dict>')
        plist.write_text(s)
for name in ['DebugProfile.entitlements', 'Release.entitlements']:
    f = app / 'macos/Runner' / name
    if f.exists():
        s = f.read_text()
        for key in ['com.apple.security.device.camera', 'com.apple.security.device.audio-input',
                    'com.apple.security.network.client']:
            if key not in s:
                s = s.replace('</dict>', f'<key>{key}</key><true/>\n</dict>')
        f.write_text(s)
subprocess.run(['flutter', 'pub', 'get'], cwd=app, check=True)
print('Demo ready. Native production permissions, signing and release builds still need platform testing.')
