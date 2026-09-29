# Nudge

Nudge reads your own WhatsApp chats and nudges you to reach out, reply or follow up before a relationship quietly drifts.

## Language

**Nudge**:
A push notification telling you that one contact is worth reaching out to now, with the reason.
_Avoid_: Alert, reminder, notification

**Contact**:
One WhatsApp chat, either a person or a group, treated as one relationship.
_Avoid_: Chat, conversation, thread

**Rhythm**:
How often you and a contact normally talk, learned from your own history with them. Never shown as a number to the user.
_Avoid_: Cadence, frequency, interval

**Close contact**:
A contact you have talked with often enough in the past for a broken rhythm to mean something.
_Avoid_: Friend, tier 1

**Session**:
A burst of messages with a contact without a long pause. Rhythm is measured between sessions, not between messages.
_Avoid_: Conversation

**Note**:
One lasting fact about a contact's life, learned from the chat and kept so later nudges can refer to it.
_Avoid_: Memory, profile, context

**Run**:
One pass of the routine over all contacts, logged with how many Jev calls it cost.
_Avoid_: Job, scan

### Thread status

**Status**:
How Carl has told Nudge to treat one contact. Automatic unless he sets one.
_Avoid_: State, label

**Done**:
Carl handled it. Nudge stays quiet about the contact until the other person writes again.
_Avoid_: Resolved, closed, archived

**Snoozed**:
Quiet until a date Carl chose, then automatic again.
_Avoid_: Paused, later

**Muted**:
Never nudge about this contact. For shops, tour operators and bots.
_Avoid_: Blocked, ignored

**Flagged**:
Carl's own flag with his own reason. Always nudges until he marks it done.
_Avoid_: Starred, pinned, manual flag

### Flags

**Flag**:
One reason a contact might deserve a nudge. A contact can carry several flags at once.
_Avoid_: Signal, trigger, rule

**Hard flag**:
A flag decided by code alone from timestamps or dates, with no reading of content.
_Avoid_: Rule

**Soft flag**:
A flag that depends on what the messages say, judged by Jev.
_Avoid_: AI flag, classification

**Broken rhythm**:
A hard flag: the current silence with a close contact is well beyond your normal rhythm.
_Avoid_: Fading, overdue, cadence breach

**Unanswered**:
A soft flag: they wrote last, and their last message expects a reply from you.
_Avoid_: Unread, pending

**Promise**:
A soft flag: you said you would do something in the recent messages.
_Avoid_: Commitment, todo

**Follow-up**:
A soft flag: they mentioned something upcoming in their life that is worth asking about afterwards.
_Avoid_: Event, reminder

**Open plan**:
A soft flag: you and the contact started making a plan together that was never settled or cancelled.
_Avoid_: Appointment, loose end

**Forgotten**:
An amplifier: an unanswered message, promise or open plan that has been sitting for a week or more. Forgotten open loops rank above fresh ones.
_Avoid_: Stale, overdue, old

**Personal**:
Whether a contact is a person Carl knows rather than a business, shop or automated sender. Non-personal contacts fade out of the ranking instead of being muted.
_Avoid_: Real contact, human

**Heavy topic**:
An amplifier, not a flag on its own: they shared something difficult, which raises the priority of any other flag.
_Avoid_: Sentiment, emotion

**Directed at you**:
Used in groups only: the message is aimed at you rather than the group in general.
_Avoid_: Mention
