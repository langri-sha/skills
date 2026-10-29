---
name: web-app-preflight
description: Readiness checklist for a web app before it goes out, like a pilot's preflight, reporting PASS, FAIL, NOT APPLICABLE or UNVERIFIED with evidence for each check. Covers its audience and visibility, analytics (PostHog), /llms.txt, link previews, browser and mobile chrome, the 404 and previews, with a Next.js section. Runs only when invoked by name.
disable-model-invocation: true
metadata:
  author: langri-sha
  version: '1.0.0'
  argument-hint: '[path, URL or app name] [what to focus on]'
---

# Web App Preflight

A preflight walks the checklist and reports whether the app is ready to depart.
It inspects and reports. It does not merge, deploy, change DNS, create or
reconfigure provider projects (PostHog included), rotate secrets, or publish
anything. Fix a gap only when the task that invoked the preflight asks for
fixes, and then as separate work after the report.

The checks are outcomes, not a stack: no framework, styling library, theme,
WebGL, service worker or visual style is required. Many of them came from
langri-sha.com, whose choices are not mandates for other apps.

## 1. File the flight plan

Establish these before checking anything, from the invocation, the repo
(readme, `AGENTS.md`, deploy workflows, infrastructure) and the user. Ask for
what can't be found; don't guess audience or visibility.

- **Audience and visibility**: public; private behind authentication or IAP;
  internal. Previews may differ from production.
- **Data sensitivity**: does it handle health, patient, financial or other
  personal data?
- **Framework and rendering**: static export, server-rendered, SPA; which
  framework. Read [references/nextjs.md](references/nextjs.md) for Next.js.
- **Hosting and environments**: production host, preview URLs and whether they
  serve under a base path (such as `/pull/<n>/<app>/`), every surface that
  answers requests (bucket, CDN, origin, router).
- **Analytics intent**: none, pageviews and web vitals, or product analytics;
  which PostHog project and host; whether consent is required.
- **Install intent**: is adding it to a home screen expected?

Restate the flight plan at the top of the report. Every check below either
applies to it or is NOT APPLICABLE with the reason.

## 2. Results and evidence

| Result         | Means                                                                                |
| -------------- | ------------------------------------------------------------------------------------ |
| PASS           | Observed working in this run, with the evidence named                                |
| FAIL           | Observed missing or wrong                                                            |
| NOT APPLICABLE | The flight plan rules it out; say which part                                         |
| UNVERIFIED     | Not observed: untestable here, needs a device or account, or awaits an owner decision |

PASS needs the outcome itself: the response's status and headers, the rendered
`<head>`, a computed color, a decoded request. A file that exists, a package
that is installed, a screenshot, a green CI run or an open PR claiming the fix
are leads, not evidence. When the evidence is partial, the result is
UNVERIFIED and says what is missing.

Default inspection, in order of preference:

1. Read the source and configuration.
2. Read existing build output, or build locally without production secrets.
3. Serve that build locally and read it with `curl` or a headless browser.
4. Read-only `GET`/`HEAD` requests to preview or production URLs the user named.

Don't log in past an app's authentication or IAP, load-test, send analytics
events, or call provider admin APIs as part of an inspection. Some outcomes
can't be emulated, such as overscroll, retracting toolbars, notches and safe
areas: measure what can be measured and leave the rest UNVERIFIED with "needs a
device".

## 3. Checks

### Visibility and secrets (always)

- Private and internal apps stay private. No check passes by exposing one;
  where a check needs a public surface, it is NOT APPLICABLE. Their privacy
  passes only on an observed refusal, such as an unauthenticated request
  answered by a redirect to sign-in, 401 or 403 on each surface; a repo that
  shows nothing exposed leaves it UNVERIFIED.
- Previews are behind authentication or answer `X-Robots-Tag: noindex`.
- The client bundle carries no secret or privileged credentials, such as a
  PostHog personal API key (`phx_…`), a Supabase secret or `service_role` key,
  a service-account key, or a private API key or password. Search the built
  output. Tokens a provider documents as public client tokens are not findings:
  a PostHog project token (`phc_…`), a Supabase publishable or anon key. They
  are only as safe as the server-side rules behind them, such as Supabase's
  row-level security. Identifiers such as project or organization IDs aren't
  credentials either.

### Not found (always)

- An unknown path answers HTTP 404, not a 200 page that says "not found", on
  every surface that serves the app: production, the preview origin, any
  router in front of them, with and without a trailing slash, and nested.
- The page has one `<title>`, is `noindex`, carries no canonical URL or Open
  Graph tags of another page, and offers a way home that resolves under the
  base path.
- Its own color metadata matches its own background (next section).

### Browser chrome and mobile (always, per page)

- `theme-color`, where set, matches the color actually rendered at the top of
  that page, in each color scheme it supports. A page with a different
  background, such as a default 404, sets its own or none.
