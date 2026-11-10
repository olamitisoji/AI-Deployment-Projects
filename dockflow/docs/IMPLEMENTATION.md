# Dockflow implementation plan

Goal: a working synthetic inbound decision console with independently written rules and no private operational inputs.

Spec: [DESIGN.md](DESIGN.md). Interfaces are in `lib/dock-types.ts`; preserve them across engine and UI tasks. Product and technical defaults are fictional implementation choices.

## 1. Rules, fixtures and actions

- [x] Write Node behavior tests for classification, physical occupancy including held loads, combined destination/handling rules, crossdock isolation, missing/stale profiles, allocation conflicts, actions, parsing, time advancement, CSV safety and immutability.
- [x] Implement the exports in `lib/dock-engine.ts` and deterministic scenarios in `lib/dock-fixtures.ts`, following DESIGN.md exactly.
- [x] Run `node --experimental-strip-types --test tests/*.test.mjs`; review proposed assignments against constraints independently in tests.

## 2. Operator interface

- [x] Replace starter page/layout/styles with the inbound console using engine outputs, no duplicated scoring/feasibility logic.
- [x] Implement overview/queue/door/assumptions views, inspector, acceptance/completion/undo, synthetic scenario/clock/refresh controls, filters, editable capacities/door enablement/holds, JSON/CSV export and guarded JSON import.
- [x] Persist versioned synthetic state after hydration; invalid browser data recovers visibly. Never call external business services.

## 3. Integration and verification

- [x] Run engine tests, TypeScript and production build; fix meaningful failures.
- [x] Independently review rules, actions, persistence/export and misleading-claim risks.
- [x] Browser-check core operator flow and a phone-sized layout. Capture an actual screenshot.
- [x] Explain the model/rule engine, limits, data provenance and verification in README/learning notes. Original scripts and private reviews remain outside this directory.

## 4. Runnable delivery

- [x] Build and deploy the demo; verify successful deployment and anonymous HTTP access after enabling public access.
- [x] Prepare a portable source export with synthetic fixtures, setup instructions, tests and safe configuration.

The linked GitHub Actions workflow supplies reproducible installation, test, type-check and build results for each published change.

Review focus: source uncertainty must not become zero-as-success; a planning hold must not free a physical door; both eligibility dimensions remain hard constraints; a prior recommendation cannot authorize a newly conflicted action; import/export and saved state must preserve the synthetic provenance and safe values.
