# Conviction Loop

The **Conviction** portfolio is a concentrated, cyclical capex-cycle book — the
opposite of Quant Core's diversified factor strategy. It holds **1-3 AI-infra
cyclicals** from the `conviction_universe` memory (currently memory MU/WDC/SNDK/STX,
optical/networking FN, power NVTS), enters when the AI capex super-cycle is
inflecting/accelerating, **rides the trend**, and **exits hard** when capex or
pricing rolls over. Cyclicals round-trip — the sell discipline IS the edge.

ALL Conviction trades use `portfolio="conviction"` and
`risk_overrides=CONVICTION_RISK_OVERRIDES` (concentration is intentional here).

Run every step in order. This loop runs once per weekday.

---

## Step 0 — Reconcile + load state

1. `reconcile_positions(portfolio="conviction")` — catch any bracket fills since last run.
2. `get_portfolio("conviction")` — current Conviction positions, equity, cash.
3. Read memory: `conviction_universe` (the candidate list), `ai_cycle_durability`,
   `ai_capex_tracker`, and the latest two `ai_cycle_snapshots` rows (query the table)
   — you need the prior snapshot to judge whether memory demand is rising or falling.

---

## Step 1 — HARD EXIT CHECK (do this BEFORE any entry)

Exits protect the book. Evaluate these every run, in order. If ANY fires for a
held name, **sell the full position** (`place_order(symbol, "sell", qty,
portfolio="conviction")`) and journal why. Do not rationalize holding through a
confirmed rollover.

- **Capex rollover** — `ai_capex_tracker.guidance_direction == "decelerating"`
  OR `hyperscaler_total_yoy` turned negative → exit ALL Conviction positions.
- **Cycle cooling** — `ai_cycle_durability.phase == "cooling"` OR `score < 40` → exit.
- **Memory-demand rollover** — the durability `memory_demand.vs_spy_pct` has gone
  negative AND fallen across the last 2 `ai_cycle_snapshots` → exit memory names.
- **Stop already hit** — reconcile in Step 0 will have recorded any bracket stop
  fill; confirm the position is flat and note the loss.

If a hard exit fires, you may stop here for that name (no re-entry same week).

---

## Step 2 — ENTRY GATE (only if no exit fired and you have room)

Conviction holds at most 3 names. If already at 3, skip to Step 4. Otherwise,
ALL of these must be true to open or add a position:

1. **Cycle healthy** — `ai_cycle_durability.phase` is `full_build` or `expanding`,
   AND `score >= 60`.
   - ⚠️ If durability is `maturing`/`cooling`, do NOT enter on price signals alone.
     BUT note the known limitation: durability is price-momentum-based and lags the
     fundamentals. If durability is `maturing` ONLY because its capex sub-signal was
     stale ("Pending"), and the capex gate below is strongly accelerating, you may
     treat the cycle as healthy — say so explicitly in the journal.
2. **Capex accelerating** — `ai_capex_tracker.guidance_direction == "accelerating"`
   (or `"stable"` with forward guidance raising). This is the PRIMARY gate — real
   spend is the thesis.
3. **Memory-demand inflecting** — `memory_demand.vs_spy_pct > 0` and rising vs the
   prior `ai_cycle_snapshots` row.

If the gate passes, read 2-3 recent headlines via `internet_search` on DRAM/HBM/NAND
pricing and the specific name to confirm nothing has broken (a guidance cut, a
fab issue). One qualitative sanity check — then proceed.

---

## Step 3 — SELECT, SIZE, EXECUTE

1. **Select**: the candidate universe is the `conviction_universe` memory
   (`value.symbols`; default `MU, WDC, SNDK, STX` if absent). Among names not already
   held, pick the top 1-2 by 3-month momentum (use `get_historical_bars`/
   `technical_analysis`). The universe spans AI-infra layers (see `value.notes`):
   memory (MU/WDC/SNDK/STX), optical/networking (FN), power (NVTS). MU is the memory
   bellwether — prefer it among memory names unless a clear reason not to.
   - **Layer-aware gating**: the Step 2 memory-demand inflection signal applies to the
     memory names. For a non-memory candidate (e.g. FN = optical, NVTS = power), confirm
     the relevant `ai_cycle_durability` sub-signal instead — `infra_momentum` (power) for
     NVTS, stack-breadth/Networking participation for FN — plus a headline check.
