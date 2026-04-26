# Wingman legal pages — drop-in for the Clippr static site

These two pages are the **Privacy Policy** and **Terms of Service**
required by Google Play and Apple App Store. They're written
specifically for Wingman and live under a `/wingman/` subpath of
clippr.io so they don't overlap with whatever Clippr already has at
`/privacy` or `/terms`.

## Files

- `clippr-deploy/privacy.html` → drop into Clippr at
  `project/wingman/privacy.html`
- `clippr-deploy/terms.html` → drop into Clippr at
  `project/wingman/terms.html`

(If your Clippr static-site root is elsewhere, place them so they
serve at the URLs below.)

## Final live URLs

- `https://clippr.io/wingman/privacy.html`
- `https://clippr.io/wingman/terms.html`

These are the URLs to paste into:

- Google Play Console → **App content → Privacy policy** field
- Apple App Store Connect → **App information → Privacy Policy URL**
- The Wingman app's own Settings → About row

## How to deploy

```bash
# In the Clippr repo
mkdir -p project/wingman
cp /path/to/wingman-og/legal/clippr-deploy/privacy.html  project/wingman/
cp /path/to/wingman-og/legal/clippr-deploy/terms.html    project/wingman/

git add project/wingman/
git commit -m "Add Wingman legal pages (privacy + terms)"
git push origin main

# DigitalOcean App Platform auto-deploys static sites on push.
# Wait ~1-2 min, then verify both URLs return 200.
```

## What's in them

Each page is plain self-contained HTML with inline CSS — no build
step, no framework, light/dark aware via `prefers-color-scheme`.

Both reference the **operator name** and **postal address** I pulled
from your Play Console screenshot:

- Operator: Oguzo Jeffries Nwali
- Address: 22 West Park Drive, Blackpool, FY3 9DN, United Kingdom
- Contact email: kevis2busy@gmail.com

When you convert your Play Console account to an Organization with a
DUNS-registered company name, do a find-and-replace on both files:

- `Oguzo Jeffries Nwali` → your registered company name
- The postal address can stay or be updated to your registered
  business address
- The contact email should ideally become a `support@yourdomain.com`
  alias once you've set one up — but the personal Gmail is
  acceptable for the first launch.

## What the pages actually cover

### Privacy Policy
- Who we are (operator name + address)
- Data we collect (account, screenshots, replies, push tokens, subscription status)
- How we use it
- Third parties: Google Gemini, Firebase, Expo, DigitalOcean, RevenueCat
- Where data is stored (DigitalOcean managed Postgres)
- Retention windows
- User rights (access, delete via Settings, export by email)
- UK GDPR / GDPR mention
- Security practices
- 18+ only
- Contact

### Terms of Service
- Acceptance + 18+ eligibility
- Description of service + user responsibility for sent messages
- Account responsibility (one person per account, secure password)
- Acceptable use (no harassment, illegal content, scraping, etc.)
- Subscription billing via Google Play, auto-renewal, refund policy
- IP ownership
- AI-generated content disclaimer (errors, biases, not professional advice)
- Termination
- Disclaimers + limitation of liability (£100 / 12 months cap)
- Governing law: England and Wales
- Contact

Both are written to satisfy:
- Google Play's "App content / Data safety" requirements
- Apple's App Review Guidelines § 5.1 (Privacy)
- UK GDPR / EEA GDPR baseline
- Standard SaaS app terms patterns
