# Echo

## Research interviews through WhatsApp

**Role:** Product direction, research workflow design, and AI-assisted prototyping  
**Stack:** Python, FastAPI, Next.js, TypeScript, PostgreSQL, Meta WhatsApp Cloud API, OpenAI  
**Status:** Implemented prototype with public source. A real WhatsApp voice interview has not yet been verified.  
**Explore:** [Source and setup](https://github.com/olamitisoji/AI-Deployment-Projects#echo) · [Verification record](https://github.com/olamitisoji/AI-Deployment-Projects/blob/main/docs/VERIFICATION.md)

### The problem

My team’s exploration of specialized AI models for healthcare administration involved discovery conversations with healthcare professionals, executives, researchers, and technical decision makers. We wanted to understand operational problems and the reliability limits of existing AI before choosing a product opportunity. Echo grew from a question about that research process: could participants answer in their own time through WhatsApp voice notes while still receiving thoughtful follow-up questions?

### My contribution

I defined the research context, WhatsApp-first participant journey, and requirements for conversational pathways, consent, participant controls, and inspectable interview decisions. Working with AI coding assistance while learning software development, I translated that direction into a backend and researcher workspace. My focus was connecting the research objective to explicit application behavior and making the boundary between a tested prototype and a participant-ready service clear.

### How it works

A researcher edits and approves an interview pathway, then generates an invitation link. The intended participant flow opens WhatsApp, explains AI use, collects consent, asks a primary question, and accepts text or voice answers. The backend retrieves audio, normalizes its format, transcribes it, and requests structured analysis. The application validates the next action, saves the answer and state, and queues the next question.

The central design choice is that the model proposes analysis; application code controls permission, progression, and limits. Required information accumulates with supporting transcript quotes. Follow-up budgets prevent endless probing. Persistent records preserve progress across messages and restarts. Pause, stop, withdrawal, and support requests take precedence over ordinary questioning. Duplicate detection and a durable message queue address delivery failures without assuming that a retry is harmless.

### Evidence and current outcome

The recorded verification includes 132 backend tests, 10 dashboard gateway tests, TypeScript validation, a production build, and a cloud PostgreSQL connection with restricted runtime access. The joined offline test covers consent, audio processing boundaries, follow-up decisions, completion, transcript retrieval after restart, and withdrawal. Meta and OpenAI are replaced by test doubles in those checks; the results demonstrate application behavior, not live delivery or interview quality.

### The next validation

The next milestone is one consented test interview using a real WhatsApp voice note and real transcription, followed by human review of relevance, neutrality, and coverage. Account configuration, API quota, a public webhook, and platform eligibility remain unresolved in the recorded setup. No participant recruitment, research findings, or commercial launch is claimed.

### Technical documentation

- [Conversation rules](../docs/ENGINE.md)
- [Research evaluation plan](../docs/EVALUATION.md)
- [Verification and remaining checks](../docs/VERIFICATION.md)

[Back to portfolio](README.md)
