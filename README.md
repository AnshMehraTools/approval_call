# approval-flow

A Claude Code plugin for video teams. Before Claude makes a **creative or irreversible** editing decision (a cut, deleting footage, the final export, publishing), it **phones the approver**, who presses a key: 1 to go ahead, 2 or 3 for an alternative. A safety gate blocks risky commands until the approver has said yes. Built for [Hyperframes](https://github.com/heygen-com/hyperframes) projects, and works for any video editing done with Claude Code. Calls go through Bird voice.

- **Editors:** follow [SETUP.md](SETUP.md).
- **Admin:** see [ADMIN.md](ADMIN.md) (publishing, rollout switch, policy, limits).

Phone calls ship **switched off**. Until the admin turns them on, Claude asks in the chat instead.

```
/plugin marketplace add AnshMehraTools/approval_call
/plugin install approval-flow@approval-flow
```
