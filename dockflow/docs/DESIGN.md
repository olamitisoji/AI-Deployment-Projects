# Dockflow — first independent prototype

Build an interactive inbound operations console with fictional facilities, carriers, trailers, destination mixes and policies. The goal is to demonstrate the decision loop: prioritize work, understand destination demand, inspect compatible available doors, and let an operator approve a simulated assignment. This is newly written code, not a copy or deployment of an employer tool.

## Scope and implementation choices

The first slice combines deadline priority, destination demand, advisory plans, compatibility exceptions and door recommendations in one operator workflow. Manual approval, history and undo are simulated capabilities. All policies, facility details and load records are invented for this independent demo.

React renders the console using the Sites/Vinext starter. Pure TypeScript functions run in the browser and Node tests; no model API, live systems or database is required. Only synthetic simulation state persists in browser storage. The demo is publicly hosted and this source folder is portable for local development.

Staffing, live integrations, time-slot optimization, real operational data and measured business outcomes are outside this slice.

## Fictional rules, chosen for this demo

- Three zones A/B/C, six ordinary doors plus one dedicated transfer door, and twelve seeded trailers. Handling categories: palletized, cart, loose, crossdock. States: expected, yard, at door, complete. Presets: balanced, surge, disruption.
- Simulated minutes on a single fictional day, 0–1440. No calendar/time-zone claims. Default clock 10:00, current deadline 12:00, next deadline 16:00. Advance 30 minutes at a time; expected trailers whose arrival passes become yard trailers. Deadlines stay fixed and missed work becomes overdue.
- High: unfinished trailer with current-deadline packages; medium: no current packages but next-deadline packages; low: other unfinished positive volume. Complete/empty loads have no priority. Priority order then current packages descending, arrival, stable ID; arrival baseline sorts arrival then ID. Expected trailers are visible but never proposed before arrival. Holds block recommendations, not occupancy or physical volume.
- Known profile zone units must equal package count; current+next packages cannot exceed package count. Unknown profile has no zone allocation, remains visible in total volume, and is reported as unmapped. Profiles older than 60 simulated minutes block new assignments. Future profile timestamps are invalid.
- Ordinary door eligibility requires BOTH handling compatibility and a dominant destination zone (ties permit tied zones). Crossdock uses only a dedicated transfer door with null zone and crossdock handling; it does not fall back to ordinary doors. Disabled or physically occupied doors are never feasible. Every at-door record reserves its location, including held, stale and wrong-door loads. Duplicate occupancy is a critical warning and still blocks that door.
- Rank feasible doors by destination match descending, projected zone pressure ascending, then stable door ID. Pressure is a synthetic workload proxy: packages already on ordinary doors in the zone + prior proposed packages + this trailer's full package count, divided by that zone's configured capacity. Transfer pressure and destination-match percentage are null, displayed as not applicable rather than an invented 100% match. Zone capacities must be positive integers. It is not a predicted processing rate or optimality claim.
- Allocate primary proposals sequentially in the selected queue order, at most one per door. Alternates must not conflict with any final primary proposal. A null primary always includes a specific reason. Never substitute occupied 'ideal' doors for feasible assignments.
- Candidate explanations disclose compatibility, destination match and workload proxy. The operator can accept a primary or choose an eligible alternative. Every action rechecks current scenario feasibility; recommendations alone never change state. Accepted assignments/mark-unloaded actions return a new scenario and audit event. Undo restores the prior entire state.
- Current planned doors are advisory references only. Warn about wrong handling/destination, duplicate physical locations, missing/stale profiles and compatible priority inversions; never imply an infeasible swap is safe.

## Interface contract

Types live in `lib/dock-types.ts`. `lib/dock-engine.ts` exports:

```ts
evaluate(scenario: Scenario, mode?: PlanMode): Evaluation
feasibleDoors(scenario: Scenario, trailerId: string): DoorCandidate[]
applyAssignment(scenario: Scenario, trailerId: string, doorId: string, reason?: string): ActionResult
completeTrailer(scenario: Scenario, trailerId: string): ActionResult
advanceClock(scenario: Scenario, minutes?: number): Scenario
refreshSyntheticProfiles(scenario: Scenario): Scenario
parseScenario(input: unknown): ParseResult
exportScenarioCsv(scenario: Scenario, evaluation: Evaluation): string
```

`lib/dock-fixtures.ts` exports `createScenario(preset?: Preset, seed?: number): Scenario`. All algorithms/actions are deterministic and do not mutate input. Invalid actions throw a readable Error. Parsing returns errors instead of throwing and constructs only known validated fields. Limit input to 100 trailers, 30 doors, fixed three zones, IDs 1–40 safe alphanumeric/hyphen/underscore characters, names 1–80 characters, integer counts 0–1,000,000, seed 0–2^32−1. Prototype constructor and schema controls must not enable object-key/prototype injection; IDs such as __proto__/constructor/prototype must be rejected or safely represented. Do not use inherited object properties for lookups.

## UI and evidence

Polished desktop console, responsive mobile navigation. Persistent 'Synthetic data' label and fictional facility name. Overview: count cards, zone pressure heatmap, occupied/available door map, exceptions. Queue: sortable/filterable trailer rows, priority reasons, deadline volumes, handling and state. Detail panel: destination mix, data freshness, preassignment vs recommendation, explanations, alternate door selection, approve/complete actions. Compare arrival/priority planning on identical state without claiming one always wins. Settings expose fictional zone capacities, door enablement and trailer holds; edits recalculate views immediately. Scenarios, advance clock, refresh fictional profiles, reset/undo, audit log, JSON/CSV export work. Synthetic-only JSON import validates size/schema and reports errors without replacing current state on failure.

Metrics always name their population. Active/total units exclude completed loads; holds remain physical work. Heatmap splits known-profile units by state and identifies unmapped volume separately. Available door count reflects enabled and physically empty doors. Urgent count includes unfinished current-deadline work but show yard count separately. Blocked count covers waiting yard trailers with no proposal, including held/unknown/stale/empty. Do not display fabricated productivity percentages or causal gains.

Verification: tests for classification boundaries, holds reserving occupancy, combined zone/type constraints, dedicated crossdock, stale/missing data, duplicate location, deterministic reservations/alternates, stale conflicting operator actions, validation, zero-work cases, clock arrivals, immutable undo inputs and safe CSV quoting. Browser verify scenario changes, alternate mode, apply/undo, blocked feedback, filters, editing, exports/import validation and mobile layout. Record actual evidence and limits in README.

## Review resolutions

Ordinary doors must have a zone and only ordinary handling categories; transfer doors must have null zone and only crossdock handling. A known profile requires a timestamp no later than the current clock and exact package-count conservation; unknown profiles require zero zone counts and a null timestamp. Exactly 60 minutes old remains fresh. Refresh only timestamps known synthetic profiles; it cannot infer an unknown profile.

Overdue means strictly past the applicable deadline with positive unfinished current OR next-window packages. At the deadline minute, work is due now. Clock advancement stops at 1440. Completed and empty trailers have no priority. Heatmap held volume is an overlapping subset already included in totals.

Every at-door record must reference a known door; every other state has null physical door. Duplicate, incompatible and disabled-but-occupied locations remain physical exceptions and reserve capacity. Completing a trailer records its original door and leaves any other conflicting occupant in place. Planned doors never reserve capacity.
