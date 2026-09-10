# HW1 Part C — analysis of one system prompt revision

## The omission

`SPEC.md` §5 lists four cases that **always go to a human**:

- ESC-1 refunds above the auto-approval threshold
- ESC-2 **account changes of any kind**
- ESC-3 disputes and requests the agent cannot resolve
- ESC-4 any case where the agent is unsure whether policy allows an action

The `## Escalation` section of `SYSTEM_PROMPT_TEMPLATE` (`agent/agent.py`) only
covered ESC-1 (named explicitly) and ESC-4 ("When you are unsure"). **ESC-2 was
absent.** The only account-adjacent text was in the refusal list —
"payment-card or credential changes" — which (a) is framed as *refuse*, not
*escalate*, and (b) does not obviously cover an email-address change.

## Predicted failure

Asked to make an account change, the agent would refuse to do it (correct) but
would **not** open an escalation (incorrect per ESC-2), leaving the user with
no path forward.

## Test (conversation 7, `hw1-session.jsonl` line 7)

Request, as shopper user 1, fresh CLI session:

> "Can you change the email address on my Cartwheel account to new@example.com?"

**Observed (before):** no tool calls. Response refused and redirected the user
to self-service account settings. No escalation ticket.

This is a prompt failure, not a tool or authorization failure:
`escalate_to_human` works (it fired correctly in conversation 3), and no tool
returned wrong data. The model simply had no instruction telling it that
account changes must be routed to a human.

## Revision (smallest change that addresses the failure)

One sentence added to the `## Escalation` section:

> Account changes of any kind (for example email, address, password, or
> closing an account) always go to a human this way: do not make the change
> yourself, and open an escalation so a human can.

## Re-test (same request, fresh session, only the prompt changed) — line 11

**Observed (after):** the agent called `escalate_to_human`, opened ticket #152,
and told the user a human would follow up within ~24 hours. ESC-2 satisfied.

## Regression check

After the edit, an ordinary order-status lookup and an ordinary policy
question still resolve with a single read tool and **no** escalation, so the
new sentence did not cause over-escalation. Full offline test suite unchanged
(same one pre-existing Langfuse-connection failure, unrelated to Module 1).

## Other omissions considered

- **ESC-3 (disputes / unresolvable requests).** Partly covered by "When you are
  unsure". Conversation 2 (a refund outside the return window) was resolvable
  from the order record and help center, and the agent handled it correctly
  without escalating, so no recorded conversation gave evidence for a change
  here.
- **Redundant escalation on above-threshold refunds (conversation 3).** The
  agent called `issue_refund` (which queues the refund for a human) *and*
  separately opened an `escalate_to_human` ticket. This is arguably noise, but
  the required behavior (queue the refund, explain the result) was met, so per
  the Part C rule ("do not revise the prompt unless a recorded conversation
  provides evidence for the revision") no edit was justified. A candidate
  future revision: state that a queued refund already routes to a human and
  needs no separate ticket.
