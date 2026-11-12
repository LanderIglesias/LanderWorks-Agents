declare const log: any;

// ruleid: console-log
console.log("x");
// ruleid: console-log
console.debug("x");
// ok: console-log
console.error("x");
// ok: console-log
log.info("x");

function a() {
  // ruleid: debugger-olvidado
  debugger;
  // ok: debugger-olvidado
  const debuggerName = "debugger;";
}
