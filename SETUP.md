# Phone approval for Claude Code: editor setup

**Time: about 10 minutes, once.**

When Claude is about to make a big editing decision (a cut, deleting footage, the final export, publishing), it phones the approver, who presses **1** to say yes. You do nothing during the call.

## Before you start, get these from your admin

- [ ] The **approver's phone number** (looks like `+971501234567`)
- [ ] The **caller ID number** (same style)
- [ ] The **Bird API key** (starts with `bk_`)
- [ ] Access to the GitHub project **AnshMehraTools/approval_call** (the invite email)

---

## Step 1. Check Python is installed

- **Mac:** open **Terminal**, type `python3 --version`, press Enter.
  - If a pop-up asks you to install the **command line developer tools**, click **Install** and wait (it can take 10 minutes), or install Python from python.org instead. Then open a new Terminal window and try again.
- **Windows:** open **PowerShell**, type `python --version`, press Enter.

You should see `Python 3.` and a number. If you see an error instead, install Python from **python.org/downloads** (on Windows, tick **"Add Python to PATH"**), then open a new Terminal or PowerShell.

## Step 2. Install the plugin

Open Claude Code. Type these two lines, pressing Enter after each:

```
/plugin marketplace add AnshMehraTools/approval_call
/plugin install approval-flow@approval-flow
```

Claude Code now asks five questions. Answer them like this:

| It asks | You type |
|---|---|
| Your first name | Your first name (the approver hears it) |
| Approver's phone number | The number from your admin, with the `+` |
| Caller ID number | The number from your admin, with the `+` |
| Bird API key | Paste the key. It is hidden as you paste. |
| Bird API address | Leave as it is. Just press Enter. |

> **Never paste the API key into a chat with Claude.** Only into this form.

If Claude Code does not show these questions, type this and they will appear:

```
/plugin configure approval-flow@approval-flow
```

## Step 3. Restart

Close Claude Code completely. Open it again in your Hyperframes project folder.

## Step 4. Check it works

Type:

```
/approval-flow:doctor
```

You want to see lines starting with **[OK]** and, at the end, **"All good. You are set up."**

- A line saying **phone calls are OFF** is normal until your admin switches them on. Claude will ask you in the chat instead.
- A line starting with **[FIX]** tells you what to do (it has an arrow). Do it, restart Claude Code, run the check again.

---

## Using it day to day

You work with Claude as you always do.

- For a **big decision** (which cut, deleting footage, final export, publishing, a new look), Claude phones the approver once phone approval is switched on. Until then it asks you in the chat.
- **Preview renders** need no call. Claude names them like `preview-3.mp4`.
- If Claude says the approver **did not answer**, it asks you in the chat. Answer there.
- Some commands are **blocked until the approver says yes** (deleting footage, final renders, publishing). This is on purpose. Don't try to get around it.

## If something goes wrong

| What you see | What to do |
|---|---|
| `command not found: ask-approval` | Restart Claude Code. Type `/plugin` and check **approval-flow** is switched on. |
| Check says the **key was rejected** | Ask your admin for a new key. Then type `/plugin configure approval-flow@approval-flow`. |
| Check says Python **cannot verify Bird's certificate** (Mac) | Open the **Python** folder inside **Applications**, double-click **Install Certificates.command**, then run the check again. |
| Claude says **"Python 3 was not found"** | Do Step 1 again, then restart Claude Code. |
| You typed a number or name wrong, or the form did not appear | Type `/plugin configure approval-flow@approval-flow`. Fix it, then restart. |
| Anything else | Run `/approval-flow:doctor` and send your admin a screenshot (it shows no secrets). |

## Keep safe

- Do not share your API key or take screenshots of the settings form.
- If you lose your laptop, tell your admin straight away so they can cancel your key.
