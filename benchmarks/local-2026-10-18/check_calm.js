// Behavioural comparison of the shipped polling script and the benchmark-only
// event prototype. Mocks verify focus ownership and scheduling, not real OSK UI.
const fs = require('fs');
const vm = require('vm');
const cp = require('child_process');
const path = require('path');
const root = path.resolve(__dirname, '../..');
const original = fs.readFileSync(path.join(root, 'b8k-calm.js'), 'utf8');
const prototype = cp.execFileSync('python3', ['-c',
  "import ast, pathlib; t=ast.parse(pathlib.Path('" + __dirname + "/run_matrix.py').read_text()); print(next(ast.literal_eval(n.value) for n in t.body if isinstance(n,ast.Assign) and any(isinstance(x,ast.Name) and x.id=='CALM_EVENT' for x in n.targets)))"
], {encoding:'utf8'});
const results = [];
function check(name, source, event) {
  const wins = [], timers = [], queue = [], observers = {};
  function win(spec, ready=true) {
    const w = {closed:false, blur:0, focus:0, gBrowserInit:{delayedStartupFinished:ready},
      setTimeout(fn) {queue.push(fn);},
      gURLBar:{blur() {w.blur++;}},
      gBrowser:{selectedBrowser:{currentURI:{spec},focus() {w.focus++;}}}};
    wins.push(w); return w;
  }
  const enumerate = () => {
    let i=0;
    return {[Symbol.iterator]:function*(){yield* wins;},
      hasMoreElements(){return i<wins.length;},getNext(){return wins[i++];}};
  };
  const context={Components:{classes:{
    '@mozilla.org/appshell/window-mediator;1':{getService(){return {getEnumerator:enumerate};}},
    '@mozilla.org/timer;1':{createInstance(){return {initWithCallback(cb,ms,type){timers.push({cb,ms,type});}};}}
  },interfaces:{nsITimer:{TYPE_REPEATING_SLACK:1}}},Services:{
    wm:{getEnumerator:enumerate},obs:{addObserver(o,topic){observers[topic]=o;}}}};
  const home=win('about:home'), page=win('https://example.test/'), late=win('about:newtab',false);
  const run=()=>{
    if(event) for(const w of wins) if(w.gBrowserInit.delayedStartupFinished)
      observers['browser-delayed-startup-finished'].observe(w);
    else {}
    for(const t of timers)t.cb.notify();
    while(queue.length)queue.shift()();
  };
  vm.runInNewContext(source,context);
  run();run();
  if(home.blur!==1||page.blur!==0||late.blur!==0)throw Error(name+': initial focus');
  late.gBrowserInit.delayedStartupFinished=true;run();
  const second=win('about:blank');run();run();
  if(late.blur!==1||second.blur!==1)throw Error(name+': new/delayed window');
  for(let i=0;i<100;i++)run();
  if(home.blur!==1||second.blur!==1)throw Error(name+': repeated user focus interception');
  results.push({name,status:'pass',recurringTimers:timers.length,
    intervalMs:timers[0]?.ms||null,focusCounts:wins.map(w=>w.blur),
    note:'Mocks; no touch keyboard or real Firefox startup timing verified'});
}
check('shipped-polling',original,false);
check('event-prototype',prototype,true);
fs.writeFileSync(path.join(__dirname,'calm-contracts.json'),JSON.stringify(results,null,2)+'\n');
console.log(JSON.stringify(results));
