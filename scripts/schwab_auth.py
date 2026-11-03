#!/usr/bin/env python3
"""One-time (then weekly) Schwab sign-in for the Trading Floor's READ-ONLY market data.

Run this on your own computer (never in a chat, never paste the results anywhere public):

    1. Create an app at https://developer.schwab.com (choose the "Market Data Production" API).
       Set its callback URL to https://127.0.0.1  and note the App Key and Secret.
    2. python3 scripts/schwab_auth.py
    3. Open the printed link, sign in, approve. Your browser lands on an error page: copy that whole address
       from the address bar and paste it back here.
    4. Save the three values it prints as GitHub secrets (repo Settings > Secrets and variables > Actions),
       or with the GitHub CLI:   gh secret set SCHWAB_REFRESH_TOKEN
       Names: SCHWAB_APP_KEY, SCHWAB_APP_SECRET, SCHWAB_REFRESH_TOKEN

Schwab refresh tokens expire after 7 days, so repeat step 2-4 about weekly. If you don't, the floor
simply falls back to free data (it says so on the Data tab).
"""
import base64
import getpass
import json
import urllib.parse
import urllib.request

key = input("App Key: ").strip()
secret = getpass.getpass("App Secret (hidden): ").strip()
print("\nOpen this link, sign in and approve:\n  https://api.schwabapi.com/v1/oauth/authorize?" + urllib.parse.urlencode({"client_id": key, "redirect_uri": "https://127.0.0.1"}))
url = input("\nPaste the full address your browser ended up on: ").strip()
code = urllib.parse.parse_qs(urllib.parse.urlparse(url).query).get("code", [""])[0]   # parse_qs already URL-decodes it
if not code:
    raise SystemExit("No ?code= found in that address.")
body = urllib.parse.urlencode({"grant_type": "authorization_code", "code": code, "redirect_uri": "https://127.0.0.1"}).encode()
req = urllib.request.Request("https://api.schwabapi.com/v1/oauth/token", data=body, headers={
    "Authorization": "Basic " + base64.b64encode(f"{key}:{secret}".encode()).decode(), "Content-Type": "application/x-www-form-urlencoded"})
res = json.load(urllib.request.urlopen(req, timeout=30))
print("\nSuccess. Save these as GitHub Actions secrets (keep them private):\n")
print("  SCHWAB_APP_KEY       =", key)
print("  SCHWAB_APP_SECRET    = (the secret you just typed)")
print("  SCHWAB_REFRESH_TOKEN =", res["refresh_token"])
print("\nThe refresh token works for 7 days.")
