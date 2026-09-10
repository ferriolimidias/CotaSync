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

## INVARIANT: CANONICAL_EXTERNAL_ENTRY_URL

`ExternalSystem.entry_url` is the single source of truth for the beginning
of every new logical unit. Learning, individual Runs, and each new batch
client must begin by navigating to that configured URL. Browser residual
state, action `url_inicial`, legacy login metadata, redirect URLs, and global
authentication URLs must not replace it.

## INVARIANT: ENTRY_RESET_PER_CLIENT_NOT_PER_OUTPUT

Entry reset occurs once per new client or logical unit, never between steps
or multiple outputs belonging to the same Action and client. A batch with N
clients performs N entry navigations, independently of the number of outputs
per client.

## INVARIANT: ACCESS_BOOTSTRAP_SEPARATION

Access bootstrap and the main Action graph are different contexts.

Bootstrap includes Microsoft account selection, authentication, and the steps
needed to reach the external system. Those steps must not become main Action
graph steps. Runtime traces may report bootstrap separately, but the main
graph begins only after bootstrap succeeds.

## INVARIANT: ACCESS_PROFILE_SINGLE_SOURCE_OF_TRUTH

There is no operational global Microsoft identity in CotaSync. Every
external identity used by learning or execution belongs to an
`ExternalAccessProfile` explicitly associated with the context, and its
`login_identifier` is the identifier used for account-picker matching.
Configuration, browser authentication, validation, learning, and execution
must resolve the same `access_profile_id`. A global username, environment
default, or account-picker ordinal is never a fallback.

## INVARIANT: CANONICAL_ACCESS_FLOW

Authentication, learning, individual execution, and each batch client share
one canonical external-access state machine:

```text
ACCESS_START
-> EXTERNAL_ENTRY
-> ACCOUNT_PICKER
-> PROFILE_SELECTED
-> LEARNED_ACCESS_BOOTSTRAP
-> EXTERNAL_SYSTEM_READY
```

No subsystem may implement a separate ordering for external entry, account
selection, or learned access bootstrap. The coordinator receives an explicit
`ExternalSystem`, `ExternalAccessProfile`, `login_identifier`, and
`run_start_strategy`. A residual browser page and account-picker ordinal are
never valid identity or start-state sources.

## INVARIANT: PROFILE_SELECTION_FIRST

For Microsoft account-picker flows, the selected
`ExternalAccessProfile.login_identifier` is explicitly selected and confirmed
before any learned post-selection bootstrap event such as Accept or consent.
The access bootstrap remains separate from the main Action graph. Merely
landing on a consent page or seeing a previously selected account does not
count as `PROFILE_SELECTED`; the coordinator must observe the picker and
perform the explicit selection in the current cycle.

## INVARIANT: STATE_DRIVEN_WAITING

External system latency must not determine execution failure. CotaSync waits
for learned or expected state transitions continuously. Wall-clock locator or
navigation probe timeouts are technical probe expirations, not logical Run
failures. Execution ends only on success, explicit cancellation, or a
recognized terminal condition such as an unavailable browser or required
reauthentication.

## INVARIANT: RUN_EXECUTION_OBSERVABILITY

Every Run must have a structured, chronological, secret-safe timeline that is
queryable by `run_id` and identifies external entry, access bootstrap, main
graph, outputs, waits, and terminal status. The timeline must never include
credentials, cookies, tokens, OAuth query strings, or secret field values.
For `external_entry_each_run`, `MAIN_GRAPH_STARTED` must follow
`BOOTSTRAP_COMPLETED`.

## Regression Rule

Do not weaken or remove tests for these invariants to accommodate another
implementation. Any violation is a product regression, even when tests for
an unrelated feature pass.
