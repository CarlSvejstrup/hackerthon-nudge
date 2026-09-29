# 1. A Claude routine orchestrates, Jev classifies, code decides

Date: 2026-09-29. Status: accepted.

## Context

Nudge has to read many chats, decide which few deserve a nudge, and word each nudge so it feels human. Jev is fast, cheap and calibrated, but it cannot generate text and is weak at dates and arithmetic. Claude writes well but is slow and costly to run over every chat.

## Decision

- **Code** computes everything about time: sessions, rhythm, silence, who wrote last.
- **Jev** answers narrow yes/no questions about the last 10 messages of each candidate chat: needs a reply, promise, follow-up, heavy topic, aimed at Carl in a group.
- **Code** combines both into a score with weights in `nudge/decide.py` and decides act or not.
- **A local Claude routine** reads `nudge scan --json`, opens only the chats marked act through the WhatsApp MCP, words the nudge and sends it with `nudge push`.

The routine runs as a local scheduled task, not a cloud routine, because the WhatsApp bridge and its database live on the Mac. The WhatsApp MCP's send tools are denied in `.claude/settings.json`.

## Consequences

- Claude only reads the handful of chats that code and Jev already picked, which keeps it cheap and keeps most chat content away from any model.
- Every nudge can be explained by its flags, because the decision is code and not a prompt.
- If Jev is down, the hard flags still work and the routine falls back to them.
- The Mac must be on and the bridge running for anything to happen.

## Addendum: classify once, read many times

The routine is the only place that classifies. It reads full history only for chats with a new message since the last run, recomputes the time-based flags for the rest from a stored snapshot, and asks Jev only when a chat's last message changed. The result is written to the `contacts` table in `nudge.db`. Classification runs on demand too: every question to the Nudge MCP first runs the same incremental scan, so the answer is current and only new messages cost a Jev call. The routine runs once in the morning to classify and push, so Carl is nudged even on days he never asks.
