import cors from "cors";
import DOMPurify from "dompurify";

declare const html: string, ld: object, el: any, jwt: any, token: string, key: string, x: string, app: any;

// ruleid: eval-js
eval(x);
// ruleid: eval-js
new Function(x);
// ok: eval-js
eval("1+1");
// ok: eval-js
new Function("return 1");

// ruleid: cors-express-abierto
app.use(cors());
// ruleid: cors-express-abierto
app.use(cors({ origin: "*" }));
// ruleid: cors-express-abierto
app.use(cors({ origin: true }));
// ok: cors-express-abierto
app.use(cors({ origin: "https://a.com" }));
// ruleid: cors-express-credenciales
app.use(cors({ origin: "*", credentials: true }));
// ok: cors-express-credenciales
app.use(cors({ origin: "https://a.com", credentials: true }));

// ruleid: react-dangerously-set-inner-html
const a = <div dangerouslySetInnerHTML={{ __html: html }} />;
// ok: react-dangerously-set-inner-html
const b = <div dangerouslySetInnerHTML={{ __html: "<b>hi</b>" }} />;
// ok: react-dangerously-set-inner-html
const c = <div dangerouslySetInnerHTML={{ __html: DOMPurify.sanitize(html) }} />;
// ok: react-dangerously-set-inner-html
const d = <script dangerouslySetInnerHTML={{ __html: JSON.stringify(ld) }} />;

// ruleid: inner-html-asignado
el.innerHTML = x;
// ok: inner-html-asignado
el.innerHTML = "<b>x</b>";
// ok: inner-html-asignado
el.innerHTML = DOMPurify.sanitize(x);

// ruleid: jwt-algoritmo-none-js
jwt.verify(token, key, { algorithms: ["none"] });
// ok: jwt-algoritmo-none-js
jwt.verify(token, key, { algorithms: ["HS256"] });
