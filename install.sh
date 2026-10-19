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
install -D -m 644 "$here/b8k-profile-prefs.py" "$root$share/b8k-profile-prefs.py"
for f in userChrome.css userChrome-shell.css userContent.css b8k-calm.js; do
	install -D -m 644 "$here/$f" "$root$share/$f"
done
# The shell's old copies, from before this repository.
rm -f "$root/usr/local/share/b8k/userChrome.css" "$root/usr/local/share/b8k/userContent.css" \
	"$root/usr/local/share/b8k/b8k-webapp.js"
# Firefox's own folder: our autoconfig and prefs. A package (ROOT a
# package's folder, no Firefox in it) installs them all the same.
install -d -m 755 "$ff/browser/defaults/preferences"
sed "s|@SHARE@|$share|g" "$here/b8k-firefox.cfg.in" >"$ff/b8k-firefox.cfg"
chmod 644 "$ff/b8k-firefox.cfg"
for f in zz-b8k-firefox.js b8k-ram.js b8k-lean.js; do
	# GRE defaults/pref loads before Firefox's own application prefs, which
	# override e.g. tab unloading and prelaunch. Application defaults also
	# select our autoconfig after mobile-config-firefox's GRE loader.
	install -m 644 "$here/$f" "$ff/browser/defaults/preferences/$f"
	rm -f "$ff/defaults/pref/$f"
done
# The shell's web-app windows are gone (chromeless windows could show a
# page under a trusted name): its autoconfig and loader go too.
rm -f "$ff/b8k-webapp.cfg" "$ff/defaults/pref/zz-b8k-webapp.js" \
	"$ff/browser/defaults/preferences/zz-b8k-webapp.js" "$root$share/b8k-webapp.js"
# uBlock Origin Lite instead of uBlock Origin, and the Russian language
# pack: Mozilla-signed files, checked against their sha256. The extension
# goes into the image: addons.mozilla.org answers 406 from some networks.
cache=${B8K_CACHE:-$here/.cache}
mkdir -p "$cache"
fetch() { # url sha256 target: the file, checked, or a warning
	name=${1##*/}
	[ -f "$cache/$name" ] || wget -q -O "$cache/$name" "$1" || rm -f "$cache/$name"
	if [ -f "$cache/$name" ] && echo "$2  $cache/$name" | sha256sum -c - >/dev/null; then
		install -D -m 644 "$cache/$name" "$root$3"
	else
		echo "b8k-firefox: no ${3##*/}" >&2
	fi
}
fetch "https://github.com/uBlockOrigin/uBOL-home/releases/download/2026.1012.1545/uBOLite_2026.1012.1545.firefox.signed.xpi" \
	0a55b67791c0987bae74ae4648cd2034e47fcc33ebd2a45e2ea0706b13af0e3d "$share/ubol.xpi"
fetch "https://releases.mozilla.org/pub/firefox/releases/151.0.3/linux-x86_64/xpi/ru.xpi" \
	61d3a59c7e98798f5bac288964764d1ff6b709ca860088a5d87a39ddc377bc85 "$share/langpack-ru.xpi"
install -m 755 "$here/b8k-firefox-configure" "$root$share/b8k-firefox-configure"
install -m 644 "$here/b8k-policies.py" "$root$share/b8k-policies.py"
# What depends on the Firefox installed (its policies, its version): now
# when there is one, else at the package's installation (post-install).
if [ -f "$ff/application.ini" ]; then
	ROOT=$root sh "$root$share/b8k-firefox-configure"
fi
