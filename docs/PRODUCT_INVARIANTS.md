# CotaSync Product Invariants

These are permanent product rules, not implementation suggestions.

## INVARIANT: FRESH_LOGICAL_START

Every new logical execution unit starts at the external entry:

- a new individual client execution;
- each new client in a batch;
- a new Action teaching session.

The required sequence is:

```text
external entry_url
-> access bootstrap
-> main action
-> output(s)
-> end
```

The residual Chromium page must never be used as the initial state of a new
unit. A same-unit continuation may navigate through multiple pages and collect
multiple outputs without restarting the external entry. A new Run, new batch
client, or new LearningSession starts again at the external entry.

The authoritative code policy is
`backend/services/start_policy.py`. The `external_entry_each_run` strategy
requires an active access profile and a configured entry URL.

## INVARIANT: ACCESS_BOOTSTRAP_SEPARATION

Access bootstrap and the main Action graph are different contexts.

Bootstrap includes Microsoft account selection, authentication, and the steps
needed to reach the external system. Those steps must not become main Action
graph steps. Runtime traces may report bootstrap separately, but the main
graph begins only after bootstrap succeeds.

## Regression Rule

Do not weaken or remove tests for these invariants to accommodate another
implementation. Any violation is a product regression, even when tests for
an unrelated feature pass.
