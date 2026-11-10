# Verification record

Checked on 2026-11-10. This record describes the independently written synthetic demo, not the original operational tools.

## Automated behavior checks

`npm test`: 24 tests passed, zero failures. The suite checks priority/deadline boundaries, stable queue ordering, held and duplicate physical occupancy, combined handling/destination eligibility, transfer-door isolation, unknown/stale profiles, unique proposals, action revalidation, completion, immutable inputs, clock advancement, metric populations, import bounds, safe identifiers, CSV escaping and repeatable fixtures. Proposal checks independently verify constraints across multiple scenario presets, seeds and both queue modes.

The profile-refresh and heatmap metric tests were corrected before implementation changes: unknown profiles remain unknown; destination demand divided by capacity is distinct from proposed physical door-zone workload.

## Integration status

- `npm run typecheck`: passed.
- Sites production build (`build-site.mjs`): passed. Vinext reports the route as unclassified by its static analyzer; the page served successfully in the local preview.
- Browser checked: assignment, reload persistence, completion, undo, door disablement, missing-profile refresh, arrival-order planning, queue filtering, manual feasible-door choice with a required note, JSON export/reimport with action history, and rejection of invalid JSON without changing current work.
- A 390-pixel phone viewport was checked. The page has no horizontal overflow; wide data tables scroll within their own panels. The temporary viewport override was reset.
- No browser console errors or warnings were reported during the checked flow.
- Independent review covered the engine; the integrated interface was checked directly in the browser. Review also corrected sparse-array validation, keeping completed/empty work last in both modes, and a proposal-versus-manual workload display mismatch.
- Hosting reported successful deployment. Public access was enabled explicitly, and an anonymous HTTP request returned 200 without a sign-in redirect. The demo link is in the README. GitHub Actions verifies this portable source export independently of the hosting account.

## What this verification does not establish

- There are no live warehouse feeds or external dispatch commands.
- This is a greedy advisory planner, not a globally optimal schedule or forecast.
- Local browser persistence is not a shared operational database or tamper-proof audit.
- Fictional capacity ratios do not measure throughput, labor utilization or business impact.
- Original private source files and their review notes are excluded from this project.
