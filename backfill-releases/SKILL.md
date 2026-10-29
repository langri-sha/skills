---
name: backfill-releases
description: >-
  Create the missing git tags and GitHub releases for every version a
  beachball-published repository has already shipped, from its CHANGELOG.json
  files. Use when moving a repository onto GitHub releases (a Release workflow
  that tags and releases each version it publishes), or when asked to "backfill
  releases", "tag old versions", "create releases for historical versions".
  Triggers: "/backfill-releases".
disable-model-invocation: true
metadata:
  author: langri-sha
  version: '1.0.0'
  argument-hint: '[--apply] [--template TEMPLATE]'
---

# Backfill Releases

`scripts/backfill-releases` reads every `CHANGELOG.json` on the default branch.
For each version it finds the commit that set the package's `package.json` to
that version, which is beachball's publish commit, and plans a tag named by the
template plus a GitHub release. Without `--apply` it only prints the plan.

With `--apply` it creates what is missing, oldest version first:

- An annotated tag on the publish commit. Its message is the version's
  `CHANGELOG.md` section, and its date is the changelog's publish date. GitHub
  sometimes rejects the push as `reference already exists` after storing the
  tag; when the remote tag is the one just created, the script warns and goes
  on.
- A release with GitHub's generated notes, starting at the same package's
  previous tag. When those notes list no pull requests, as for versions built
  before the repository took pull requests, the changelog section comes first.
  No backfilled release is marked Latest.

## Workflow

1. From any checkout of the repository, including the bare repository of a
   worktree layout, with `gh` authenticated and `jq` installed, run the script;
   `<skill-dir>` is the directory holding this file:

   ```sh
   <skill-dir>/scripts/backfill-releases
   ```

2. Take every warning to the user before applying. Never delete or move a tag on
   your own.
   - _Tags that match no published version_: often carried in by a history
     import, like `v2.x` tags from a repository merged in.
   - _`skip: … is on another commit`_: the tag is left alone, and the next
     version's notes start from it.
   - _No commit sets a version_: that version is left out.
   - _A version listed more than once_: beachball files a release of `none`
     changes under the version it didn't bump. The first entry is the publish,
     so the rest are left out; nothing to fix.
   - _A change file names a package that is not here_: usually a rename.
     Beachball skips such files and leaves them behind, so fix their
     `packageName`.

3. Use the template the Release workflow will tag with from now on. The default
   is `v{version}` for one package and `{name}_v{version}` for a workspace; pass
   `--template` for anything else. A workspace that publishes one package, its
   others private, can tag it `v{version}` too: pass `--package` with its name,
   since the other packages' versions would claim the same tags.

4. Run it again with `--apply`. Every release notifies the repository's
   watchers, and a large workspace takes a while: a few dozen packages can plan
   hundreds of releases.

5. A release made before the backfill, such as the first automated one, lists
   every pull request since the repository began. Regenerate its notes from its
   previous tag, keeping any changelog section at the top:

   ```sh
   gh api repos/OWNER/REPO/releases/generate-notes \
     -f tag_name=v1.0.0 -f previous_tag_name=v0.2.13 --jq .body
   gh release edit v1.0.0 --notes-file notes.md
   ```

## Going forward

From here on, the repository's Release workflow tags each version it publishes
with the same template and creates its GitHub release, so the tags continue
where the backfill stopped.

Keep beachball's `gitTags` off; with it on, beachball would add its own
`<name>_v<version>` tags next to the workflow's.
