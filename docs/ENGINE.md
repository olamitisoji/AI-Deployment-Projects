# Conversation pathway engine

The application owns interview state and every transition. OpenAI returns a schema-checked analysis with a suggested action and evidence; it cannot consent, publish a study, skip a topic, change permissions, or declare completion. No Agents API, Agents SDK, tools, hosted conversations, or model-controlled state machine are used.

## Interfaces

`echo.conversation_pathway_engine` exports `StudyPathway`, `PathwayNode`, `Transition`, `Analysis`, `Evidence`, `InterviewState`, `Decision`, `default_pathway()`, `initial_state(pathway)`, `begin(pathway, state)`, `apply_response(pathway, state, answer, analysis)`, and `apply_command(pathway, state, command)`.

Functions return a `Decision` containing the new state and leave the input state unchanged. The caller persists the returned state and decision in its transaction. Consent is enforced by the caller before `begin`; this module never grants consent. `begin` is idempotent while a question is pending.

Decisions use `ASK_PRIMARY`, `PROBE_DEEPER`, `CLARIFY`, `ASK_FOR_EXAMPLE`, `MOVE_TO_NEXT_TOPIC`, `SKIP_TOPIC`, `PAUSE_INTERVIEW`, `COMPLETE_INTERVIEW`, and `REQUEST_HUMAN_SUPPORT`. `question` is nullable. `reason_code` and validated evidence explain the observable decision without hidden reasoning.

`echo.audio_transcription.AIClient` offers asynchronous `transcribe(audio, mime_type)`, `analyze(pathway, state, answer, history)`, and `propose_pathway(objective, questions)`. It accepts an injected `httpx.AsyncClient` for local HTTP contract tests; callers can share and close their own client. Without an injected client, each call owns and closes its HTTP client. `AIError.code` contains a stable sanitized error; provider bodies and credentials are never exposed. The adapter performs one request, including for quota errors. The orchestrator decides whether any retry is appropriate.

`echo.research_synthesis.synthesize_transcripts([{id, text}, ...])` produces extracts with source transcript IDs. Blank, unidentified and duplicate-ID records are omitted. It generates no themes, prevalence estimates, or invented quotes.

## Pathways and bounds

A pathway contains 1–12 nodes and 1–40 total answered turns. Each node has at most three followups, unique required-information labels, suggested probes, clarification/deeper-probe guidance, and optional conditional transitions. Unknown targets and cycles are rejected, including implicit sequential edges. `next_node: null` means the following node in list order (or end for the last item). An explicit matching transition with `target_node: null` ends the path. First matching conditional transition wins; an `always` transition is unconditional. Participant SKIP follows the ordinary next-node order.

The natural-language `clarification_conditions` and `deeper_probe_conditions` are model guidance. The engine does not independently evaluate their semantic truth. Its independent checks enforce action enums, evidence/coverage requirements, graph transitions and numeric budgets. Any deployment needing independently verifiable condition rules should encode and evaluate structured predicates rather than treating these prose lists as executable policy.

An answer covers a required criterion only when the analysis marks it covered, the criterion belongs to the current node, the response is relevant, and its nonempty supporting quote occurs in the current participant answer. This exact-substring check prevents fabricated quotes; it does not independently prove semantic entailment. Researcher review and evaluation remain necessary. Optional information never substitutes for required information. Coverage accumulates across answers as `unanswered`, `partial`, or `covered`.

Full required coverage advances regardless of a model request to continue probing. Incomplete information receives a bounded followup, then advances when its followup allowance is exhausted. Model suggestions cannot force advancement. Explicit pathway branch conditions are evaluated in code. The total turn ceiling stops further questions and requests human review, without claiming missing coverage. A fully covered final topic may complete on the final allowed turn.

Completion follows the configured rule: all topics must have been answered or explicitly skipped, or all required criteria must be covered. Exhausting a path without satisfying its rule requests human review. A branch that bypasses a required topic therefore does not silently claim the topic was visited.

## Adaptive questions and controls

Relevant responses can receive one natural model-proposed followup for the allowed `CLARIFY`, `PROBE_DEEPER`, or `ASK_FOR_EXAMPLE` suggestion. It must fit 400 characters, contain one question, avoid exact prior question repetition, and pass a limited lexical screen for obvious leading language, requests for secrets/identifiers, and rule overrides. If it fails, the engine uses a suggested study probe or a deterministic clarification of the approved primary question. These are transparent study fallbacks, not simulated AI responses.

The lexical screen is a narrow safeguard. It does not guarantee neutrality, detect all prompt injection, assess clinical risk, or establish topical relevance independently of model analysis. Evaluation should include adversarial instructions, off-topic responses, indirect leading questions, medical advice, ambiguity, colloquial speech, and subgroup language variation. No production clinical use is claimed.

Commands are standalone, case-insensitive `PAUSE`, `RESUME`, `SKIP`, `STOP`, `WITHDRAW`, and `HELP`. The service also handles `DECLINE` and tolerates terminal `.`, `!` and `?` punctuation. Text commands are parsed before AI. After consent, an active interview also recognizes a command spoken alone after transcription, before analysis; quoted or embedded commands are ordinary research data. Speech recognition can mishear a command, so text is the reliable channel. No voice processing occurs while paused or in human support; use text to RESUME or exercise other controls in those states. Pausing preserves the pending question. Resuming repeats it without consuming a turn or followup. STOP and WITHDRAW cannot be resumed. WITHDRAW remains available after completion or stop; the caller must perform the configured data deletion/retention workflow. HELP routes to human support; the engine does not claim a researcher has been contacted.

