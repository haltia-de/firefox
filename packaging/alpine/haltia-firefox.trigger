#!/bin/sh
# apk runs this when a package changes /usr/lib/firefox (firefox or
# mobile-config-firefox). Rewrite policies and the language-pack pin.
/usr/share/haltia-firefox/haltia-firefox-configure
exit 0
