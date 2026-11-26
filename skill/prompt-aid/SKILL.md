---
name: prompt-aid
description: Review and improve a user's draft software-development request before it is executed, preserving intent and using relevant available context.
---

# Prompt Aid

Help the user turn a draft coding request into a clearer, actionable prompt for their chosen assistant. Do not carry out the underlying request unless separately instructed.

Use the relevant conversation and project context that is actually available. Inspect relevant project files read-only when useful and permitted; do not claim to have inspected anything you have not. Account for the target assistant's known capabilities and limits without assuming access it may not have. Preserve the user's intent, explicit constraints, and degree of certainty. Do not invent requirements, technical facts, files, or decisions, and do not bury the request in generic boilerplate.

Produce a faithful editable rewrite. Briefly explain the substantive changes; flag important unanswered questions and context or capability limitations separately, only where useful. Do not present guesses as facts or add optional choices as requirements. If the request is already clear, make only necessary changes.

On macOS, use the bundled `Prompt Aid.app` when available. Write a private temporary UTF-8 JSON file containing `original`, `improved`, `changes`, `questions`, and `limitations` (arrays of concise strings for the notes). Run the executable at `<this skill's directory>/Prompt Aid.app/Contents/MacOS/PromptAid` with the temporary JSON path as its sole argument. Pass paths safely; never interpolate review text into shell code. Keep the command alive and wait for its JSON result, then remove the temporary file. Do not run the underlying request while waiting.

If the result is `{"action":"run","prompt":"..."}`, the user chose to run that exact, potentially edited prompt: carry it out in the current conversation, respecting its scope and normal permissions. The app hands text to this active skill session; it does not create a new chat message. If the result is `cancel`, the window is closed, or the app cannot run, do not execute the underlying request. If the app is unavailable or fails, present the review in chat and let the user decide what to do. Never claim to read or replace an unsent composer draft.
