# SPDX-License-Identifier: GPL-2.0
"""Regression checks with temporary homes and offline staged installations."""
import json
import os
from pathlib import Path
import subprocess
import sys
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
        return subprocess.run(['sh', str(script or ROOT / 'haltia-firefox-profile'), *args],
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

    def test_malformed_block_is_left_alone_and_other_profiles_continue(self):
        bad = self.home / '.config/mozilla/firefox/bad.profile'
        good = self.home / '.mozilla/firefox/good.profile'
        bad.mkdir(parents=True)
        good.mkdir(parents=True)
        begin = '// BEGIN b8k-firefox managed prefs\n'
        end = '// END b8k-firefox managed prefs\n'
        original = begin + 'user_pref("a", 1);\n' + end + begin + 'user_pref("b", 2);\n' + end
        (bad / 'user.js').write_text(original)
        (good / 'user.js').write_text('user_pref("unrelated", "keep");\n')
        result = self.prepare()
        self.assertEqual((bad / 'user.js').read_text(), original)
        self.assertIn('malformed b8k-firefox block', result.stderr)
        good_text = (good / 'user.js').read_text()
        self.assertEqual(good_text.count(begin), 1)
        self.assertIn('user_pref("unrelated", "keep");\n', good_text)
        self.assertEqual(list(bad.glob('.haltia-*')), [])

    def test_running_firefox_lock_refuses_prefs_js_edit(self):
        self.prepare('--fps', '30')
        prefs = self.profile / 'prefs.js'
        original = 'user_pref("layout.frame_rate", 30);\nuser_pref("unrelated", true);\n'
        prefs.write_text(original)
        # Firefox's Unix lock is a symlink to a path that does not exist.
        lock = self.profile / 'lock'
        lock.symlink_to('127.0.0.1:+1')
        self.assertFalse(lock.exists())
        result = self.prepare('--reset-optimizations')
        self.assertIn('not changing prefs.js', result.stderr)
        self.assertEqual(prefs.read_text(), original)
        self.assertNotIn('layout.frame_rate', (self.profile / 'user.js').read_text())
        self.assertEqual(list(self.profile.glob('.haltia-*')), [])

    def test_stale_parentlock_does_not_block_prefs_reset(self):
        self.prepare('--fps', '30')
        prefs = self.profile / 'prefs.js'
        prefs.write_text('user_pref("layout.frame_rate", 30);\n')
        (self.profile / '.parentlock').write_text('')
        self.prepare('--reset-optimizations')
        self.assertEqual(prefs.read_text(), '')

    def test_policies_replace_atomically_and_keep_mode(self):
        src = self.home / 'policies-src.json'
        dst = self.home / 'policies.json'
        src.write_text(json.dumps({'policies': {'DisableTelemetry': True}}))
        dst.write_text('not json\n')
        dst.chmod(0o640)
        subprocess.run([sys.executable, str(ROOT / 'haltia-policies.py'),
                        str(src), str(dst)], check=True)
        text = dst.read_text()
        self.assertTrue(text.endswith('\n'))
        self.assertTrue(json.loads(text)['policies']['DisableTelemetry'])
        self.assertEqual(dst.stat().st_mode & 0o777, 0o640)
        self.assertEqual(list(self.home.glob('.haltia-*')), [])

    def test_configure_strips_old_loader_without_leftover_temp_files(self):
        stage = self.home / 'configured'
        ff = stage / 'usr/lib/firefox'
        ff.mkdir(parents=True)
        block = (
            'try {\n'
            '  Components.classes["@mozilla.org/moz/jssubscript-loader;1"]\n'
            '    .getService(Components.interfaces.mozIJSSubScriptLoader)\n'
            '    .loadSubScript("file:///usr/share/b8k/b8k-webapp.js");\n'
            '} catch (e) {}\n'
        )
        mc = ff / 'mobile-config-autoconfig.js'
        mc.write_text('before\n' + block + 'after\n')
        mc.chmod(0o644)
        env = dict(self.env, ROOT=str(stage))
        subprocess.run(['sh', str(ROOT / 'haltia-firefox-configure')],
                       env=env, check=True, capture_output=True, text=True)
        text = mc.read_text()
        self.assertNotIn('b8k-webapp.js', text)
        self.assertEqual(text, 'before\nafter\n')
        self.assertEqual(mc.stat().st_mode & 0o777, 0o644)
        self.assertEqual(list(ff.glob('.haltia-*')), [])

    def test_apkbuild_triggers_configure_on_firefox_directory(self):
        apkbuild = (ROOT / 'packaging/alpine/APKBUILD').read_text()
        self.assertIn('triggers="$pkgname.trigger=/usr/lib/firefox"', apkbuild)
        trigger = (ROOT / 'packaging/alpine/haltia-firefox.trigger').read_text()
        self.assertIn('/usr/share/haltia-firefox/haltia-firefox-configure', trigger)
        calm = (ROOT / 'haltia-calm.js').read_text()
        self.assertNotIn('nsITimer', calm)
        self.assertIn('browser-delayed-startup-finished', calm)
        self.assertIn('domwindowopened', calm)

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
                        HALTIA_CACHE=str(self.home / 'cache'))
        for prefix in ['/usr', '/usr/local']:
            with self.subTest(prefix=prefix):
                staged = self.home / ('stage' + prefix.replace('/', '-'))
                ff = staged / 'usr/lib/firefox'
                (ff / 'distribution').mkdir(parents=True)
                (ff / 'application.ini').write_text('[App]\nVersion=151.0.3\n')
                (ff / 'distribution/policies.json').write_text(json.dumps({
                    'policies': {'DisableTelemetry': True}}))
                (ff / 'defaults/pref').mkdir(parents=True)
                for name in ['haltia-ram.js', 'haltia-lean.js', 'zz-haltia-firefox.js']:
                    (ff / 'defaults/pref' / name).write_text('// Old package location\n')
                share = staged / prefix.lstrip('/') / 'share/haltia-firefox'
                share.mkdir(parents=True)
                (share / 'ubol.xpi').write_text('path-selection fixture')
                subprocess.run(['sh', str(ROOT / 'install.sh'), str(staged), prefix],
                               env=self.env, check=True, capture_output=True)
                for name in ['haltia-ram.js', 'haltia-lean.js', 'zz-haltia-firefox.js']:
                    self.assertEqual((ff / 'browser/defaults/preferences' / name).read_bytes(),
                                     (ROOT / name).read_bytes())
                    self.assertFalse((ff / 'defaults/pref' / name).exists())
                policies = json.loads((staged / 'etc/firefox/policies/policies.json').read_text())['policies']
                self.assertTrue(policies['DisableTelemetry'])
                self.assertEqual(policies['ExtensionSettings']['uBOLiteRedux@raymondhill.net']['install_url'],
                                 'file://' + prefix + '/share/haltia-firefox/ubol.xpi')
                self.assertNotIn('langpack-ru@firefox.mozilla.org', policies['ExtensionSettings'])
                self.prepare('--fps', '30', script=staged / prefix.lstrip('/') / 'bin/haltia-firefox-profile')
                self.assertIn('"layout.frame_rate", 30', (self.profile / 'user.js').read_text())


if __name__ == '__main__':
    unittest.main()
