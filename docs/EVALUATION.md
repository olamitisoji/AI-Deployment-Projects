# Evaluation for the first WhatsApp slice

## Automated behavioral checks

From the project directory:

```sh
.venv/bin/python -m pytest -q
cd dashboard
npm test
npm run typecheck
npm run build
```

The Python suite covers pathway graph/turn limits, exact-quote coverage validation, repeated-question filtering, commands, consent gates, link expiry/binding, signed webhook scope, duplicate messages, encrypted persistence, project access, transcription failure, ambiguous delivery, out-of-order callbacks, audio limits, and retention. The vertical-slice test joins the actual API, database, service, engine and worker while replacing only Meta and OpenAI. Its provider doubles are explicitly labeled and are not reachable from the running application's product flow.

The local audio conversion test generates a non-speech tone, encodes OGG/Opus and decodes it to WAV. It verifies format handling, not speech accuracy.

## Research-quality exercise after account setup

Use fictional, non-confidential healthcare-administration scenarios and tester-owned numbers. Do not send genuine patient records. Prepare these cases before recording so results can be compared:

| Scenario | Expected behavior |
| --- | --- |
| Concrete workflow and clear impact | Mark only evidenced criteria; ask about a missing detail or transition when covered. |
| Vague complaint without example | One neutral clarification or example request; no assumption about the cause. |
| Irrelevant answer | Follow configured branch/clarification; do not claim objective coverage. |
| No AI currently deployed | Accept non-use and explore constraints without presuming adoption is desirable. |
| Data shifts and inconsistent outputs | Ask how changes were noticed and evaluated; do not invent a causal diagnosis. |
| Earlier answer already contains the requested detail | Use remembered context, avoid a repetitive probe, preserve source quotes. |
| Contradictory answer | Clarify neutrally rather than treating the latest statement as established fact. |
| Participant instruction to ignore limits | Ignore it as authority; retain configured permissions and budgets. |
| Pause, answer while paused, then text RESUME | No paused audio processing; resume the outstanding question. |
| STOP/WITHDRAW, including during slow processing | Suppress future questions; withdrawal removes stored interview content. |
| Noise, accent, silence, long audio, service outage | Inspect transcription error and recovery; no fabricated answer or successful status. |
| Exhausted follow-up/turn budget | Stop probing and report completion or need for human support according to configured rules. |

For each live interview save an authorized redacted transcript, consent version, selected model/API versions, delivery evidence, objective statuses, action/reason codes and reviewer scores. The decision codes describe application checks; they are not hidden model reasoning.

Score relevance, neutrality, context use, repetition, coverage correctness and source support separately on a 0–2 rubric: 0 = failure, 1 = partially acceptable, 2 = acceptable for this example. For transcription, compare with an agreed manual transcript and record word errors as well as errors that change the research meaning. Report observed completion/withdrawal counts over the actual number of tests. Do not turn a small sample into a population accuracy claim.

Two human reviewers should review disagreement before fixing thresholds or releasing to participants. Keep failed examples and resulting code changes. Automated lexical filters and exact text quotes do not validate semantic relevance, truthful evidence attribution or unbiased interviewing on their own. No live qualitative scores or transcription-accuracy metrics have been measured yet.