## Provider request contracts

Transcription uses a multipart WAV request to `/v1/audio/transcriptions`, default model `gpt-transcribe`, and JSON text output. Input must be an accepted media MIME type and no larger than 25 MiB; the WhatsApp gateway imposes a lower 16 MiB cap. WhatsApp OGG/Opus, AAC and AMR are decoded locally before upload because they are absent from OpenAI's documented file-input formats. Every accepted input is normalized to mono 16kHz PCM WAV, capped at five minutes/9.6 MB PCM. The bundled `imageio-ffmpeg` executable receives only stdin/stdout pipes with file and network protocols disabled, one decoding thread, and a 30-second timeout. Oversize output, corrupt audio, unavailable decoding and timeouts produce sanitized errors and terminate the process. No downloaded or normalized audio file is retained. Test fixtures verify a generated-tone OGG/Opus roundtrip locally; this is decoder verification, not speech recognition or a live-provider test.

The optional `transcribe(..., before_upload=callback)` permission check runs both before and after local decoding. The interview service passes a callback that rereads opt-out and active-interview state, preventing an upload if a stop arrives during decoding. Results are checked again after the provider returns. An upload already in flight when opt-out arrives cannot be retracted.

Analysis and pathway drafting call `/v1/responses` with `store: false` and `text.format: {type: "json_schema", strict: true, ...}`. All schema object properties are required with `additionalProperties: false`; optional values use nullable types. Model output is validated again locally, including graph semantics. Refusals, incomplete responses, malformed JSON, prohibited actions, invalid graphs, network failures and quota errors become typed failures. A missing live credential is never replaced by pretend AI output. The default decision model is configurable and currently `gpt-4.1-mini`.

`store: false` controls response storage for Responses; it is not a promise of zero provider retention. Apply the deployment's contractual data and retention policies before processing participant material. The application should bound and minimize transcript history sent to the model; this adapter sends at most the most recent 12 history entries.

## Durable interview service

`echo.interview_service.process_event(event_id, settings, session_factory, vault, ai, gateway)` consumes a queued/processing encrypted inbox event and commits its resulting state, answer turn, outbox reply and final event status together. External media/transcription/analysis calls occur outside database transactions. Current opt-out, expiry and state are checked before persisting provider results. A sequential worker is required; this service does not provide independent multi-worker leader election.

START tokens are looked up by SHA-256 hash and checked against study approval, expiry, revocation, use limits and personalized-recipient binding. The first accepted invitation freezes a validated encrypted pathway snapshot. Repeated starts reuse an existing interview and do not consume another invitation use. A participant's active interview is continued before starting another study.

Consent version `2026-11-10-v2` records `status`, ISO timestamp `at`, and booleans for participation, recording, transcription and data use. Only exact I CONSENT grants all four scopes. The consent message discloses AI processing, the four scopes, retention, support and participant controls. No voice download or AI analysis occurs before consent. The default retention applies to Echo's stored records, separately from provider retention.

STOP/DECLINE opt out immediately; WITHDRAW additionally deletes all participant answer turns and scrubs stored inbound payloads, interview state, consent and prior outbox content, cancelling pending sends. The approved study pathway contains study configuration and is retained. Withdrawal leaves encrypted empty dictionaries for state/consent, so researcher views must display the withdrawn status without trying to reconstruct an active engine state. One control acknowledgement can be enqueued despite opt-out when the terminal status changes. Echo cannot erase copies already delivered through WhatsApp or independently retained by providers; the privacy notice and provider agreements must explain those boundaries.

Media/transcription failure saves a typed durable error and asks for text or support, without inventing a transcript or consuming an answer turn. If analysis fails after a real answer/transcript was obtained, that evidence is preserved in a turn and the interview enters human support. Provider errors are not automatically retried by the service. Human-support interviews accept STOP/WITHDRAW and no longer download or analyze new voice answers. Stale provider results never overwrite a newer interview state.

Each turn receives an increasing per-interview `sequence`, including preserved answers on analysis failure. History and researcher transcripts use that sequence so replies in the same second remain ordered. This added column requires a schema migration for any previously created database; `create_all` only initializes fresh tables. Existing legacy turns require an explicitly reviewed ordering backfill because second-resolution timestamps alone cannot reconstruct ties.

Official request references verified 2026-11-10: [Structured outputs](https://developers.openai.com/api/docs/guides/structured-outputs?api-mode=responses) and [File transcription](https://developers.openai.com/api/docs/guides/speech-to-text).

## Verification

From the project directory: `PYTHONPATH=backend .venv/bin/pytest`.

Tests exercise quote substantiation, coverage accumulation and transition authority, graph validation, commands, terminal states, pause/resume, skips, conditional branches, total and per-node ceilings, repeated and unsafe followups, strict nonstored Responses payloads, real multipart encoding, refusals, invalid outputs, quota/no-retry behavior, network failures, and evidence-linked extracts. HTTP tests use `httpx.MockTransport` with fake credentials; no real API request is needed. Live transcription and model quality remain deployment checks when account quota is available.
