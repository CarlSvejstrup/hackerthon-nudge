# Future work

Things we decided not to build in the hackathon, and why. Newest decision last.

## Product

- **Morning routine.** A daily local scheduled task that classifies and pushes up to 5 nudges, following `ROUTINE.md`. Built and removed again for the hackathon: the demo is on-demand through the Nudge MCP. Decided 2026-09-29.
- **Chat bot as the surface instead of push.** A Telegram or WhatsApp bot that sends the nudge and lets you answer it ("snooze", "done", "draft a reply"). Push via ntfy is one-way. Decided 2026-09-29.
- **Reply drafts.** Claude drafts a reply in Carl's voice from the last 20 to 30 messages. Carl always copies and sends himself; nothing is sent automatically. Decided 2026-09-29.
- **Reply from WhatsApp directly.** Send the approved draft through the bridge, behind an explicit yes per message. The send tools are blocked in the MVP. Decided 2026-09-29.
- **Birthdays as a hard flag.** Needs a mapping from WhatsApp contact to the people notes in the vault, which have no phone numbers today.
- **Tier from the people notes to override rhythm.** Tier is empty on 67 of 68 people notes, so rhythm is learned from history only.
- **Notes into the vault.** Notes live in `nudge.db` today. Sync them to the people notes in the vault so they are useful outside Nudge.
- **Nudge status from the phone.** The `nudges` table has a `status` column (sent, done, snoozed) that only a two-way surface like a bot can fill.
- **Group mentions.** Use real @-mentions from WhatsApp instead of asking Jev whether a group message is aimed at Carl.

## Model and data

- **Tune thresholds on real data.** `YES = 0.7` and `ACT_AT = 0.6` in `nudge/decide.py` are guesses. Plot Jev's nouls against Carl's own "yes, that was worth a nudge" and set them from that.
- **Test Jev on Danish.** Jev is weaker on Danish than English. The hackathon tests were on made-up Danish chats only.
- **Data agreement with TypeSafe.** No data processing agreement and no zero retention today, and the last 10 messages of each candidate chat go to them. Needed before anyone but Carl uses it.
- **Promises beyond the last 10 messages.** Jev only sees the tail of a chat, so a promise followed by 10 unrelated messages is missed. Scan the whole chat for Carl's own promises and keep them as open items until a later message closes them.
- **Media and voice notes.** Only text is read today.
- **GDPR before other users.** For Carl alone it is personal use and GDPR does not apply. As a product, the company processes messages from the users' friends, who never agreed to it, and the heavy-topic flag can infer health, which is special-category data. Needs a legal basis, data processing agreements with every subprocessor, a lawful transfer to the US, and probably heavy-topic dropped or kept on the device. Get legal advice before launch.

## Platform

- **Official data source.** The bridge uses the unofficial WhatsApp Web protocol, which breaks WhatsApp's terms and can get a number banned. A product for others needs a different source.
- **Full history on linking.** The phone only sent one message per chat and reported that sync could not complete, even with full sync requested. We work around it with `/api/backfill` in the bridge, which asks for 50 older messages per chat per call. Find out why the full sync fails, or backfill on a schedule.
- **Run without the Mac.** The routine and the bridge both run locally. A hosted version needs the bridge on a server and a cloud routine.
