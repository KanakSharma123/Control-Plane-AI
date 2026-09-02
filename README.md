# ControlPlane.ai

**Gate the consequence, not the sentence.**

A runtime governance layer that sits on top of any model and decides what
should happen to an AI action *before* it triggers a real-world
consequence.

Accenture Innovation Challenge 2026 · Round 2 · Problem Track 1 ·
Team **kamana24**

---

## The idea in one paragraph

Reading a wrong answer is reversible. Acting on one is not. Most AI
oversight inspects text and pays a latency cost on every request to do
it; ControlPlane inspects the *action*, and decides how much scrutiny it
deserves from two independent questions:

| | Question | Built from |
|---|---|---|
| **AI Health** | How likely is the model to be wrong? | performance, cost, responsibility |
| **Decision Criticality** | How much does it matter if it is? | impact, reversibility |

Together they select the **minimum necessary intervention** — the least
action that makes the situation safe.

```
ALLOW  →  MONITOR  →  EDIT  →  VERIFY  →  HOLD  →  BLOCK
 send    send+log   redact   re-check   human    never
                    + send    first     decides   runs
```

Every score in the system runs **1 = low concern → 5 = high concern**.
There are no exceptions and nothing inverts it.

---

## Quickstart

```bash
git clone <repo-url>
cd controlplaneai

python -m venv venv
source venv/bin/activate          # Windows: venv\Scripts\activate
pip install -r requirements.txt

streamlit run app.py              # interactive demo
python run_eval.py                # evaluation over the labelled set
python run_eval.py --sweep        # over-flag / under-flag tradeoff
python run_eval.py --by-use-case  # same cases, three policies
python -m pytest tests/ -q        # 23 tests
```

No API keys and no network access are required. The Tier 1 judge is
stubbed so the prototype is reproducible offline; the interface is the
real one, and swapping `_simulated_judge` for an API call changes nothing
else in the pipeline.

---

## What the prototype demonstrates

**Two-axis scoring.** `src/health_engine.py` and
`src/criticality_engine.py`. Criticality is read from
`config/action_registry.json` rather than inferred, which means it needs
no model, costs no inference latency, and cannot be manipulated by the
content of a response.

**Tiered checking, with real measurements.** `src/pipeline.py`. Tier 0 is
deterministic and runs on everything in well under a millisecond. Tier 1
is the expensive rung and runs only when Tier 0 has flagged something, or
when the action is critical enough that a second opinion is worth its
latency. Criticality *alone* does not trigger it — a clean, fully
grounded payment release does not need a secondary model to confirm it is
clean.

**Policy, not engineering.** `config/policies.json` defines three use
cases with different latency budgets and risk appetites. The customer
chatbot has a 400 ms budget, so Tier 1 runs asynchronously while the
irreversible action is held; the batch decision-support tool waits for
it. Same engine, different policy — which is the Round 2 brief's point
that one-size-fits-all checking rarely works.

**Responsibility by worst-case, not by mean.** Privacy, safety, fairness
and security are scored separately and combined with `max`. Averaging
would let three clean sub-scores bury one serious finding.

**Redaction over suppression.** A leaked account number produces `EDIT`
with the identifier removed and the rest of the reply intact — not a
blocked response. `tests/test_controlplane.py::test_redaction_preferred_over_suppression`.

**Uncertainty is not guilt.** Low assessment confidence never escalates
to `BLOCK`. If the system is unsure, it verifies or asks a human; it does
not punish the user for its own doubt.

**The checker as an attack surface.** The Tier 1 judge never receives
untrusted content as instructions — it receives it as quoted evidence
inside a fixed frame (`src/detectors/judge.py`). Prompt-injection strings
are caught deterministically at Tier 0, with no model in the loop.

**A feedback loop that compounds.** `src/audit.py`. Every assessment is
appended to a JSONL audit trail. A reviewer escalation becomes a learned
rule, so the same pattern is caught automatically next time. An override
that *relaxes* a control is logged but never learned from — loosening a
control should not propagate from one reviewer's judgement.

---

## Results on the labelled set

22 cases in `data/demo_cases.json`, each carrying a
`label_should_intervene` ground truth.

```
True positives   14      False positives   0
False negatives   0      True negatives    8

Recall 100%   Precision 100%   FPR 0%   FNR 0%
Tier 1 ran on 64% of cases   Mean latency 319 ms
```

**Read those numbers with the caveat they deserve.** The thresholds were
tuned against this same 22-case set, so what the result shows is that the
mechanism cleanly separates these cases — *not* that it generalises to
unseen traffic. A held-out set is the first thing this needs, and we say
so rather than presenting a self-graded exam as validation.

Two further honest notes. The demo set is deliberately adversarial: 14 of
22 cases are genuine failures, which is why Tier 1 fires on 64% of it.
Real traffic is overwhelmingly benign, so the Tier 1 share there would be
far lower — that is the whole basis of the latency argument, and it is an
argument from design rather than a measurement we can yet claim. And the
`--sweep` output shows the tradeoff explicitly: at a `MONITOR` floor the
false-positive rate is 37.5%, which is what alert fatigue looks like in
a number.

---

## Layout

```
controlplaneai/
├── app.py                      Streamlit demo
├── run_eval.py                 metrics harness (FP/FN, sweep, per-policy)
├── config/
│   ├── action_registry.json    impact + reversibility per action type
│   └── policies.json           per-use-case latency budget & risk appetite
├── data/
│   └── demo_cases.json         22 labelled cases
├── src/
│   ├── models.py               scoring convention lives here
│   ├── pipeline.py             tiered orchestration + latency
│   ├── health_engine.py        AI Health aggregation
│   ├── criticality_engine.py   Decision Criticality lookup
│   ├── control_engine.py       risk × criticality matrix, confidence, rules
│   ├── audit.py                audit trail + learned rules
│   └── detectors/
│       ├── grounding.py        claim-level verification (Tier 0)
│       ├── consistency.py      sampled-generation divergence (Tier 0)
│       ├── responsibility.py   privacy/safety/fairness/security (Tier 0)
│       ├── cost.py             spend vs expected envelope (Tier 0)
│       └── judge.py            secondary-model review (Tier 1)
└── tests/                      23 tests
```

---

## Known limitations

We would rather state these than have them found.

- **Detectors are deterministic and English/INR-shaped.** Grounding
  handles rupee amounts, percentages and dates. Semantic claims that
  cannot be reduced to a comparable token are scored *unverified*, not
  *correct* — but they are not caught either.
- **Tier 1 is simulated.** It mirrors Tier 0's evidence rather than
  making a live model call. The seam is real; the intelligence behind it
  is not yet.
- **Fairness detection is a co-occurrence heuristic.** It flags a
  protected attribute appearing alongside an adverse outcome. That is a
  prompt for review, not a finding of bias, and it is labelled that way
  in the output.
- **No held-out evaluation.** As above.
- **Cost figures are illustrative.** The expected-cost envelope in
  `src/detectors/cost.py` is assumed, not measured against a real
  deployment.

## Assumptions

Stated explicitly, per the brief's instruction to make and declare
reasonable assumptions:

- An enterprise running several AI use cases at once, on the order of
  tens of thousands of interactions per week
- A foundation model consumed via API, so ControlPlane works at the
  input/output layer and never inspects model internals
- Action types registered once by the enterprise; unregistered actions
  fall back to a conservative default of 3/3
- Indian insurance/financial context for the worked examples; all names,
  figures and identifiers are synthetic

---
