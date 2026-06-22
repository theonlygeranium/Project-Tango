# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Fixed
- CI/CD pipeline: removed sudo from git pull in deploy.yml (git 2.35.2+ cross-owner rejection)
- CI/CD pipeline: replaced docker compose with systemd restarts in deploy.sh
- CI/CD pipeline: use venv pip instead of system pip (PEP 668 blocks system pip on Python 3.14)
- CI/CD pipeline: fixed root-owned scripts/ dir breaking git pull as z121532
- Backend: fixed streaming_latency kwarg in ElevenLabs TTS constructor

## [0.1.0] - 2026-06-22
### Added
- Initial project scaffolding provisioned by WRITER Agent via Schubert Project Provisioning playbook.
- Foundation files: README, CHANGELOG, AGENTS.md, CONTINUITY.md.
- Docker configuration and GitHub Actions CD pipeline.
- Confluence knowledge base pages created and linked in AGENTS.md.
