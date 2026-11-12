# Admin guide

For whoever runs the approval flow. Editors use [SETUP.md](SETUP.md).

## What is in this repo

```
.claude-plugin/marketplace.json            marketplace (so editors can add this repo)
plugins/approval-flow/
  .claude-plugin/plugin.json               plugin + the 5 questions asked at install
  policy.json                              YOUR central switches (calls on/off, quiet hours, limits)
  hooks/hooks.json                         session briefing + the approval gate
  bin/ask-approval, bin/approval-doctor    commands Claude and editors can run
  skills/approval-flow, skills/doctor      the rule for Claude, and /approval-flow:doctor
  scripts/                                 the code, plus test_gate.py (offline tests)
```

## 1. Publish

Create an empty repo on GitHub named `AnshMehraTools/approval_call` (private is fine; every editor then needs read access and to be signed in to GitHub on their computer). The repo holds no secrets and no phone numbers.

```
git remote add origin https://github.com/AnshMehraTools/approval_call.git
git push -u origin main
```

## 2. Give each editor their kit

Send through a password manager, never by chat or email:

- the **approver's phone number** and the **caller ID number**
- a **Bird API key**. Make **one key per editor** in Bird so you can cancel one without disturbing the rest.

Each editor types these into the form Claude Code shows when they install (SETUP.md, step 2). The key is stored privately, hidden from Claude.

> Anyone with a key can place calls from your Bird workspace, and every editor ends up with the approver's number on their computer (in a private file). Bird's daily spend cap ($10 at the moment) is the backstop. If that is not acceptable, the next step up is a small relay service that holds the key and number and gives editors only a token.

## 3. Roll out safely: calls are OFF by default

`policy.json` ships with `"calls_enabled": false`. Editors can install, configure and run the check, and Claude asks **in the chat** instead of phoning. The gate stays quiet but reminds Claude to ask.

**To switch phone calls on** when you are absolutely ready:

1. Edit `plugins/approval-flow/policy.json`: set `"calls_enabled": true`.
2. Raise `"version"` in `plugins/approval-flow/.claude-plugin/plugin.json` (editors only get updates when the version changes).
3. Commit and push.
4. Tell editors to update (`/plugin`, then update approval-flow, or `claude plugin update approval-flow@approval-flow`) and restart Claude Code.

**Emergency off:** set it back to `false`, bump the version, push. A single editor can also turn calls off locally by setting the environment variable `APPROVAL_CALLS=off`.

Before telling everyone, do one supervised call yourself: switch it on for your own computer only (`APPROVAL_POLICY_FILE` pointing at a copy of policy.json with `calls_enabled` true), and have the approver expect it.

## 4. Policy settings (`policy.json`)

| Setting | Default | Meaning |
|---|---|---|
| `calls_enabled` | `false` | Master switch for phone calls |
| `approver_timezone` | `Asia/Dubai` | Time zone used for quiet hours |
| `quiet_hours` | `22-07` | No calls in this window (approver's local time, 24h) |
| `max_per_hour` | `4` | Calls an editor's computer may place per rolling hour. **Counted per computer, not shared.** |
| `grant_ttl_s` | `900` | How long one approval stays valid (seconds) |
| `approve_digits` | `1` | Keys that count as "yes" (option 1 is always the intended action) |

## 5. What the gate covers for Hyperframes

The gate blocks these until the approver presses 1 (one approval unlocks one command, for 15 minutes):

| Hyperframes action | Gated? |
|---|---|
| `npx hyperframes render -o preview-N.mp4` (new, non-final name) | No, needs no call |
| `render` with no `-o`, to an existing file, or named final / export / master / render / deliver | **Yes** |
| `hyperframes publish`, `hyperframes share` (they upload the project) | **Yes** |
| Cloud (Lambda) renders: `@hyperframes/aws-lambda`, `hyperframes lambda` | **Yes** (costs money) |
| `normalize-audio --write` (changes the mix) | **Yes** (without `--write` it is a dry run) |
| `npm/pnpm/yarn run render \| export \| publish \| deploy` | **Yes** |
| Deleting footage, assets, images or composition `.html` files | **Yes** |
| Overwriting an existing file with `cp`, `mv` or `>`; `ffmpeg -y`; force push; `git reset --hard` | **Yes** |
| `lint`, `preview`, `init`, `add`, `doctor` | No |
| Editing composition HTML (cuts, pacing, palette, fonts, layout, music) | **No.** This is normal work, so the gate cannot judge it. The rule in the session briefing and the skill tell Claude to ask for creative changes. |

The gate is a safety net against accidents, not a lock. It cannot see what a script does internally, and it does not judge whether an HTML edit is creative.

Hyperframes details come from its public docs, which disagree in places on subcommands; re-check with `npx hyperframes --help` when Hyperframes updates, and add any new export or upload command to `hyperframes_reasons()` in `scripts/approval_gate.py`.

## 6. Known limits

- **Rate limit is per computer.** Five editors at 4 calls an hour could ring the approver 20 times an hour. Lower `max_per_hour`, or ask us to add a shared limiter.
- **Overlapping calls.** Two editors asking at once ring the approver twice. The spoken intro includes the editor's name so he knows who is asking.
- **Bird billing.** Calls to the UAE cost about $0.16 each (measured). The daily cap in Bird applies to the whole workspace.
- **Calling India.** The Indian caller ID we tested was rejected by Indian carriers on international routes. Calls to the UAE and Canada connected. If the approver is ever in India, use a different caller ID.
- **macOS and Windows are untested on real machines** (everything was tested on Linux). The launcher was checked under strict POSIX shells and the scripts under the Python 3.8 grammar. Known Mac traps are covered in SETUP.md (the developer-tools pop-up and the Python certificates step). The first Mac and Windows editors should run `/approval-flow:doctor` and report back.

## 7. Tests

```
python3 plugins/approval-flow/scripts/test_gate.py     # offline, places no calls
claude plugin validate .
```

Verified so far: the offline suite passes; the plugin loads in real Claude Code (the `ask-approval` command is found, the session briefing runs, install-time settings are saved privately, and the gate blocks a risky command); a real keypress was read earlier by the standalone version of this tool. **Not yet verified:** a full live call placed through this packaged plugin, a private-repo install on an editor's computer, and Windows.

## 8. Remove

```
claude plugin uninstall approval-flow@approval-flow
```

Then delete the folder `~/.claude/approval-flow` (Windows: `%USERPROFILE%\.claude\approval-flow`). It holds the saved key and the call log.
