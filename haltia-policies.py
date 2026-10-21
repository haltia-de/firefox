#!/usr/bin/env python3
"""Write Firefox's policies for the tablet: mobile-config-firefox's, changed.

    haltia-policies.py SRC DST [XPI [LANGPACK]]

SRC is the policies.json of mobile-config-firefox
(/usr/lib/firefox/distribution/policies.json), DST is
/etc/firefox/policies/policies.json, which Firefox reads in its place and
which a package upgrade leaves alone.

The main change: uBlock Origin Lite instead of uBlock Origin. uBlock Origin
compiles its filter lists in its own process now and then (after a list or
Firefox update, or when it was stopped before saving them): 270-340 MB on
this 1 GB tablet, which once filled the swap and froze the session.
uBlock Origin Lite ships its rules precompiled for the browser to apply,
and its process stays near 37 MB. Its filtering mode is set to complete
(cosmetic filtering included), its default lists are kept on and RU
AdList (ruleset rus-0) is added to them, through its managed settings.

XPI is the path of a signed uBlock Origin Lite on the tablet. Firefox
installs it from there: addons.mozilla.org answers 406 from some networks,
and then the extension never arrived. Without XPI (or with an empty one),
Firefox downloads it.

Firefox asks for Russian menus, then English. Alpine packages no language
packs, so LANGPACK is the path of Mozilla's signed Russian one on the
tablet; without it the menus stay English.
"""
import json
import os
import sys
import tempfile

UBO = "uBlock0@raymondhill.net"
UBOL = "uBOLiteRedux@raymondhill.net"


def atomic_write(path, text):
    """Replace path with text. A crash keeps the previous file."""
    path = os.fspath(path)
    directory = os.path.dirname(path) or "."
    fd, tmp = tempfile.mkstemp(prefix=".haltia-", dir=directory)
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as fh:
            fh.write(text)
            fh.flush()
            os.fsync(fh.fileno())
        mode = 0o644
        if os.path.lexists(path):
            mode = os.lstat(path).st_mode & 0o777
        os.chmod(tmp, mode)
        os.replace(tmp, path)
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


def main(argv):
    src, dst = argv[1], argv[2]
    xpi = argv[3] if len(argv) > 3 and argv[3] else None
    langpack = argv[4] if len(argv) > 4 and argv[4] else None
    with open(src) as fh:
        data = json.load(fh)
    policies = data["policies"]
    settings = policies.setdefault("ExtensionSettings", {})
    settings[UBO] = {"installation_mode": "blocked"}
    settings[UBOL] = {
        "installation_mode": "normal_installed",
        "install_url": "file://" + xpi if xpi else
        "https://addons.mozilla.org/firefox/downloads/latest/ublock-origin-lite/latest.xpi",
        "default_area": "menupanel",
    }
    if langpack:
        settings["langpack-ru@firefox.mozilla.org"] = {
            "installation_mode": "force_installed",
            "install_url": "file://" + langpack,
        }
    policies["RequestedLocales"] = ["ru", "en-US"]
    # No bookmarks toolbar: a third row of small links took height from the
    # page and offered «Импорт закладок» to someone who has none.
    policies["DisplayBookmarksToolbar"] = "never"
    policies.setdefault("3rdparty", {}).setdefault("Extensions", {})[UBOL] = {
        "defaultFiltering": "complete",
        # uBOL's default lists always on ("+default": they were found off on
        # the tablet, a state uBOL keeps across restarts), and RU AdList on
        # top of them for Russian sites' ads.
        "rulesets": ["+default", "+rus-0"],
    }
    text = json.dumps(data, indent=4, ensure_ascii=False) + "\n"
    atomic_write(dst, text)


if __name__ == "__main__":
    main(sys.argv)
