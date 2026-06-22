# Project Continuity

## Current Project Phase
Phase 1: Initial Provisioning and Infrastructure Setup.

## Recent Decisions
- Assigned host port 3006 to the Docker container.
- Configured Next.js to use `PORT=3006` internally to match the host port mapping.
- Established GitHub Actions CD pipeline for automated deployment to Schubert Nexus.

## Open Tasks
- Implement Next.js frontend and Pipecat voice framework integration.
- Configure Deepgram STT and ElevenLabs TTS.
- Connect to LiteLLM proxy for Qwen 3.5 and WRITER Palmyra routing.

## Known Issues
- None at this time.

## Session Startup Instructions
1. Read `AGENTS.md` and `CHANGELOG.md`.
2. Check the live URL at `https://project-tango.schubert.life`.
3. Review this `CONTINUITY.md` file for the latest context.
