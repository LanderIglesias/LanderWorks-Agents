from __future__ import annotations


def widget_js() -> str:
    # Plain JS widget. Token is read from script querystring: ?token=...
    return r"""
(function () {
  // ---- config ----
  function getScriptToken() {
    try {
      var scripts = document.getElementsByTagName("script");
      var me = scripts[scripts.length - 1];
      var src = me && me.src ? me.src : "";
      var u = new URL(src);
      return u.searchParams.get("token") || "";
    } catch (e) {
      return "";
    }
  }

  var TOKEN = getScriptToken();
  if (!TOKEN) {
    console.warn("[ScaffoldWidget] Missing token in widget.js?token=...");
  }

  var API_BASE = (function() {
    try {
      var scripts = document.getElementsByTagName("script");
      var me = scripts[scripts.length - 1];
      var src = me && me.src ? me.src : "";
      var u = new URL(src);
      return u.origin;
    } catch (e) {
      return "";
    }
  })();

  var SID_KEY = "scaffold_widget_session_id_" + (TOKEN || "no_token");
  // Controla si el saludo inicial ya se pidió en esta página
  // (evita pedirlo de nuevo si el usuario cierra y vuelve a abrir el widget)
  var _greeted = false;

  function uuid() {
    return "xxxxxxxx-xxxx-4xxx-yxxx-xxxxxxxxxxxx".replace(/[xy]/g, function (c) {
      var r = (Math.random() * 16) | 0;
      var v = c === "x" ? r : (r & 0x3) | 0x8;
      return v.toString(16);
    });
  }

  function getSessionId() {
    var sid = localStorage.getItem(SID_KEY);
    if (!sid) {
      sid = uuid();
      localStorage.setItem(SID_KEY, sid);
    }
    return sid;
  }

  function el(tag, attrs) {
    var n = document.createElement(tag);
    if (attrs) {
      Object.keys(attrs).forEach(function (k) {
        if (k === "style") Object.assign(n.style, attrs[k]);
        else if (k === "text") n.textContent = attrs[k];
        else n.setAttribute(k, attrs[k]);
      });
    }
    return n;
  }

  // ---- UI ----
  var btn = el("button", { "aria-label": "Open chat" });
  btn.textContent = "Chat";
  Object.assign(btn.style, {
    position: "fixed",
    right: "20px",
    bottom: "20px",
    zIndex: 2147483647,
    border: "0",
    borderRadius: "999px",
    padding: "12px 14px",
    cursor: "pointer",
    fontFamily: "system-ui, -apple-system, Segoe UI, Roboto, Arial, sans-serif",
    fontSize: "14px",
    background: "#111",
    color: "#fff",
    boxShadow: "0 10px 30px rgba(0,0,0,.2)"
  });

  var panel = el("div");
  Object.assign(panel.style, {
    position: "fixed",
    right: "20px",
    bottom: "70px",
    width: "360px",
    height: "460px",
    zIndex: 2147483647,
    borderRadius: "14px",
    background: "#fff",
    boxShadow: "0 14px 50px rgba(0,0,0,.25)",
    overflow: "hidden",
    display: "none"
  });

  var header = el("div");
  Object.assign(header.style, {
    padding: "10px 12px",
    background: "#111",
    color: "#fff",
    display: "flex",
    alignItems: "center",
    justifyContent: "space-between",
    fontFamily: "system-ui, -apple-system, Segoe UI, Roboto, Arial, sans-serif",
    fontSize: "13px"
  });
  header.appendChild(el("div", { text: "Scaffold Agent" }));

  var close = el("button");
  close.textContent = "×";
  Object.assign(close.style, {
    border: "0",
    background: "transparent",
    color: "#fff",
    fontSize: "22px",
    cursor: "pointer",
    lineHeight: "1"
  });
  header.appendChild(close);

  var chat = el("div");
  Object.assign(chat.style, {
    padding: "12px",
    height: "370px",
    overflow: "auto",
    display: "flex",
    flexDirection: "column",
    gap: "10px",
    background: "#fafafa"
  });

  function bubble(text, who) {
    var row = el("div");
    Object.assign(row.style, { display: "flex", justifyContent: who === "user" ? "flex-end" : "flex-start" });
    var b = el("div");
    b.textContent = text;
    Object.assign(b.style, {
      maxWidth: "78%",
      whiteSpace: "pre-wrap",
      padding: "10px 12px",
      borderRadius: "12px",
      fontFamily: "system-ui, -apple-system, Segoe UI, Roboto, Arial, sans-serif",
      fontSize: "13px",
      lineHeight: "1.35",
      background: who === "user" ? "#1f6feb" : "#e9eef5",
      color: who === "user" ? "#fff" : "#111"
    });
    row.appendChild(b);
    chat.appendChild(row);
    chat.scrollTop = chat.scrollHeight;
    return b; // devuelve el nodo para poder modificarlo (ej: loading)
  }

  var composer = el("div");
  Object.assign(composer.style, {
    padding: "10px",
    display: "flex",
    gap: "8px",
    borderTop: "1px solid #eee",
    background: "#fff"
  });

  var input = el("input", { type: "text", placeholder: "Type a message..." });
  Object.assign(input.style, {
    flex: "1",
    padding: "10px 10px",
    border: "1px solid #ddd",
    borderRadius: "10px",
    outline: "none",
    fontSize: "13px",
    fontFamily: "system-ui, -apple-system, Segoe UI, Roboto, Arial, sans-serif"
  });

  var send = el("button");
  send.textContent = "Send";
  Object.assign(send.style, {
    border: "0",
    borderRadius: "10px",
    padding: "10px 12px",
    background: "#111",
    color: "#fff",
    cursor: "pointer",
    fontFamily: "system-ui, -apple-system, Segoe UI, Roboto, Arial, sans-serif",
    fontSize: "13px"
  });

  composer.appendChild(input);
  composer.appendChild(send);

  panel.appendChild(header);
  panel.appendChild(chat);
  panel.appendChild(composer);

  document.body.appendChild(btn);
  document.body.appendChild(panel);

  // ---- lógica de red ----

  async function postMessage(text) {
    var sid = getSessionId();
    var url = API_BASE + "/scaffold-agent/chat?token=" + encodeURIComponent(TOKEN);

    var res = await fetch(url, {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        "X-Widget-Token": TOKEN
      },
      body: JSON.stringify({ session_id: sid, message: text })
    });

    if (!res.ok) {
      var fallback = "Something went wrong while processing your request.\nPlease try again in a few minutes.";

      if (res.status === 401) {
        fallback = "This widget is not configured correctly for this website.\nPlease contact the site owner.";
      } else if (res.status === 403) {
        fallback = "This website is not allowed to use this widget.\nPlease contact the site owner.";
      } else if (res.status === 429) {
        fallback = "Too many requests in a short time.\nPlease wait a moment and try again.";
      } else if (res.status >= 500) {
        fallback = "Something went wrong sending your request.\nPlease try again in a few minutes or contact the company directly.";
      }

      bubble(fallback, "bot");
      return;
    }

    var data = await res.json();
    bubble(data.reply || "(no reply)", "bot");
  }

  // Pide el saludo al servidor la primera vez que se abre el widget.
  // Muestra "..." mientras espera y lo reemplaza con la respuesta real.
  async function fetchGreeting() {
    var sid = getSessionId();
    var url = API_BASE + "/scaffold-agent/chat?token=" + encodeURIComponent(TOKEN);

    // Burbuja de "escribiendo..." mientras carga
    var loadingNode = bubble("...", "bot");
    send.disabled = true;
    input.disabled = true;

    try {
      var res = await fetch(url, {
        method: "POST",
        headers: { "Content-Type": "application/json", "X-Widget-Token": TOKEN },
        body: JSON.stringify({ session_id: sid, message: "__greeting__" })
      });

      if (res.ok) {
        var data = await res.json();
        loadingNode.textContent = data.reply || "¡Hola! ¿En qué puedo ayudarte?";
      } else {
        loadingNode.textContent = "¡Hola! ¿En qué puedo ayudarte?";
      }
    } catch (e) {
      loadingNode.textContent = "¡Hola! ¿En qué puedo ayudarte?";
    } finally {
      send.disabled = false;
      input.disabled = false;
      input.focus();
    }
  }

  function sendNow() {
    var t = (input.value || "").trim();
    if (!t) return;
    bubble(t, "user");
    input.value = "";
    postMessage(t);
  }

  function toggle(open) {
    panel.style.display = open ? "block" : "none";
    if (open) {
      // Pide el saludo al LLM la primera vez que se abre
      if (!_greeted) {
        _greeted = true;
        fetchGreeting();
      } else {
        setTimeout(function(){ input.focus(); }, 0);
      }
    }
  }

  btn.addEventListener("click", function () { toggle(panel.style.display === "none"); });
  close.addEventListener("click", function () { toggle(false); });
  send.addEventListener("click", sendNow);
  input.addEventListener("keydown", function (e) {
    if (e.key === "Enter") sendNow();
  });

})();
""".strip()
