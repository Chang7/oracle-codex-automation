---
name: mcp-update-guard
description: Update automation sources and deployment safely while preserving authentication, user configuration, and active runs.
---

# Automation maintenance

Follow the installed `docs/AUTOMATION_POLICY.md`. Read repository instructions,
identify authoritative source and deployment, and inspect existing changes.

- Keep one writer per file. Preserve unrelated user changes, authentication,
  OAuth state, approved roots, browser profile seeds, and historical runs.
- Implement a coherent change, run focused behavior checks, and broaden tests
  according to risk. Do not add forced web reviews, receipt chains, or modes.
- Check upstream package identity and patch compatibility when changing runtime
  versions. Preserve an exact rollback version; do not execute a moving tag.
- Never restart shared services or replace a runtime underneath an active run.
  Recover the same owning task's run without duplicate submission.
- Keep reusable changes in source. Verify deployed byte parity before claiming
  installation, and report pending deployment honestly.
- For release work, verify exact-commit CI, immutable tag, published release,
  version consistency, and installation separately. A version bump is not a
  release. Never invent approval evidence or move a published tag.
  Check the peeled remote tag, `releases/latest`, and source/install byte parity;
  missing evidence is `release incomplete`.
- Preserve the configured commander and user-approved routing. Do not restore
  removed CGW endpoints or silently modify global policy.
- Report the meaningful changes, relevant test evidence, source/deployment
  status, and actual blockers. Stop after sufficient verification.

## Chat On Steroids release continuity

Chat On Steroids (CoS) uses the same fail-closed maintenance principles, but its
candidate source is GitHub Releases rather than npm. Run
`python scripts/check_cos_release_policy.py --installed-version <version>` for
the read-only candidate check.

- The candidate is the **latest stable published GitHub Release**. Ignore an
  unreleased repository `main` version, drafts, and prereleases until they are
  actually published as a stable release.
- Require the matching `Chat-On-Steroids-Extension.zip` release asset so app and
  companion-extension promotion cannot silently drift apart.
- A customized local CoS bundle must complete a verified customization rebase
  before it is eligible for staging.
- Active or uncertain exact work blocks runtime replacement. **Silence alone
  never authorizes replacement or resubmission**; preserve the existing exact
  task/session/command identity until terminal evidence or an explicit boundary.
- `READY_TO_STAGE_REBASE is staging authority only`; it is never permission for
  the checker to install, restart, promote, create a task, or create a browser
  session.
- After a separately authorized promotion in a proven exact-work-quiescent
  window, **reload the matching companion extension** and **refresh the affected
  ChatGPT tabs and connectors** before treating the installed pair as ready.
