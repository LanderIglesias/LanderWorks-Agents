declare const app: any, p: Promise<void>, log: any, run: any;

function a() {
  try {
    run();
  // ruleid: catch-vacio
  } catch (e) {}
  try {
    run();
  // ruleid: catch-vacio
  } catch {}
  try {
    run();
  } catch (e) {
    // ok: catch-vacio
    log(e);
  }
}

// ruleid: promise-catch-vacio
p.catch(() => {});
// ruleid: promise-catch-vacio
p.catch((e) => {});
// ruleid: promise-catch-vacio
p.catch(e => {});
// ok: promise-catch-vacio
p.catch((e) => log(e));
// ok: promise-catch-vacio
p.catch((e) => { log(e); });

app.get("/a", (req: any, res: any) => {
  try {
    run();
  } catch (err: any) {
    // ruleid: express-stack-en-respuesta
    res.status(500).send(err.stack);
  }
});
app.get("/b", (req: any, res: any) => {
  try {
    run();
  } catch (err: any) {
    // ruleid: express-error-expuesto
    res.status(500).json({ error: err.message });
  }
});
app.get("/c", (req: any, res: any) => {
  try {
    run();
  } catch (err: any) {
    // ruleid: express-error-expuesto
    res.send(err.message);
  }
});
app.get("/d", (req: any, res: any) => {
  try {
    run();
  } catch (err: any) {
    // ruleid: express-error-expuesto
    res.send(err);
  }
});
app.use((err: any, req: any, res: any, next: any) => {
  // ruleid: express-error-expuesto
  res.status(500).json({ error: err.message });
});
app.get("/e", (req: any, res: any) => {
  try {
    run();
  } catch (err: any) {
    log(err);
    // ok: express-error-expuesto
    res.status(500).json({ error: "Error interno" });
  }
});
app.get("/f", (req: any, res: any) => {
  // ok: express-error-expuesto
  res.send(req.message);
});
