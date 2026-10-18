# SPDX-License-Identifier: GPL-2.0
"""Regression checks with temporary homes and offline staged installations."""
import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]


class ProfileInstallTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.home = Path(self.tmp.name)
        self.env = dict(os.environ, HOME=str(self.home))
        self.profile = self.home / '.config/mozilla/firefox/b8k.default'

    def prepare(self, *args, script=None, check=True):
        return subprocess.run(['sh', str(script or ROOT / 'b8k-firefox-profile'), *args],
                              env=self.env, text=True, capture_output=True, check=check)

    def test_migration_preserves_manual_settings_and_is_idempotent(self):
        self.profile.mkdir(parents=True)
        js = self.profile / 'user.js'
        js.write_text('// My settings\nuser_pref("dom.ipc.processCount", 2);\n'
                      'user_pref("dom.ipc.processCount", 1);\n'
                      'user_pref("browser.startup.page", 0);\n'
                      'user_pref("unrelated", "keep");\n')
        self.prepare('--shell')
        first = js.read_bytes()
        self.assertIn(b'"dom.ipc.processCount", 2', first)
        self.assertNotIn(b'"dom.ipc.processCount", 1', first)
        self.assertIn(b'"browser.startup.page", 0', first)
        self.assertIn(b'"unrelated", "keep"', first)
        self.prepare('--shell')
        self.assertEqual(first, js.read_bytes())
        self.assertIn('padding-inline-end: 110px',
                      (self.profile / 'chrome/userChrome.css').read_text())
        self.prepare()
        self.assertNotIn('padding-inline-end: 110px',
                         (self.profile / 'chrome/userChrome.css').read_text())

    def test_options_persist_update_and_reset_persisted_firefox_values(self):
        self.prepare('--image-cache-factor', '8', '--fps', '30', '--shell',
                     '--unload-after', '30', '--unload-threshold-percent', '15')
        js = self.profile / 'user.js'
        first = js.read_bytes()
        self.assertIn(b'"browser.tabs.min_inactive_duration_before_unload", 30000', first)
        self.prepare()
        self.assertEqual(first, js.read_bytes())
        self.prepare('--image-cache-factor', '16')
        self.assertIn('"image.mem.surfacecache.size_factor", 16', js.read_text())
        self.assertNotIn('"image.mem.surfacecache.size_factor", 8', js.read_text())
        prefs = self.profile / 'prefs.js'
        prefs.write_text('// Firefox preferences\nuser_pref("layout.frame_rate", 30);\n'
                         'user_pref("image.mem.surfacecache.size_factor", 16);\n'
                         'user_pref("browser.tabs.min_inactive_duration_before_unload", 30000);\n'
                         'user_pref("browser.low_commit_space_threshold_percent", 15);\n'
                         'user_pref("unrelated", true);\n')
        self.prepare('--reset-optimizations')
        self.assertNotIn('layout.frame_rate', js.read_text())
        self.assertNotIn('surfacecache', js.read_text())
        self.assertEqual(prefs.read_text(), '// Firefox preferences\nuser_pref("unrelated", true);\n')
        self.prepare('--reset-optimizations')
        self.assertIn('"unrelated", true', prefs.read_text())

    def test_invalid_arguments_do_not_create_profiles(self):
        for args in [('--fps', '0'), ('--image-cache-factor', '64'),
                     ('--unload-after', '-1'), ('--unload-threshold-percent', '65536'),
                     ('--unknown',)]:
            with self.subTest(args=args):
                self.assertNotEqual(self.prepare(*args, check=False).returncode, 0)
                self.assertFalse(self.profile.exists())

    def test_help_does_not_create_profiles(self):
        result = self.prepare('--help')
        self.assertIn('--image-cache-factor', result.stdout)
        self.assertFalse(self.profile.exists())

    def test_manual_overrides_follow_managed_block(self):
        self.prepare('--fps', '30')
        js = self.profile / 'user.js'
        with js.open('a') as stream:
            stream.write('user_pref("layout.frame_rate", 45);\n')
        self.prepare()
        self.assertTrue(js.read_text().endswith('user_pref("layout.frame_rate", 45);\n'))

    def test_staged_installer_uses_installed_assets_for_both_prefixes(self):
        # No network and no fake signature verification: existing placeholder
        # assets exercise path selection only; fetch warns and retains them.
        stub = self.home / 'bin'
        stub.mkdir()
        (stub / 'wget').write_text('#!/bin/sh\nexit 1\n')
        (stub / 'wget').chmod(0o755)
        self.env.update(PATH=str(stub) + ':' + os.environ['PATH'],
                        B8K_CACHE=str(self.home / 'cache'))
        for prefix in ['/usr', '/usr/local']:
            with self.subTest(prefix=prefix):
                staged = self.home / ('stage' + prefix.replace('/', '-'))
                ff = staged / 'usr/lib/firefox'
                (ff / 'distribution').mkdir(parents=True)
                (ff / 'application.ini').write_text('[App]\nVersion=151.0.3\n')
                (ff / 'distribution/policies.json').write_text(json.dumps({
                    'policies': {'DisableTelemetry': True}}))
                share = staged / prefix.lstrip('/') / 'share/b8k-firefox'
                share.mkdir(parents=True)
                (share / 'ubol.xpi').write_text('path-selection fixture')
                subprocess.run(['sh', str(ROOT / 'install.sh'), str(staged), prefix],
                               env=self.env, check=True, capture_output=True)
                policies = json.loads((staged / 'etc/firefox/policies/policies.json').read_text())['policies']
                self.assertTrue(policies['DisableTelemetry'])
                self.assertEqual(policies['ExtensionSettings']['uBOLiteRedux@raymondhill.net']['install_url'],
                                 'file://' + prefix + '/share/b8k-firefox/ubol.xpi')
                self.assertNotIn('langpack-ru@firefox.mozilla.org', policies['ExtensionSettings'])
                self.prepare('--fps', '30', script=staged / prefix.lstrip('/') / 'bin/b8k-firefox-profile')
                self.assertIn('"layout.frame_rate", 30', (self.profile / 'user.js').read_text())


if __name__ == '__main__':
    unittest.main()
