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

## Step 5 — Cycle signals (the qualitative layer the quant misses)

The capex/durability scores are quantitative. This step captures the NARRATIVE
signals that front-run them — the things that move before the numbers do.

**Start with structured news**: call `get_ai_infra_news()` — it returns sourced,
ticker-tagged, dated headlines for the AI-infra basket (hyperscalers + memory + key
semis) from Finnhub. This is your primary candidate set — more reliable than free-text
search (real source links, no hallucinated attribution). Scan it for items matching the
angles below.

**Then fill gaps with `internet_search`** for the angles company-news tags poorly —
especially DRAM/HBM contract pricing and sector-wide financing (rotate / prioritize what's fresh):

- **Demand stress** — customers pushing back on AI/token cost, ROI doubts, budget
  overruns ("AI inference cost", "AI budget overrun", "token tax margins")
- **Financing strain** — capex funded by debt/equity issuance ("hyperscaler AI
  capex debt bond issuance", "data center financing")
- **Supply tightness** — memory/HBM shortages, lead times, pricing ("HBM DRAM
  shortage", "memory pricing")
- **Capacity / guidance** — new fabs/data centers, hyperscaler capex guidance changes

Curate the **top 4-7** most cycle-relevant items. For each, classify:
- `category`: `demand_stress` | `financing_strain` | `supply_tight` | `capacity_adds` | `guidance_shift`
- `direction`: `supportive` | `cautionary` | `neutral`
- `why`: ONE line on what it means for the cycle (your read, not just a summary)
- plus `headline`, `source`, `url` (real link), `date` — the **article's publication
  date** (from the source/Finnhub item), NOT today's date. If you can't establish a
  real pub date, drop the item rather than stamp it with today.

Then persist (REPLACE the list each run — keep it current, ~7 max):
```
write_agent_memory("ai_cycle_signals", {
    "as_of": "<ISO now>",
    "net_read": "<1-2 sentences synthesizing the balance: supportive vs cautionary, where's the weight>",
    "signals": [ {headline, source, url, date, category, direction, why}, ... ],
})
```

Discipline: **signal, not noise.** Cap at ~7, each must carry a real source link, and
the `why` must tie to the cycle — not generic AI news. A cluster of `demand_stress` +
`financing_strain` is an early warning the cycle is maturing; reflect that in `net_read`
and your Step 7 journal note.

**Freshness — this is a feed of what's MOVING, not standing facts:**
- **Drop anything whose article is older than 7 days.** A 2-month-old capex article
  re-surfaced today is not a signal — it misrepresents freshness (and now seeds the
  daily email subject line). If nothing fresh exists for an angle, leave it out.
- **Don't restate standing capex *levels* as signals.** The current hyperscaler capex
  total / YoY (e.g. "$725B, +77%") already lives in `ai_capex_tracker` and shows on the
  AI Capex Trend card and the email's AI Super-Cycle band. Only surface a `guidance_shift`
  / `capacity_adds` signal when there's a genuine *change* (a new raise, a cut, a new
  fab/contract) — dated to when it was actually reported.

## Step 6 — Record the daily history point

Call `record_ai_cycle_snapshot()`. It reads the cycle memory keys you just
refreshed and writes one dated row to `ai_cycle_snapshots` (the time series behind
the trend chart). Idempotent — re-running the same day upserts.

## Step 7 — Brief journal note (optional but preferred)

Write a SHORT journal entry (`entry_type="market_scan"`,
`run_source="ai_cycle_refresh"`) summarizing the read in 2-3 sentences: cycle
phase + score, capex direction + hyperscaler YoY, and any notable shift vs the
prior snapshot. This is the narrative that will seed the weekly email and help the
Conviction loop decide. Keep it tight — this runs every day.
