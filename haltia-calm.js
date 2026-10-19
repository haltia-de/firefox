// A window that opens on the home page puts the cursor in the address bar,
// and an on-screen keyboard comes up over half the screen though nobody
// has touched a text field. Once per window, take the focus off it; a tap
// on the address bar brings the keyboard as usual. Loaded by autoconfig
// (haltia-firefox.cfg).
(function () {
  if (globalThis.__haltiaCalm) {
    return;
  }
  globalThis.__haltiaCalm = true;

  var Cc = Components.classes;
  var Ci = Components.interfaces;

  function browserWindows() {
    var wm = Cc["@mozilla.org/appshell/window-mediator;1"].getService(
      Ci.nsIWindowMediator
    );
    var found = [];
    var en = wm.getEnumerator("navigator:browser");
    while (en.hasMoreElements()) {
      var win = en.getNext();
      try {
        // Only a window that has finished starting has its address bar.
        if (!win.closed && win.gBrowserInit && win.gBrowserInit.delayedStartupFinished) {
          found.push(win);
        }
      } catch (e) {}
    }
    return found;
  }

  function calmStart() {
    var wins = browserWindows();
    for (var i = 0; i < wins.length; i++) {
      try {
        if (wins[i].__haltiaCalm) {
          continue;
        }
        wins[i].__haltiaCalm = true;
        var spec = wins[i].gBrowser.selectedBrowser.currentURI.spec;
        if (/^about:(home|newtab|blank)/.test(spec)) {
          wins[i].gURLBar.blur();
          wins[i].gBrowser.selectedBrowser.focus();
        }
      } catch (e) {}
    }
  }

  var timer = Cc["@mozilla.org/timer;1"].createInstance(Ci.nsITimer);
  var callback = { notify: function () { try { calmStart(); } catch (e) {} } };
  globalThis.__haltiaCalmTimer = [timer, callback];
  timer.initWithCallback(callback, 400, Ci.nsITimer.TYPE_REPEATING_SLACK);
})();