- `color-scheme` declares the schemes the page is designed for (`light`,
  `dark` or both), so form controls, scrollbars and forced darkening follow it.
- A solid `background-color` sits under gradients and images on the root, so
  overscroll and letterboxing don't show the browser's default canvas.
- `<meta name="viewport" content="width=device-width, initial-scale=1">`.
- Full-viewport-height layouts use `dvh` after a `vh` fallback. NOT APPLICABLE
  without one.
- `viewport-fit=cover` only with content kept clear of the cutouts, by
  `env(safe-area-inset-*)` padding or measured clearance at the device's
  insets. NOT APPLICABLE without `viewport-fit=cover`.
- An SVG or ICO favicon, and a 180×180 `apple-touch-icon` for public apps and
  ones meant for the home screen.
- Web app manifest, when installing to a home screen is expected: served as
  `application/manifest+json` by every surface, with `name`, `display`,
  `theme_color` and `background_color` matching the page, 192 and 512 px icons
  and a maskable one with its art inside the safe zone, and a `start_url`,
  `scope` and icon URLs that resolve under a preview's base path.

### Discovery and link previews (public apps)

- A specific `<title>` and meta description that say what the app is.
- A canonical URL on the production host, which previews keep pointing at.
- Open Graph `og:title`, `og:description`, `og:url`, `og:site_name`,
  `og:type`; `og:image` at 1200×630 when one exists.
- The prerendered HTML, without JavaScript, says what the app is.
- Structured data where it fits, such as a schema.org `Person` with `sameAs`
  and `rel="me"` links on a personal site. NOT APPLICABLE elsewhere.
- `robots.txt` is served and its crawler policy, AI crawlers included, is the
  owner's decision. UNVERIFIED with "owner decision" until one is recorded;
  never invent a policy.
- Description copy and an `og:image` are the owner's to write. Missing ones are
  UNVERIFIED with "owner decision", not filled with invented copy.

### /llms.txt (public apps)

- `/llms.txt` answers 200 as `text/plain` or `text/markdown` on production and
  previews, following [llmstxt.org](https://llmstxt.org/): an `# H1` name, a
  `>` summary, then `##` sections of links.
- It describes the app as it is and links only public resources. No private
  routes, admin or preview URLs, internal repositories, prompts, data or keys.
- A response check in CI asserts its status, type and heading.
- Private and internal apps: NOT APPLICABLE. The fix is never to make the app or
  the file public.

### Analytics: PostHog (unless the flight plan has no analytics)

- The app sends to the PostHog project meant for it, on the region host meant
  for it, through a first-party proxy where one serves the app's domain. A
  project per app is fine.
- The browser only sees the project token, injected at build time from the
  environment. A build without a token doesn't load the SDK.
- Capture is explicit, not left to project toggles: autocapture, session
  recording, heatmaps, exception capture, surveys and web vitals are each set
  on purpose. `person_profiles: 'identified_only'` unless people are identified
  on purpose, and Do Not Track honored.
- Preview, local and production events can be told apart, by property or by
  project.
- Consent matches the data and the audience. Cookieless or memory-only
  persistence is not consent-exempt by itself. Health and other sensitive apps
  may rightly have no analytics, or opt-in only, and properties carry no
  personal data.
- Delivery: PASS needs an observed event, such as a decoded capture request in
  a local or preview build pointed at the proxy, or the user's own read of the
  project's live events. Otherwise UNVERIFIED. Never send test events or create
  projects to get evidence.
- Core Web Vitals are measured from real visits, such as PostHog's
  `$web_vitals`, when performance matters to the app. The SDK drops headless
  browsers as bots, so a local run may send nothing.

### Accessibility (always)

Record what evidence exists: `lang` on `<html>`, text alternatives for images
and icon-only links, a visible focus outline, a keyboard path to every control,
contrast. For a full audit, run the `web-design-guidelines` skill; the preflight
records its result, it doesn't restate it.

### Previews and base paths (when previews serve under a base path)

- Assets, links, the manifest, icons and the 404's way home resolve under the
  base path, while canonical and `og:url` stay on production.
- The response checks CI runs against previews cover the routes above:
  `/llms.txt`, the manifest's type, the 404's status and body.

## 4. Report

1. **Flight plan**, as established, with anything assumed marked as such.
2. **Checklist**, one table per section above:
   `| Check | Result | Evidence | Gap or action |`. Evidence names the command,
   file or URL and what it showed.
3. **Open decisions** for the owner.
4. **Verdict**, one of:
   - `Not ready: N FAIL` when anything FAILs.
   - `Ready, N unverified` when nothing FAILs but something is UNVERIFIED,
     listing those for the owner to accept or close.
   - `Ready` only when every check is PASS or NOT APPLICABLE.

   Then this line, verbatim:
   "Readiness is an assessment only. It authorizes no merge, deploy, DNS,
   provider or secret change."
