#!/usr/bin/env python3
"""Read uBOL's actual background state, managed storage and granted origins."""
import json
from pathlib import Path
import shutil
import time
import run_matrix as m

out=m.OUT/'extension-state';out.mkdir(exist_ok=True)
for mode in ['basic','optimal','complete']:
    profile=Path('/home/bench/lab')/('extension-state-'+mode)
    shutil.rmtree(profile,ignore_errors=True);profile.mkdir()
    r={'mode_requested':mode,'started':time.time()};d=None
    try:
        prefs=m.configure('ubol_'+mode,profile)
        d=m.Driver(profile,prefs,out/(mode+'.log'))
        time.sleep(3)
        r['startup_tabs']=d.script('''return [...gBrowser.tabs].map(t=>({
          uri:t.linkedBrowser.currentURI.spec,selected:t===gBrowser.selectedTab}));''',True)
        url=d.script('''return WebExtensionPolicy.getByID('uBOLiteRedux@raymondhill.net').getURL('popup.html');''',True)
        d.navigate(url)
        r['extension_state']=d.script('''let done=arguments[0];Promise.all([
          browser.storage.managed.get(null),browser.permissions.getAll(),
          browser.runtime.sendMessage({what:'getFilteringModeDetails'})
        ]).then(([managed,permissions,modes])=>done({managed,permissions,modes}),
          e=>done({error:String(e)}));''',async_=True)
        r['status']='ok' if 'error' not in r['extension_state'] else 'error'
    except Exception as e:
        r.update(status='error',error=str(e))
    finally:
        if d:d.close()
        shutil.rmtree(profile,ignore_errors=True)
        r['ended']=time.time();(out/(mode+'.json')).write_text(json.dumps(r,indent=2)+'\n')
    print(json.dumps(r),flush=True)
