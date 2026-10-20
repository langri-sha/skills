# Next.js (App Router)

Where the checks in `SKILL.md` live in a Next.js app, and how to read them from
`next build` output. For the APIs themselves, see the `next-best-practices`
skill, `metadata.md` and `file-conventions.md` in particular.

## Reading the evidence

- With `output: 'export'`, read the exported `index.html`, `404.html` and the
  route files in the output directory. Otherwise run `next start` and request
  the routes. Check the rendered `<head>`, not the source.
- Build once with the preview's base path (`basePath` from an environment
  variable such as `BASE_PATH=/pull/1`) to check what resolves under it.
- `NEXT_PUBLIC_*` values are inlined at build time. The variable the app reads
  and the one the build workflow sets must have the same name, and a local
  build without it must still work. Search the client chunks for `phx_` and
  any other administrative credential.

## Where each check lives

| Check | Next.js |
| --- | --- |
| `theme-color`, `color-scheme`, `viewport-fit` | `export const viewport` (`themeColor`, `colorScheme`, `viewportFit`) in the `page.tsx` or `not-found.tsx` they describe. In the root layout they apply to every page, the 404 included. Pages that each add fields need them combined into one export. |
| Title, description | `export const metadata` in the root layout, with a page-level `title` where it differs |
| Canonical, Open Graph | `metadataBase` in the root layout, then `alternates.canonical` and `openGraph` in the page they describe, so the 404 doesn't inherit them. With `metadataBase` on the production URL, previews keep the production canonical. |
| Favicon, apple-touch-icon | `app/icon.svg`, `app/favicon.ico`, `app/apple-icon.png`, which add the `<link>` tags to every page |
| Manifest | `app/manifest.ts` returning `MetadataRoute.Manifest`, with `export const dynamic = 'force-static'` under `output: 'export'`. Relative `start_url`, `scope` and icon `src` resolve under a base path. Icons the manifest names go in `public/`, since `app/` icons get content-hashed URLs and extra `<link>` tags. |
| 404 | `app/not-found.tsx`, with its own `metadata.title` and `viewport`. Next adds `noindex`. Under `output: 'export'` it becomes `404.html`, which the host must serve with status 404. |
| Way home, internal links | `next/link`, which prefixes `basePath`; a plain `<a href="/">` doesn't |
| `/llms.txt`, `robots.txt` | Static files in `public/`, or `app/robots.ts`. Check the content type each host serves them with. |
| Structured data | A `<script type="application/ld+json">` rendered by a server component |
| PostHog | A client component that initializes `posthog-js` in an effect, imported dynamically only when the project token is set, so builds without one never load the SDK |

## Content types outside Next.js

A static export is served by whatever host takes it, and Next.js doesn't set
its content types. nginx's stock `mime.types` has no `webmanifest` entry, so
the manifest needs its type set explicitly there; a `types {}` block replaces
the whole map, so set it on the location instead. Check every surface that
serves the export.
