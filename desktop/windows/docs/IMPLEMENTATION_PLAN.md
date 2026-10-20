# VMA Windows Desktop — Implementation Plan

## Phase 1 — Freeze behavior and requirements

1. Use the working release branch as the source of truth; record V1/V2 invariants and UI/API routes.
2. Create this separate desktop project and six design documents.
3. Keep all generated build outputs ignored by Git.

## Phase 2 — Backend executable

1. Add a desktop-only Python entry point with a dynamically assigned loopback socket, structured port handshake, and graceful stdin shutdown.
2. Build with PyInstaller in one-folder mode, including existing frontend and demo data at their expected paths.
3. Smoke test the frozen executable against health, ready, demo, and representative V1/V2 requests.

## Phase 3 — Desktop shell

1. Pin Electron and packager dependencies in this folder.
2. Spawn the backend executable, wait for readiness, and load the existing UI in a restricted window.
3. Block off-origin navigation, new windows, permissions, and renderer Node access.
4. Stop the child cleanly at window close and enforce single instance behavior.

## Phase 4 — Distribution and acceptance

1. Package Electron with the backend executable as an external runtime asset and create a ZIP.
2. Run parser/API tests, frozen-backend smoke tests, and desktop UI smoke tests.
3. Test on a clean Windows x64 machine offline, with no Python or Node installed.
4. Publish only after the clean-machine gate passes; add signing for broader distribution.

## Risk and fallback

- If PyInstaller omits runtime assets, fix the spec file and repeat the frozen-backend smoke test.
- If Electron cannot launch or decode a stream, inspect its actual window logs and test the original file in the current browser app. Keep V2 extraction available.
- If distribution signing is unavailable, deliver a clearly labeled unsigned ZIP for testing and defer public release.
