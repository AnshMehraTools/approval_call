---
name: doctor
description: Check that approval-flow is set up correctly on this computer (settings saved, Bird connection, caller ID, safety gate, Hyperframes requirements). Places no calls and shows no secrets. Use when the user runs /approval-flow:doctor or says phone approval is not working.
disable-model-invocation: true
---

# Approval flow setup check

Run this command and show the user its output exactly as printed:

```
sh "${CLAUDE_PLUGIN_ROOT}/scripts/run.sh" doctor.py
```

Then, in one or two plain sentences with no jargon, tell the user either "You are all set" or exactly which `[FIX]` lines they must act on and how. Do not read any files in the approval folder, and do not ask the user to paste their API key into the chat.
