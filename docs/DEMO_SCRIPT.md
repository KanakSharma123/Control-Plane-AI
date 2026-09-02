# Prototype demo video — running order

Round 2 asks for a demo video in the repo. Four minutes is plenty. Run
`streamlit run app.py` and follow this order; every beat below is a real
behaviour of the code, not a mock.

## 1. The headline case (45s)
Pick **CP-001 · Claim approved on an unsupported amount**, policy
`decision_support`. Run it.

Point at: Performance 5/5 with the evidence line naming ₹48.7L against
₹38.7L, Impact and Reversibility both 5/5, verdict **BLOCK**. Read one
line from "Why this rung" aloud — the rationale is generated, not
written by us.

## 2. Criticality doing real work (40s)
Pick **CP-021 · Aadhaar in an internal CRM note**, then **CP-004 · PAN
quoted back to the customer**.

Identical class of finding, different action type, different control.
This is the whole two-axis argument in one comparison.

## 3. Redaction over suppression (35s)
Pick **CP-003 · Account number leaked into a customer email**.

Verdict is **EDIT**, and the "Edited action" panel shows the reply
intact with only the account number replaced. Say the line: the customer
still gets their answer.

## 4. The latency story (40s)
Same case CP-003, switch the sidebar policy between `customer_chatbot`
and `decision_support`.

Tier 0 stays under a millisecond. Tier 1 mode flips between
`async (consequence held)` and `inline`. Nothing about the engine
changed — only the policy.

## 5. Uncertainty is not guilt (25s)
Pick **CP-016 · Multi-turn drift**. Confidence is 80%; note that the
rationale explains what would happen below the 70% floor — a BLOCK
becomes a HOLD rather than punishing the user for our own doubt.

## 6. The loop closes (45s)
Pick **CP-007 · Prompt injection**. Verdict **VERIFY**. Record an
override of **HOLD** with a note. The app confirms learned rule LR-001.

Now open the Audit trail tab, show the rule and the trail. Then go back
and run a *different* injection case — it comes out as **HOLD**, with
"Learned rule LR-001 applies" in the rationale.

That is one human decision becoming a future control, on screen.

## 7. Evidence (30s)
Terminal: `python -m pytest tests/ -q` (23 passing), then
`python run_eval.py --sweep`.

Say the honest line out loud: thresholds were tuned on this set, so it
shows the mechanism separates these cases, not that it generalises. A
judge who hears you say it first cannot use it against you.
