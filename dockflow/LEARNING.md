# Understanding Dockflow

This is a small operations simulator. All facilities, loads, carriers, quantities and policies are fictional. It sends no assignments to a warehouse or transport system.

## 1. A data model describes what the app knows

`lib/dock-types.ts` defines the shape of a trailer, dock door, zone and scenario. TypeScript checks whether the rest of the code uses those shapes consistently. For example, a trailer has a lifecycle state, package counts, a handling category and an optional physical door.

Types alone do not protect data loaded from a file or browser storage. `parseScenario` checks those values at runtime, rejects invalid combinations, and keeps the existing working state when an import fails.

## 2. Priority and feasibility answer different questions

Priority asks which work deserves attention first. This demo uses documented rules: current-deadline work, then next-deadline work, then other work. These are fictional policy choices, not a learned model or the original operation's thresholds.

Feasibility asks whether a specific trailer can use a specific door now. It checks physical occupancy, door enablement, handling support, destination zone, arrival, holds and profile freshness. High priority never bypasses those checks.

## 3. Pure functions make decisions testable

`evaluate(scenario, mode)` takes one scenario and returns a queue, demand view, warnings and proposals. It does not change the scenario or contact another system. Given identical inputs, it produces identical outputs.

`applyAssignment` rechecks an operator's chosen door and returns a new scenario plus an audit event. The previous state remains intact, which makes undo possible and lets tests check before/after behavior precisely.

## 4. A recommendation is not a reservation

The planner chooses primary proposals in queue order and avoids recommending the same door twice in that plan. It makes no operational change until the operator accepts a proposal. Acceptance rechecks the current state because a proposal may have become invalid after another action.

This is a greedy rule-based method: it makes one local choice at a time. It does not prove the best possible overall plan. Switching queue order illustrates tradeoffs rather than guaranteeing improvement.

## 5. The interface is another view of the same state

React renders the queue, map, metrics and inspector from one scenario and evaluation. Changing a hold, door availability or capacity updates the same underlying state. The interface does not maintain a separate hidden copy of the business rules.

The simulator saves its synthetic state in this browser. That is not a shared database, a server audit trail or multi-user collaboration. Exports provide a portable snapshot. Reset restores generated example data. Undo retains up to 30 previous snapshots during the current page session; reloading keeps the scenario and action history, but clears the undo stack. The plan-order control is a viewing choice and resets to deadline priority after a reload.

## 6. Tests check decisions, not business impact

Automated tests can prove that an occupied door is not proposed, a bad import is rejected, or a repeated seed reproduces a scenario. They cannot prove warehouse adoption, time savings, accuracy against a real operation, or a financial outcome. Those would require separate evidence.

Try this walkthrough: load Balanced → choose a waiting high-priority trailer → read its recommendation → accept it → observe door occupancy and the audit event → undo → disable that door → inspect the revised result. Then load Disruption and inspect how unknown or stale information changes what the app is willing to recommend.
