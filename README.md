# Nudge

Nudge reads your own WhatsApp chats and tells you who you should reply to, follow up with or reach out to, before a friendship quietly drifts.

It runs locally on your Mac. A small classifier ([Jev](https://docs.typesafe.ai/)) judges each chat once per new message, plain code turns that into a priority score, and you ask Claude "who should I write to?" through an MCP server. Nudge never sends a WhatsApp message.

Built in 2.5 hours at a hackathon.

## How it works

```
WhatsApp bridge ──> messages.db ──> nudge scan ──> nudge.db ──> Nudge MCP ──> Claude
 (local, read-only)                  │                              "who should I write to?"
                                     ├─ code: rhythm, silence, who wrote last
                                     ├─ Jev: yes/no questions on the last 10 messages
                                     └─ code: weighted score, your own statuses
```

1. **Read.** The bridge (whatsmeow, via [lharries/whatsapp-mcp](https://github.com/lharries/whatsapp-mcp)) syncs your chats into a local SQLite database.
2. **Find what is new.** Only chats with a new last message are read in full. For the rest, silence and rhythm are recomputed from the stored snapshot.
3. **Classify.** Jev is asked once per new last message: six calibrated yes/no questions, plus one in groups. Cached answers are reused, so asking again without new messages costs nothing.
4. **Prioritise.** Code turns flags into one score and applies your own statuses (done, snoozed, muted, flagged).
5. **Answer.** Claude reads the stored result through the Nudge MCP and explains who to reach out to and why.

### Flags

Five flags add points (Jev's probability × weight):

| Flag | Decided by | Weight |
|---|---|---|
| Unanswered: they wrote last and expect a reply | Jev + code | 1.0 |
| Promise: you said you would do something | Jev | 0.8 |
| Open plan: a plan that was never settled | Jev | 0.8 |
| Broken rhythm: quiet for longer than normal for you two | code | 0.7 |
| Follow-up: something in their life worth asking about | Jev | 0.6 |

Three adjust the score:

- **Forgotten** (code): unanswered, promise and open plan grow up to ×1.5 as they age.
- **Personal** (Jev): ×0 to 1, so shops, hotels and bots fade out.
- **Heavy topic** (Jev): ×1.5.

A contact gets a nudge at a score of 0.6 or more with at least one real flag. The vocabulary is defined in [CONTEXT.md](CONTEXT.md), and the design decision in [docs/adr/0001](docs/adr/0001-claude-routine-with-jev-as-classifier.md).

## Setup

Requirements: macOS, Python 3.11+, [uv](https://docs.astral.sh/uv/), Go, a Jev API key from [TypeSafe](https://console.typesafe.ai), and optionally the [ntfy](https://ntfy.sh) app for push.

```bash
git clone https://github.com/CarlSvejstrup/hackerthon-nudge.git
cd hackerthon-nudge
cp .env.example .env        # add JEV_API_KEY and NTFY_TOPIC
uv sync
```

Build and start the WhatsApp bridge, then scan the QR code with WhatsApp on your phone (Settings, Linked devices, Link a device). Keep it running.

```bash
cd vendor/whatsapp-mcp/whatsapp-bridge
go build -o bridge .
./bridge
```

The first sync only brings a little history. The bridge has a `/api/backfill` endpoint that asks the phone for 50 older messages per chat.

## Usage

```bash
uv run python -m nudge scan -v          # classify new messages and rank contacts
uv run python -m nudge scan --push      # also push nudges to your phone via ntfy
uv run python -m nudge scan --no-jev    # time-based flags only, nothing leaves the machine
uv run python -m nudge search hytten    # search all chats
uv run python -m nudge status Sofie done              # done, snoozed, muted, flagged, open
uv run python -m nudge status Mads snoozed --until 2026-10-03
uv run python -m nudge log              # recent runs and nudges
```

### With Claude

`.mcp.json` registers two MCP servers for Claude Code in this folder:

- **nudge**: `who_to_reach_out_to`, `explain_contact`, `demo`, `show_pipeline`, `set_thread_status`, `list_thread_statuses`, `nudge_history`, `notes_about`, `search_chats`.
- **whatsapp**: read tools from lharries/whatsapp-mcp. The send tools are denied in `.claude/settings.json`.

Open Claude Code in this folder and ask "who should I write to?". The `/nudge-demo` skill runs the stage demo.

## Data and privacy

- Two databases: the bridge's `messages.db` (read only) and `nudge.db`, which holds Jev's answers, the classified snapshot, your statuses, notes and sent nudges. Both are git-ignored.
- Only the last 10 text messages of a candidate chat are sent to Jev. No images or audio.
- Nudge cannot send WhatsApp messages. Push goes only to your own ntfy topic.
- For purely personal use, GDPR does not apply (article 2(2)(c)). As a product for others, GDPR and WhatsApp's terms need solving first: the bridge is an unofficial WhatsApp client, and your friends never agreed to their messages being processed. See [FUTURE-WORK.md](FUTURE-WORK.md).

## Cost

Measured: a Jev call on 10 messages is about 1,000 input tokens, or $0.00004. At 100 chats with new messages and 10 questions a day, Nudge with Jev + Claude Haiku costs about $0.85 a month, against about $9.60 if Haiku did the classification too. The Haiku figures are estimates.

## Repository

| Path | What |
|---|---|
| `nudge/` | The scanner, scoring, Jev client, store and MCP server |
| `vendor/whatsapp-mcp/` | lharries/whatsapp-mcp (MIT), patched for the current whatsmeow API and with a backfill endpoint |
| `presentation/` | The hackathon deck. `nudge.html` opens in any browser |
| `ROUTINE.md` | Instructions for a scheduled Claude routine that pushes nudges (not active) |
| `CONTEXT.md`, `docs/adr/` | Glossary and design decisions |
| `FUTURE-WORK.md` | What was left out, and why |
