"""Public web pages for the Food Tracker connector.

Landing page (product description + self-serve API key signup), privacy
policy, and terms of service. These are required for the Meta connector
directory review and for anyone connecting via the custom-connector path.
"""
from __future__ import annotations

import html
import os

SUPPORT_EMAIL = os.environ.get("SUPPORT_EMAIL", "support@foodtracker.example")
CONNECTOR_NAME = "Food Tracker"

_CSS = """
:root { color-scheme: light dark; }
body { font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
       max-width: 680px; margin: 0 auto; padding: 32px 20px; line-height: 1.6; }
h1 { font-size: 2rem; margin-bottom: 0.25rem; }
.sub { color: #666; font-size: 1.1rem; margin-top: 0; }
.card { border: 1px solid #ddd; border-radius: 12px; padding: 20px; margin: 24px 0; }
button, .btn { background: #1877f2; color: #fff; border: 0; border-radius: 8px;
               padding: 12px 20px; font-size: 1rem; cursor: pointer; text-decoration: none;
               display: inline-block; }
button:disabled { opacity: 0.6; cursor: default; }
code.key { display: block; background: #f4f4f4; color: #111; padding: 12px; border-radius: 8px;
            word-break: break-all; margin: 12px 0; font-size: 0.95rem; }
.warn { background: #fff8e1; border: 1px solid #ffe082; border-radius: 8px; padding: 12px; }
footer { margin-top: 40px; font-size: 0.85rem; color: #666; }
ol.steps li { margin-bottom: 12px; }
.hidden { display: none; }
"""

_LANDING = """<!doctype html>
<html lang="en">
<head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>{name} - a Muse connector</title><style>{css}</style></head>
<body>
<h1>{name}</h1>
<p class="sub">Your fridge, freezer, cupboard, and drinks, tracked by your AI assistant.</p>

<p>{name} is a connector for Meta Muse. It keeps a personal inventory of your
food and drink, tells you what is about to expire or running low, suggests
recipes from what you already have, and keeps your shopping list.</p>

<div class="card">
<h2>How it works</h2>
<ol class="steps">
<li><strong>Get your free API key</strong> below. It is shown once, so save it.</li>
<li><strong>Connect it in Muse.</strong> Ask Muse: "Build a custom integration
to my Food Tracker MCP server at <code>{origin}/mcp</code>. It is a remote MCP
server over streamable HTTP. Authenticate with
<code>Authorization: Bearer &lt;your-api-key&gt;</code>."</li>
<li><strong>Ask Muse</strong> things like "what is in my fridge?", "what can I
cook tonight?", "what expires this week?", or show it a photo of your fridge
to log items.</li>
</ol>
</div>

<div class="card">
<h2>Get your API key</h2>
<p>One key per person. It identifies your inventory and nothing else.</p>
<button id="signup">Get my API key</button>
<div id="result" class="hidden">
<p><strong>Your API key (shown once):</strong></p>
<code class="key" id="key"></code>
<button id="copy">Copy key</button>
<p class="warn">Save this key somewhere safe. If you lose it, you can rotate it
from the app, or email <a href="mailto:{email}">{email}</a>.</p>
</div>
<p id="err" class="hidden warn"></p>
</div>

<div class="card">
<h2>What it can do</h2>
<ul>
<li>Track items across fridge, freezer, cupboard, and drinks with quantities and expiry dates</li>
<li>Bulk-add from receipts or order confirmations (duplicates merge automatically)</li>
<li>Flag what expires soon and what is running low</li>
<li>Suggest recipes from 60 built-in recipes, ranked by ingredients you have</li>
<li>Push missing recipe ingredients to a shopping list, and move bought items into inventory</li>
</ul>
</div>

<footer>
<a href="/privacy">Privacy policy</a> - <a href="/terms">Terms of service</a> -
<a href="mailto:{email}">Support: {email}</a><br>
Your data is stored only to run the service. You can delete your account and
all data at any time.
</footer>

<script>
const btn = document.getElementById('signup');
btn.onclick = async () => {{
  btn.disabled = true;
  try {{
    const r = await fetch('/api/signup', {{method: 'POST'}});
    const j = await r.json();
    if (!r.ok) throw new Error(j.error || 'signup failed');
    document.getElementById('key').textContent = j.api_key;
    document.getElementById('result').classList.remove('hidden');
    btn.classList.add('hidden');
  }} catch (e) {{
    const err = document.getElementById('err');
    err.textContent = 'Could not create a key: ' + e.message + '. Please try again later.';
    err.classList.remove('hidden');
    btn.disabled = false;
  }}
}};
document.getElementById('copy').onclick = async () => {{
  await navigator.clipboard.writeText(document.getElementById('key').textContent);
}};
</script>
</body></html>
"""