2. **Conviction tier**: `high` (40% of book) only when the cycle is `full_build`
   AND capex accelerating AND the name is the clear leader; `medium` (30%) for a
   solid setup; `starter` (20%) when you want exposure but the signal is early.
3. **Size (STAGED)**: `size_cycle_position(symbol, conviction="<tier>")` deploys a
   ~66% STARTER of the tier target and keeps the rest as dry powder — it returns
   the starter `quantity`, `deployed_pct`/`reserve_pct`, `stop_loss_price`,
   `take_profit_price`, and writes a `conviction_plan:{SYMBOL}` so Step 3.5 can add
   the reserve on dips. Do NOT deploy the full target up front — the reserve is
   what lets you buy an intact-thesis dip. (Pass `deploy_fraction=1.0` only if you
   deliberately want a full-size entry with no reserve.)
4. **Execute**:
   ```
   place_order(
       symbol, "buy", <quantity>,
       take_profit_price=<tp>, stop_loss_price=<sl>,
       thesis="<capex-cycle thesis + the gate readings>",
       portfolio="conviction",
       risk_overrides=CONVICTION_RISK_OVERRIDES,
   )
   ```
   The wide ATR stop is the safety net; the bracket TP keeps the order valid.

Keep total Conviction names ≤ 3. Do not diversify for its own sake — concentration
is the point. One or two high-conviction names beats five half-convictions here.

---

## Step 3.5 — MANAGE held positions (add on dips, trim overshoots)

After entry there's still work: a conviction book that's fully deployed and only
ever exits is leaving its best move — buying an intact-thesis dip — on the table.
Call **`manage_cycle_positions("conviction")`**. It checks each held name against
the SAME thesis signals as Step 1 and returns `add` / `trim` / `hold` actions:

- **ADD** (name ≥8% below entry, thesis intact, room below target, cash available)
  — deploys reserve into the dip. Execute it:
  ```
  place_order(symbol, "buy", <quantity>, thesis="<dip add: % below entry + the
              still-intact gate readings>", portfolio="conviction",
              risk_overrides=CONVICTION_RISK_OVERRIDES)
  ```
- **TRIM** (name ≥40% above entry) — bank a slice, refill dry powder:
  ```
  place_order(symbol, "sell", <quantity>, thesis="<trim overshoot: % above entry>",
              portfolio="conviction", risk_overrides=CONVICTION_RISK_OVERRIDES)
  ```
- **HOLD** — nothing to do; the `reason` tells you why (within band, no room,
  cooldown, or thesis broken).

**Critical discipline**: if `thesis_intact` is **false**, the tool will NOT
recommend adds — it returns HOLD with the broken reason. Do not override and
average down into a breaking thesis; that's a Step-1 EXIT, not an add. Adding is
only for dips where the cycle thesis still holds.

After executing, re-run reflects in the next loop (cooldowns prevent same-name
adds/trims on back-to-back runs).

---

## Step 4 — Trail winners + record

- For any winner up materially since entry, ratchet the stop UP toward breakeven
  or better with `attach_bracket_to_position(symbol, qty, stop_loss_price=<higher>,
  portfolio="conviction")`. Let the position run; just protect gains.
- `record_daily_snapshot(portfolio="conviction")` — log the Conviction equity curve.
- Write a journal entry (`entry_type="trade"`, `run_source="conviction_loop"`):
  the gate readings (cycle phase/score, capex direction + YoY, memory demand),
  what you did and why, and current Conviction holdings with unrealized P&L. Be
  honest about cycle position — this book lives or dies on exit discipline.
