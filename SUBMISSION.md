# Submitting to the Muse connector directory

On 2026-09-18 Meta opened Muse to developer-built connectors ("you bring the
API"). Third parties submit through the developer portal at **muse.ai/platform**
(verified live 2026-09-21): describe the product, submit for review (Meta
checks functional, security, and legal requirements plus end-to-end testing),
then appear in the Muse directory. This guide covers what's needed to submit
the Food Tracker.

> Status note: the program is days old. The portal and the review bar above are
> confirmed on Meta's official page, but terms, fees, revenue share, and review
> timelines are undisclosed. Expect the checklist below to grow once the
> portal's developer docs are public.

## What Meta reviews (per public reporting)

1. **Functional** - the connector works end to end from inside Muse.
2. **Security** - safe credential handling, no over-collection of user data.
3. **Legal** - privacy policy, terms of service, accurate listing copy.

Meta does not review *custom* (user-built, unlisted) connectors; a directory
listing is what puts you under review and in front of every user.

## Submission checklist

- [ ] **Public HTTPS deployment** of this server (Fly/Render/Railway per README).
      Health check at `/health`, MCP endpoint at `/mcp`.
- [ ] **Reviewer credentials**: generate a dedicated API key
      (`python -m src.server create-key --name "meta-review"`) so reviewers can
      exercise all 15 tools without touching real users.
- [x] **Privacy policy** (hosted at `/privacy`): what data is stored (inventory
      items, shopping lists, API-key hashes), where (host region), retention
      (until deleted), deletion on request, and that data is never sold or used
      for ads.
- [x] **Terms of service** (hosted at `/terms`).
- [ ] **Listing copy**: name ("Food Tracker"), short description, what it does
      with a user's data, and support contact email.
- [ ] **Test script for reviewers**: the e2e flow in `test_e2e.py` doubles as
      one - add the reviewer key and endpoint to it.
- [x] **Data deletion path**: `DELETE /api/account` (Bearer) permanently
      deletes the user and all their data; also documented on the privacy page.

## Likely follow-ups from review

- **Per-user OAuth instead of manual API keys.** The current Bearer-key model
  is fine for the custom-connector path (user pastes their own key), but a
  directory listing where users tap "Connect" will almost certainly require a
  standard OAuth 2.0 authorization-code flow so Muse can mint per-user tokens
  without manual key handling. Budget engineering time for this; the tool layer
  already isolates users by id, so only the auth edge needs to change.
- **Approval scoping**: confirm which tools are read vs write so Muse can show
  the right permission prompts (reads: list/suggest/details/expiring/low-stock;
  writes: everything else).

## Steps

1. Deploy (README) and smoke-test from a second machine with a fresh key.
2. Write and host the privacy policy + terms.
3. Open muse.ai/platform, create a developer account, start a connector
   submission with the endpoint URL, reviewer key, policies, and listing copy.
4. Respond to review feedback; iterate.

Until the listing is live, anyone can still use this *today* via Muse's custom
connector flow (see README) - no portal approval needed for that path.
