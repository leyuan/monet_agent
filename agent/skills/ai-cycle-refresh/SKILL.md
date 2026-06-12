# AI Cycle Refresh

Daily refresh of the AI super-cycle signals that power the `/ai-cycle` dashboard
page and feed the Conviction portfolio's entry/exit gates. Lightweight — NO
trading, NO universe scoring. Just reassess the cycle and record a history point.

Run all steps in order. Total runtime ~1-2 minutes.

## Step 1 — Sector heat (bubble risk)

Call `assess_ai_bubble_risk()`. It returns a dict with `score`, `level`, and
sub-metrics. **Persist it** so the dashboard card and history snapshot can read it:

```
result = assess_ai_bubble_risk()
write_agent_memory("ai_bubble_risk", result)
```

## Step 2 — Cycle durability

Call `assess_ai_cycle_durability()`. This one **self-persists** to
`ai_cycle_durability` — you do NOT need to write it. Note its `phase` and `score`.

## Step 3 — Read forward capex guidance (the qualitative judgment)

The capex tool computes backward-looking capex from financials. YOU add the
forward view. Run `internet_search` for recent hyperscaler capex guidance, e.g.:

- "Microsoft Google Amazon Meta capex guidance 2026 raise"
- "hyperscaler AI capex outlook next quarter"

Read the headlines and form ONE judgment about the direction of *forward* guidance:
- `"raising"` — management is guiding capex higher / raising the full-year number
- `"maintaining"` — roughly holding the line
- `"cutting"` — pulling back / guiding lower

Write a one-line `summary` of what you saw (e.g. "MSFT + AMZN both raised FY26
capex on AI demand; META reiterated"). If the search is inconclusive, use
`"maintaining"` and say so.

## Step 4 — Compute the capex trend

Call `compute_ai_capex_trend(...)`, passing your Step 3 judgment:

```
compute_ai_capex_trend(
    forward_guidance_direction="raising",   # or maintaining / cutting
    forward_guidance_summary="<your one-line summary>",
)
```

This pulls quarterly capex for the hyperscalers (MSFT/GOOGL/AMZN/META) and memory
names (MU/WDC/SNDK), computes YoY/QoQ, blends in your forward read, and persists
`ai_capex_tracker`. Note the resulting `guidance_direction` and
`hyperscaler_total_yoy`.

## Step 5 — Record the daily history point

Call `record_ai_cycle_snapshot()`. It reads the three memory keys you just
refreshed and writes one dated row to `ai_cycle_snapshots` (the time series behind
the trend chart). Idempotent — re-running the same day upserts.

## Step 6 — Brief journal note (optional but preferred)

Write a SHORT journal entry (`entry_type="market_scan"`,
`run_source="ai_cycle_refresh"`) summarizing the read in 2-3 sentences: cycle
phase + score, capex direction + hyperscaler YoY, and any notable shift vs the
prior snapshot. This is the narrative that will seed the weekly email and help the
Conviction loop decide. Keep it tight — this runs every day.
