#!/bin/sh
# SPDX-License-Identifier: GPL-2.0
# Install b8k-firefox: sh install.sh [ROOT] [PREFIX]
# ROOT empty or / for this system; PREFIX /usr/local unless given. Firefox
# itself, and mobile-config-firefox for its policies, are installed already
# (in ROOT/usr/lib/firefox). B8K_CACHE keeps the downloaded extension and
# language pack between runs.
#
# Puts the prefs (b8k-lean.js, b8k-ram.js, zz-b8k-firefox.js) into Firefox's
# defaults, its autoconfig file (b8k-firefox.cfg: mobile-config-firefox's
# autoconfig, then b8k-calm.js, which keeps the keyboard down on a new
# window), the stylesheets and b8k-firefox-profile into PREFIX, and writes
# /etc/firefox/policies/policies.json: mobile-config-firefox's, with
# uBlock Origin Lite in complete mode and the Russian language pack, both
# Mozilla-signed files checked against their sha256.
set -eu
root=${1:-}
root=${root%/}
prefix=${2:-/usr/local}
here=$(cd "$(dirname "$0")" && pwd)
share=$prefix/share/b8k-firefox
ff=$root/usr/lib/firefox
install -D -m 755 "$here/b8k-firefox-profile" "$root$prefix/bin/b8k-firefox-profile"
for f in userChrome.css userChrome-shell.css userContent.css b8k-calm.js; do
	install -D -m 644 "$here/$f" "$root$share/$f"
done
# The shell's old copies, from before this repository.
rm -f "$root/usr/local/share/b8k/userChrome.css" "$root/usr/local/share/b8k/userContent.css" \
	"$root/usr/local/share/b8k/b8k-webapp.js"
if [ ! -d "$ff/defaults/pref" ]; then
	echo "b8k-firefox: no Firefox in $ff: only the profile files installed" >&2
	exit 0
fi
sed "s|@SHARE@|$share|g" "$here/b8k-firefox.cfg.in" >"$ff/b8k-firefox.cfg"
chmod 644 "$ff/b8k-firefox.cfg"
for f in zz-b8k-firefox.js b8k-ram.js b8k-lean.js; do
	install -m 644 "$here/$f" "$ff/defaults/pref/$f"
done
# The shell's web-app windows are gone (chromeless windows could show a
# page under a trusted name): its autoconfig and loader go too.
rm -f "$ff/b8k-webapp.cfg" "$ff/defaults/pref/zz-b8k-webapp.js" "$root$share/b8k-webapp.js"
# uBlock Origin Lite in complete mode instead of uBlock Origin. The
# extension goes into the image: addons.mozilla.org answers 406 from some
# networks, and Firefox then never installed it. The release on GitHub is
# the same file, signed by Mozilla.
cache=${B8K_CACHE:-$here/.cache}
mkdir -p "$cache"
fetch() { # url sha256 target: the file, checked, or nothing
	name=${1##*/}
	[ -f "$cache/$name" ] || wget -q -O "$cache/$name" "$1" || rm -f "$cache/$name"
	if [ -f "$cache/$name" ] && echo "$2  $cache/$name" | sha256sum -c - >/dev/null; then
		install -D -m 644 "$cache/$name" "$root$3"
		return 0
	fi
	return 1
}
ubol_ver=2026.1012.1545
ubol=$share/ubol.xpi
fetch "https://github.com/uBlockOrigin/uBOL-home/releases/download/$ubol_ver/uBOLite_$ubol_ver.firefox.signed.xpi" \
	0a55b67791c0987bae74ae4648cd2034e47fcc33ebd2a45e2ea0706b13af0e3d "$ubol" || {
	echo "b8k-firefox: no uBlock Origin Lite $ubol_ver, Firefox will download it" >&2
	ubol=
}
# Russian menus: Alpine packages no Firefox language packs, so Mozilla's
# signed one, which must match Firefox's version.
ru_for=151.0.3
ru=$share/langpack-ru.xpi
ff_ver=$(sed -n 's/^Version=//p' "$ff/application.ini" | head -1)
if [ "$ff_ver" != "$ru_for" ] || ! fetch "https://releases.mozilla.org/pub/firefox/releases/$ru_for/linux-x86_64/xpi/ru.xpi" \
	61d3a59c7e98798f5bac288964764d1ff6b709ca860088a5d87a39ddc377bc85 "$ru"; then
	echo "b8k-firefox: no Russian language pack for Firefox $ff_ver (pinned $ru_for)" >&2
	ru=
fi
if [ -f "$ff/distribution/policies.json" ]; then
	mkdir -p "$root/etc/firefox/policies"
	python3 "$here/b8k-policies.py" "$ff/distribution/policies.json" \
		"$root/etc/firefox/policies/policies.json" "$ubol" "$ru"
fi
# The loader for b8k-webapp.js the shell once appended to
# mobile-config-firefox's autoconfig (b8k-firefox.cfg loads b8k-calm.js).
mc=$ff/mobile-config-autoconfig.js
if [ -f "$mc" ] && grep -q 'b8k-webapp.js' "$mc"; then
	python3 - "$mc" <<'EOT'
import re, sys
p = sys.argv[1]
s = open(p).read()
s = re.sub(r'try \{\n  Components\.classes\["@mozilla\.org/moz/jssubscript-loader;1"\]\n'
           r'    \.getService\(Components\.interfaces\.mozIJSSubScriptLoader\)\n'
           r'    \.loadSubScript\("file://[^"]*b8k-webapp\.js"\);\n\} catch \(e\) \{\}\n', '', s)
open(p, "w").write(s)
EOT
fi