_PRIVACY = """<!doctype html>
<html lang="en">
<head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>{name} - Privacy Policy</title><style>{css}</style></head>
<body>
<h1>Privacy Policy</h1>
<p>Last updated: 2026-09-21</p>

<h2>What we store</h2>
<ul>
<li><strong>Inventory and shopping lists:</strong> the item names, quantities,
units, locations, expiry dates, thresholds, and notes that you (or your AI
assistant acting for you) save through the connector.</li>
<li><strong>API key records:</strong> a one-way hash of your API key and when it
was created, used to authenticate your requests. We never store your key in
readable form.</li>
</ul>

<h2>What we do not collect</h2>
<ul>
<li>We never see your photos. If you show Muse a fridge photo, Muse reads it
and sends us only the structured item list.</li>
<li>No advertising profiles, no tracking cookies, no sale of your data. Your
data is used only to answer your requests.</li>
</ul>

<h2>Where data lives</h2>
<p>Data is stored in a database on our hosting provider's servers in the United
States. Backups, if enabled by the host, stay within the same region.</p>

<h2>Retention and deletion</h2>
<p>Your data is kept until you delete it. You can delete your account and
everything in it at any time by sending
<code>DELETE /api/account</code> with your API key as a Bearer token, or by
emailing <a href="mailto:{email}">{email}</a> from an address you control and
we will delete it for you.</p>

<h2>Sharing</h2>
<p>We share data with no one except our hosting provider (to run the service)
and Meta's Muse (to answer your requests through the connector). We will
disclose data if required by law.</p>

<h2>Contact</h2>
<p>Questions: <a href="mailto:{email}">{email}</a>.</p>

<footer><a href="/">Back to {name}</a></footer>
</body></html>
"""

_TERMS = """<!doctype html>
<html lang="en">
<head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>{name} - Terms of Service</title><style>{css}</style></head>
<body>
<h1>Terms of Service</h1>
<p>Last updated: 2026-09-21</p>

<h2>The service</h2>
<p>{name} is a free connector that stores a personal food-and-drink inventory
and shopping list, exposed to AI assistants over the Model Context Protocol
(MCP). It is provided as-is, without warranties of any kind.</p>

<h2>Your responsibilities</h2>
<ul>
<li>Keep your API key secret. Anyone with your key can read and change your
inventory.</li>
<li>Use the service lawfully and do not abuse it (for example, do not flood it
with automated requests). We may rate-limit or suspend keys that degrade the
service for others.</li>
<li>You own the data you store and are responsible for its accuracy.</li>
</ul>

<h2>Your data</h2>
<p>You can export your data through the connector's list tools and delete your
account and all data at any time (see the privacy policy). Deletion is
permanent.</p>

<h2>Changes and availability</h2>
<p>This is an early-stage service. We may change, suspend, or discontinue it at
any time, and we will aim to give reasonable notice of breaking changes.</p>

<h2>Liability</h2>
<p>To the maximum extent permitted by law, we are not liable for any indirect
or consequential damages arising from use of the service, including decisions
made about food safety based on stored expiry dates. Always use your own
judgment about whether food is safe to eat.</p>

<h2>Contact</h2>
<p><a href="mailto:{email}">{email}</a></p>

<footer><a href="/">Back to {name}</a></footer>
</body></html>
"""


def landing_page(origin: str) -> str:
    return _LANDING.format(name=html.escape(CONNECTOR_NAME), css=_CSS,
                           origin=html.escape(origin.rstrip("/")),
                           email=html.escape(SUPPORT_EMAIL))


def privacy_page() -> str:
    return _PRIVACY.format(name=html.escape(CONNECTOR_NAME), css=_CSS,
                           email=html.escape(SUPPORT_EMAIL))


def terms_page() -> str:
    return _TERMS.format(name=html.escape(CONNECTOR_NAME), css=_CSS,
                         email=html.escape(SUPPORT_EMAIL))
