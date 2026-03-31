from __future__ import annotations


def demo_html(token: str) -> str:
    safe_token = (token or "").replace('"', "").replace("'", "")
    return f"""<!doctype html>
<html lang="en">
  <head>
    <meta charset="utf-8" />
    <meta name="viewport" content="width=device-width,initial-scale=1" />
    <title>Scaffold Agent Demo</title>
    <style>
      body {{
        margin: 0;
        font-family: system-ui, -apple-system, Segoe UI, Roboto, Arial, sans-serif;
        background: #f6f7f9;
        color: #111;
      }}
      .wrap {{
        max-width: 920px;
        margin: 0 auto;
        padding: 48px 20px 80px;
      }}
      .hero {{
        background: white;
        border-radius: 18px;
        box-shadow: 0 10px 30px rgba(0,0,0,.08);
        padding: 28px;
      }}
      h1 {{
        margin: 0 0 10px;
        font-size: 34px;
      }}
      p {{
        line-height: 1.5;
        color: #444;
      }}
      .box {{
        margin-top: 18px;
        background: #f0f2f5;
        border-radius: 12px;
        padding: 14px;
        font-size: 14px;
        word-break: break-all;
      }}
      .note {{
        margin-top: 18px;
        font-size: 13px;
        color: #666;
      }}
      code {{
        background: #eef1f4;
        padding: 2px 6px;
        border-radius: 6px;
      }}
    </style>
  </head>
  <body>
    <div class="wrap">
      <div class="hero">
        <h1>Scaffold Agent Demo</h1>
        <p>
          This page loads the real installable widget using the tenant token in the URL.
          Open the chat button in the bottom-right corner and test the full flow.
        </p>

        <div class="box">
          <strong>Token in use:</strong><br />
          {safe_token or "(missing token)"}
        </div>

        <div class="note">
          This page is intended for internal demos and client validation.
          If the widget does not load, check the token, tenant config, and allowed origins.
        </div>
      </div>
    </div>

    <script src="/scaffold-agent/widget.js?token={safe_token}"></script>
  </body>
</html>
"""
