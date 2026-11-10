# Dockflow

## Inbound operations decision support

[Try the public demo](https://dockflow-inbound-lab-olami-1110.boileditem.chatgpt.site) · [View the source](https://github.com/olamitisoji/AI-Deployment-Projects/tree/main/dockflow) · [View automated checks](https://github.com/olamitisoji/AI-Deployment-Projects/actions/workflows/dockflow.yml)

**Status:** Public, interactive portfolio simulator. All operational data and policies are fictional.

### The problem

Choosing the next trailer to unload requires more than a priority list. A load may be urgent while its compatible door is occupied, its destination profile is outdated, or its handling requirements rule out the available doors. An operator needs to see urgency, physical constraints, and missing information together before acting.

### My contribution

I used my operational workflow experience to define an independent demonstration of this decision process. I directed the product requirements and worked with AI coding assistance to build, test, and publish the simulator while developing my technical skills. Dockflow uses newly written code and synthetic scenarios; the original workplace tools and any historical outcomes are separate from this portfolio project.

### What the product does

Dockflow brings a deadline-based queue, destination-demand heatmap, door plan, and exception list into one workspace. A researcher or hiring manager can load a repeatable scenario, select a waiting trailer, and inspect a proposed door or the reason no proposal is available. The operator accepts a simulated assignment or chooses another eligible door with a required explanation. Local history, completion, undo, and JSON or CSV export make the decision sequence reviewable.

### Decisions that shaped the implementation

The recommendation engine uses explicit TypeScript rules. This makes a proposed assignment traceable to the constraints that permitted it. Deadline priority changes the order of consideration; it never overrides physical occupancy, handling compatibility, destination compatibility, or data freshness.

A held trailer still occupies its door. An unknown destination profile stays unknown rather than being filled in by a refresh. Accepting a recommendation checks the current state again, because a previously feasible action can become invalid after another change. Recommendations themselves do not move trailers.

The first release runs in the browser with three reproducible scenario presets. This keeps the demonstration accessible without warehouse credentials or infrastructure and lets reviewers compare arrival order with deadline priority on the same synthetic state. Browser storage preserves a visitor's work, but does not provide a shared operational database.

### Evidence and limits

The published verification record documents 24 passing behavioral tests, a successful type check and production build, and browser checks covering assignments, manual choices, persistence, completion, undo, invalid imports, and mobile layout. The public deployment was also checked without sign-in.

This demonstrates a working decision-support loop. It does not establish warehouse productivity gains: the planner is greedy, the capacity ratios are synthetic, and there are no live feeds or dispatch commands. A next validation step would be a scenario-based usability session measuring whether operators can explain a recommendation, recognize a blocked load, and recover from an incorrect choice.

### Three minute demo

1. Open the demo and identify the synthetic-data label. Explain that the queue and heatmap describe the same fictional facility.
2. Select a waiting trailer. Read its priority, profile age, destination mix, and proposed door or blocking reason.
3. Change **Plan order** between **Deadline priority** and **Arrival order**. Explain that the order changes while the eligibility rules stay fixed.
4. Select an eligible proposal and click **Accept simulated assignment**. Show the resulting physical occupancy, then open **Rules & scenarios** to inspect the local action history.
5. Use **Undo** to restore the preceding state. Finish by explaining the boundary: this demonstrates advisory decisions with human review, not a connection to a live warehouse.

### Technical documentation

- [Design decisions](../dockflow/docs/DESIGN.md)
- [Verification record](../dockflow/docs/VERIFICATION.md)
- [Setup and learning guide](../dockflow/README.md)

[Back to portfolio](README.md)
