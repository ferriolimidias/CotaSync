# CotaSync Product Invariants

The permanent product invariants are defined in
[`docs/PRODUCT_INVARIANTS.md`](docs/PRODUCT_INVARIANTS.md). Any change to
learning, individual execution, batch execution, or browser start behavior
must preserve them.

Violating these invariants is a product regression even when unrelated local
tests pass. Do not remove or weaken their tests to accommodate a new
implementation.

## Required Review Rule

Before changing a logical start, verify the shared start policy and the
invariant tests. A residual Chromium page is never valid evidence for the
initial state of a new logical unit.
