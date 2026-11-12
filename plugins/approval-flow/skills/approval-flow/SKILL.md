---
name: approval-flow
description: Use when editing video (especially HyperFrames projects) and about to make a creative or irreversible decision such as a cut choice, deleting footage or assets, overwriting a file, rendering a final export, publishing or sharing, or changing the visual style. Explains how to get the approver's keypad OK by phone with ask-approval and how to act on the answer.
---

# Approval flow

The approver (a busy executive) approves big decisions by pressing a key on a phone call.
Your session context already says whether phone approval is ON or OFF. If it is OFF, ask in the chat instead.

## When to ask (and when not to)

Ask for a **creative or irreversible** decision:
- Cut choices: which take, what to trim, pacing, structure
- Deleting footage, assets or compositions; overwriting an existing file or render
- Rendering the **final** export; `hyperframes publish` or `share`; cloud (Lambda) renders
- Changing style: palette, fonts, layout, motion style, music, captions look

Do **not** ask for trivial choices: lint fixes, typos, file naming, preview renders (`-o preview-3.mp4`), restarting the preview, moving a clip by a few frames to fix a glitch. If in doubt about whether it is trivial, it probably is. Calls cost money and interrupt a busy person.

## How to ask

```
ask-approval "<question>" "<option 1>" "<option 2>" "<option 3>"
```

- **Option 1 is always the action you intend to take.** Options 2 and 3 are alternatives or a decline ("Not yet", "Something else").
- Under 20 seconds when spoken, at most 3 options, one decision per call. The approver cannot see the screen, so say what and which file in plain words.
- Good: `ask-approval "Render the final cut of the product launch as an MP4?" "Render it" "Not yet" "Something else"`
- Good: `ask-approval "Use the warm orange palette for the whole video?" "Use orange" "Keep the blue" "Show me both"`
- Bad: long questions, several decisions in one call, or an option 1 that is not what you will do.

## What the answer means

The command prints one JSON line.

| Result | What you do |
|---|---|
| exit 0, `"approved": true` | Do the action now |
| exit 0, `"approved": false` | Do NOT do it. Take the alternative they chose, or continue in the chat |
| exit 2 | No answer or the call could not connect: ask the user in the chat. Never guess |
| exit 3 | The approver's quiet hours: ask in the chat, or wait |
| exit 4 | Hourly call budget used: ask in the chat |
| exit 5 | Phone approval is switched off: ask in the chat |

## The approval gate

A hook blocks risky commands (deleting footage, final or overwriting renders, `publish`, `share`, force pushes, and so on) until the approver has pressed 1.
One approval unlocks exactly one command for 15 minutes. If a command is blocked, run `ask-approval`, then retry it.
Never try to get around the gate, and never read or write the approval folder or the saved credentials.

## HyperFrames notes

- Preview renders need no call: `npx hyperframes render -o preview-N.mp4` (always pass `-o` with a new, non-final name).
- Run `npx hyperframes lint` before every render.
- Edits to composition HTML are normal work and are not blocked by the gate, so use your judgement: creative changes need a call, routine fixes do not.
