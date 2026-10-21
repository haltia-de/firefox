// A window that opens on the home page puts the cursor in the address bar,
// and an on-screen keyboard comes up over half the screen though nobody
// has touched a text field. Once per window, after delayed startup, take
// the focus off it; a tap on the address bar brings the keyboard as usual.
// Loaded by autoconfig (haltia-firefox.cfg).
(function () {
  if (globalThis.__haltiaCalm) {
    return;
  }
  globalThis.__haltiaCalm = true;

  var Cc = Components.classes;
  var Ci = Components.interfaces;

  function calm(win) {
    try {
      if (!win || win.closed || win.__haltiaCalm) {
        return;
      }
      // domwindowopened arrives before the address bar exists.
      if (!win.gBrowserInit || !win.gBrowserInit.delayedStartupFinished) {
        return;
      }
      win.__haltiaCalm = true;
      // Focus is applied around the end of startup. Blur on the next turn,
      // once, so a later tap on the address bar still raises the keyboard.
      win.setTimeout(function () {
        try {
          if (win.closed || !win.gBrowser) {
            return;
          }
          var spec = win.gBrowser.selectedBrowser.currentURI.spec;
          if (/^about:(home|newtab|blank)/.test(spec)) {
            win.gURLBar.blur();
            win.gBrowser.selectedBrowser.focus();
          }
        } catch (e) {}
      }, 0);
    } catch (e) {}
  }

  var observer = {
    observe: function (subject, topic) {
      if (topic == "browser-delayed-startup-finished" || topic == "domwindowopened") {
        calm(subject);
      }
    },
  };
  var obs = Cc["@mozilla.org/observer-service;1"].getService(Ci.nsIObserverService);
  obs.addObserver(observer, "browser-delayed-startup-finished", false);
  obs.addObserver(observer, "domwindowopened", false);
  // The autoconfig sandbox must keep this; the observer service holds it too.
  globalThis.__haltiaCalmObserver = observer;

  var wm = Cc["@mozilla.org/appshell/window-mediator;1"].getService(
    Ci.nsIWindowMediator
  );
  var en = wm.getEnumerator("navigator:browser");
  while (en.hasMoreElements()) {
    calm(en.getNext());
  }
})();
