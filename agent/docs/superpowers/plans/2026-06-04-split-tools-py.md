# Split `tools.py` into a `tools/` package Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Split the 4648-line `agent/src/stock_agent/tools.py` into a focused `tools/` package, with zero behavior change — the same tools, same `AUTONOMOUS_TOOLS`/`CHAT_TOOLS` contents, same importable symbols.

**Architecture:** Convert the single module into a package `stock_agent/tools/` with category submodules (`market`, `trading`, `memory`, `reports`, `research`, `strategy_health`, `factors`) plus `_shared.py` for the three genuinely cross-category helpers. `tools/__init__.py` imports every tool function from the submodules, rebuilds `AUTONOMOUS_TOOLS` and `CHAT_TOOLS` verbatim, and re-exports the individual functions that external callers import (`get_sp500_sp400_tickers`, `get_earnings_results`, etc.). Because the public surface is preserved, `agent.py`, `autonomy.py`, `backtest/data.py`, and `scripts/seed_earnings_profiles.py` need **no changes**.

**Tech Stack:** Python 3, LangGraph / deepagents, pytest (added), yfinance/finnhub/alpaca/tavily clients (unchanged).

**This is a pure move.** No function body is edited. The only new code is `_shared.py` headers, the per-module import blocks, `__init__.py`, and the characterization test. Verification = "the public surface is byte-identical in behavior."

---

## File Structure

New package `agent/src/stock_agent/tools/`:

| Module | Functions / symbols (moved verbatim from `tools.py`) | Source line ranges |
|--------|------------------------------------------------------|--------------------|
| `_shared.py` | `_avg_return`, `_DEFAULT_FACTOR_WEIGHTS`, `_load_factor_weights` | 1868–1873, 3782–3784, 3785–3801 |
| `market.py` | `SECTOR_ETFS`, `CYCLICAL_SECTORS`, `DEFENSIVE_SECTORS`, `internet_search`, `get_stock_quote`, `get_historical_data`, `technical_analysis`, `fundamental_analysis`, `screen_stocks`, `company_profile`, `sector_analysis`, `peer_comparison`, `earnings_calendar`, `eps_estimates`, `market_breadth`, `_safe_float` | 56–71, 78–102, 103–118, 119–131, 132–145, 146–182, 183–343, 344–481, 482–567, 568–653, 654–813, 814–874, 875–969, 1858–1867 |
| `trading.py` | `place_order`, `cancel_order`, `get_open_orders`, `get_portfolio_state`, `reconcile_positions`, `check_trade_risk`, `get_my_portfolio`, `attach_bracket_to_position` | 970–1175, 1176–1264, 1265–1322, 1597–1605, 1606–1794, 1795–1818, 1819–1827, 3447–3530 |
| `memory.py` | `read_agent_memory`, `read_all_agent_memory`, `write_agent_memory`, `write_journal_entry`, `update_market_regime`, `update_stock_analysis`, `record_decision`, `manage_watchlist`, `query_database`, `submit_user_insight` | 1323–1337, 1338–1356, 1357–1370, 1371–1397, 1398–1431, 1432–1524, 1525–1564, 1565–1596, 1828–1857, 4607–4635 |
| `reports.py` | `_fmt_currency`, `_fmt_pct`, `_inline_bold`, `_markdown_to_html`, `_build_subscription_email`, `send_daily_recap`, `send_daily_subscription_emails`, `send_weekly_cycle_report`, `record_daily_snapshot`, `get_performance_comparison`, `position_health_check` | 1941–1946, 1947–1952, 2900–2905, 2906–2977, 2978–3138, 1874–1940, 3139–3274, 3275–3446, 3531–3571, 3572–3642, 3643–3776 |
| `research.py` | `AI_SEMI_BASKET`, `_rsi`, `assess_ai_bubble_risk`, `AI_CYCLE_LAYERS`, `assess_ai_cycle_durability` | 1953–1958, 1959–1967, 1968–2099, 2100–2108, 2109–2308 |
| `strategy_health.py` | `audit_factor_ic`, `check_live_vs_backtest_divergence`, `suggest_factor_weight_adjustment` | 2309–2576, 2577–2708, 2709–2899 |
| `factors.py` | `_factor_cache`, `_FACTOR_CACHE_TTL`, `_percentile_rank`, `_check_reentry_delta`, `score_universe`, `enrich_eps_revisions`, `generate_factor_rankings`, `check_watchlist_alerts`, `discover_catalysts`, `get_earnings_results` | 52–53, 3777–3781, 4104–4182, 3802–3980, 3981–4103, 4183–4327, 4328–4376, 4377–4450, 4451–4552 |
| `__init__.py` | imports all of the above; defines `AUTONOMOUS_TOOLS`, `CHAT_TOOLS`; re-exports `get_sp500_sp400_tickers` | n/a (new) |

**Cross-module dependency rule (prevents cycles):** submodules may import only from `stock_agent.tools._shared` and from non-`tools` modules (`db`, `market_data`, `alpaca_client`, `finnhub_client`, `technical`, `risk`, `supabase_client`, `factor_scoring`). They must **never** import from each other or from `tools/__init__.py`. The only cross-category helpers live in `_shared.py`: `market.py` and `research.py` import `_avg_return`; `factors.py` and `strategy_health.py` import `_load_factor_weights`.

**`factor_scoring` imports stay function-local.** Lines 1050, 2336, 2594, 3870 do `from .factor_scoring import ...` *inside* function bodies. Keep them inside the moved function bodies (the relative import `from .factor_scoring` resolves the same from `stock_agent/tools/<mod>.py` because `factor_scoring` is one level up — change `from .factor_scoring` → `from ..factor_scoring` in the moved bodies). This is the one in-body edit allowed, and it is mechanical.

---

### Task 1: Snapshot the current public surface (lightweight — no new test infra)

Per user preference (simplicity first), verification uses an ephemeral before/after surface diff rather than a committed pytest test. No `tests/` dir is added.

**Files:** none (writes a temp baseline to `/tmp`, not committed)

- [ ] **Step 1: Capture the CURRENT tool surface to a baseline file**

Run:
```bash
cd agent && python -c "from stock_agent.tools import AUTONOMOUS_TOOLS, CHAT_TOOLS; f=lambda L:sorted(getattr(t,'name',None) or getattr(t,'__name__',str(t)) for t in L); print('AUTON',*f(AUTONOMOUS_TOOLS),sep='\n'); print('CHAT',*f(CHAT_TOOLS),sep='\n')" > /tmp/tools_surface_before.txt
```
Expected: file has 58 lines = 45 autonomous + 11 chat tool names + 2 section headers (`AUTON`, `CHAT`). This is the source of truth for the whole refactor.

- [ ] **Step 2: Define the reusable verify command** (run after every later task)

```bash
cd agent && python -c "from stock_agent.tools import AUTONOMOUS_TOOLS, CHAT_TOOLS; f=lambda L:sorted(getattr(t,'name',None) or getattr(t,'__name__',str(t)) for t in L); print('AUTON',*f(AUTONOMOUS_TOOLS),sep='\n'); print('CHAT',*f(CHAT_TOOLS),sep='\n')" > /tmp/tools_surface_now.txt && diff /tmp/tools_surface_before.txt /tmp/tools_surface_now.txt && echo "SURFACE OK"
```
Expected: prints `SURFACE OK` with no diff output. Any diff = a tool was lost/renamed/added — stop and fix before committing.

- [ ] **Step 3: Commit the plan only**

```bash
cd agent && git add docs/superpowers/plans/2026-06-04-split-tools-py.md
git commit -m "docs: plan for splitting tools.py into a package"
```

---

### Task 2: Create the package skeleton + `_shared.py`

**Files:**
- Modify: rename `agent/src/stock_agent/tools.py` → `agent/src/stock_agent/tools/__init__.py` (temporary home; gutted in later tasks)
- Create: `agent/src/stock_agent/tools/_shared.py`

- [ ] **Step 1: Convert the module into a package without losing the file**

```bash
cd agent/src/stock_agent
mkdir tools_pkg
git mv tools.py tools_pkg/__init__.py
git mv tools_pkg tools
```
(Two-step rename avoids a path clash between the file `tools.py` and dir `tools/`.)

- [ ] **Step 2: Verify nothing broke yet**

Run the surface-diff command from Task 1 Step 2.
Expected: `SURFACE OK` — `tools/__init__.py` is still the full original module.

- [ ] **Step 3: Create `_shared.py`**

Create `agent/src/stock_agent/tools/_shared.py` with this header, then move the bodies of `_avg_return` (orig lines 1868–1873), `_DEFAULT_FACTOR_WEIGHTS` (3782–3784), and `_load_factor_weights` (3785–3801) verbatim:

```python
"""Cross-category helpers shared by more than one tools submodule."""

import logging

from stock_agent.db import read_memory

logger = logging.getLogger(__name__)

# --- moved verbatim from the original tools.py: ---
# _avg_return(...)
# _DEFAULT_FACTOR_WEIGHTS = {...}
# _load_factor_weights(...)
```

Delete those three definitions from `tools/__init__.py`. At the top of `tools/__init__.py` add `from stock_agent.tools._shared import _avg_return, _DEFAULT_FACTOR_WEIGHTS, _load_factor_weights` so the still-monolithic code keeps resolving them.

- [ ] **Step 4: Verify**

Run the surface-diff command from Task 1 Step 2.
Expected: `SURFACE OK`.

- [ ] **Step 5: Commit**

```bash
cd agent && git add -A && git commit -m "refactor(tools): make tools a package, extract _shared helpers"
```

---

### Tasks 3–9: Extract each category submodule

Each task is identical in shape. For category `<MOD>` with its function list and line ranges from the File Structure table:

- [ ] **Step 1: Create `agent/src/stock_agent/tools/<MOD>.py`** with a module docstring + import header (see per-module headers below), then **move the listed definitions verbatim** out of `tools/__init__.py` into it. In moved bodies, rewrite any `from .factor_scoring import` → `from ..factor_scoring import`. Leave every other line byte-identical.

- [ ] **Step 2: In `tools/__init__.py`**, delete the moved definitions and add `from stock_agent.tools.<MOD> import (<the public names just moved>)` near the top (so the `AUTONOMOUS_TOOLS`/`CHAT_TOOLS` lists at the bottom still resolve every name).

- [ ] **Step 3: Verify** — run the surface-diff command from Task 1 Step 2 → must print `SURFACE OK`.

- [ ] **Step 4: Commit** — `git add -A && git commit -m "refactor(tools): extract <MOD> submodule"`.

**Do them in this order** (leaf modules first, so `__init__` shrinks steadily): **Task 3** `research.py`, **Task 4** `strategy_health.py`, **Task 5** `reports.py`, **Task 6** `memory.py`, **Task 7** `trading.py`, **Task 8** `factors.py`, **Task 9** `market.py`.

**Per-module import headers** (start from these; the test in Step 3 will surface any missing/extra import immediately as `NameError`/`ImportError`):

```python
# research.py
import logging
import pandas as pd
import yfinance as yf
from stock_agent.market_data import get_historical_bars
from stock_agent.tools._shared import _avg_return
logger = logging.getLogger(__name__)
```

```python
# strategy_health.py
import logging
from datetime import datetime, timedelta
import pandas as pd
import yfinance as yf
from stock_agent.db import read_memory, write_memory as db_write_memory, get_equity_snapshots
from stock_agent.market_data import get_sp500_sp400_tickers
from stock_agent.tools._shared import _load_factor_weights
logger = logging.getLogger(__name__)
```

```python
# reports.py
import html
import logging
import os
from datetime import datetime, timedelta
import httpx
from langgraph_sdk import get_sync_client
from stock_agent.db import (read_journal, read_memory, get_equity_snapshots,
                            record_equity_snapshot as db_record_equity_snapshot,
                            get_risk_settings)
from stock_agent.alpaca_client import get_trading_client
from stock_agent.market_data import get_portfolio, get_quote, get_historical_bars
logger = logging.getLogger(__name__)
```

```python
# memory.py
import logging
from datetime import datetime
from stock_agent.db import (read_memory, read_all_memory, write_memory as db_write_memory,
                            write_journal as db_write_journal, add_to_watchlist,
                            remove_from_watchlist, get_watchlist)
from stock_agent.supabase_client import get_supabase
logger = logging.getLogger(__name__)
```

```python
# trading.py
import logging
from alpaca.trading.requests import (MarketOrderRequest, LimitOrderRequest,
                                      TakeProfitRequest, StopLossRequest)
from alpaca.trading.enums import OrderSide, TimeInForce, OrderClass
from stock_agent.alpaca_client import get_trading_client
from stock_agent.db import create_trade, update_trade, get_trades, get_risk_settings
from stock_agent.market_data import get_portfolio, get_quote, get_historical_bars
from stock_agent.risk import check_risk
logger = logging.getLogger(__name__)
```

```python
# factors.py
import logging
import time
from datetime import datetime, timedelta
import pandas as pd
import yfinance as yf
from stock_agent.db import (read_memory, write_memory as db_write_memory,
                            get_watchlist, get_finnhub_news_or_similar_if_used)  # prune to actual usage
from stock_agent.market_data import (get_sp500_sp400_tickers, get_quote, get_historical_bars)
from stock_agent.finnhub_client import get_finnhub
from stock_agent.tools._shared import _load_factor_weights
logger = logging.getLogger(__name__)
_FACTOR_CACHE_TTL = 14400  # 4 hours
_factor_cache: dict = {"data": None, "timestamp": 0.0}
```

```python
# market.py
import logging
import os
import httpx
import pandas as pd
import yfinance as yf
from tavily import TavilyClient
from stock_agent.market_data import (get_quote, get_historical_bars,
                                     get_historical_data_dict, get_sp500_sp400_tickers)
from stock_agent.finnhub_client import get_finnhub
from stock_agent.technical import compute_indicators
from stock_agent.tools._shared import _avg_return
logger = logging.getLogger(__name__)
```

> The factors.py db import line above contains a deliberate placeholder (`get_finnhub_news_or_similar_if_used`) — replace the db import list with the exact names the moved bodies reference. Run the test; any `NameError` names the missing import. Prune unused imports from every header before committing the module (pyflakes/ruff if available: `ruff check src/stock_agent/tools/<MOD>.py`).

---

### Task 10: Rebuild `__init__.py` as a thin assembler

By now `tools/__init__.py` contains only: the import lines added in Tasks 2–9, the original top-of-file imports, and the two list literals (`AUTONOMOUS_TOOLS` orig 4553–4606, `CHAT_TOOLS` orig 4636–4648). No function bodies remain.

**Files:**
- Modify: `agent/src/stock_agent/tools/__init__.py`

- [ ] **Step 1: Reduce the header to only what the lists need.** Replace the whole top of the file with explicit submodule imports:

```python
"""Stock Agent tools — autonomous-mode and chat-mode.

Public surface preserved from the pre-split tools.py: AUTONOMOUS_TOOLS,
CHAT_TOOLS, and the individual tool functions (importable directly).
"""

from stock_agent.market_data import get_sp500_sp400_tickers  # re-export for backtest/data.py

from stock_agent.tools.market import (
    internet_search, get_stock_quote, get_historical_data, technical_analysis,
    fundamental_analysis, screen_stocks, company_profile, sector_analysis,
    peer_comparison, earnings_calendar, eps_estimates, market_breadth,
)
from stock_agent.tools.trading import (
    place_order, cancel_order, get_open_orders, get_portfolio_state,
    reconcile_positions, check_trade_risk, get_my_portfolio,
    attach_bracket_to_position,
)
from stock_agent.tools.memory import (
    read_agent_memory, read_all_agent_memory, write_agent_memory,
    write_journal_entry, update_market_regime, update_stock_analysis,
    record_decision, manage_watchlist, query_database, submit_user_insight,
)
from stock_agent.tools.reports import (
    send_daily_recap, send_daily_subscription_emails, send_weekly_cycle_report,
    record_daily_snapshot, get_performance_comparison, position_health_check,
)
from stock_agent.tools.research import (
    assess_ai_bubble_risk, assess_ai_cycle_durability,
)
from stock_agent.tools.strategy_health import (
    audit_factor_ic, check_live_vs_backtest_divergence,
    suggest_factor_weight_adjustment,
)
from stock_agent.tools.factors import (
    score_universe, enrich_eps_revisions, generate_factor_rankings,
    check_watchlist_alerts, discover_catalysts, get_earnings_results,
)
```

- [ ] **Step 2: Keep the two list literals exactly as they were** (`AUTONOMOUS_TOOLS = [...]`, `CHAT_TOOLS = [...]`). They reference the names now imported above. Delete any now-dead leftover imports (yfinance, httpx, etc.) from `__init__.py` — it should import nothing it doesn't use.

- [ ] **Step 3: Verify the surface**

Run the surface-diff command from Task 1 Step 2.
Expected: `SURFACE OK`.

- [ ] **Step 4: Verify downstream importers still resolve**

Run:
```bash
cd agent && python -c "import backtest.data" \
  && python -c "import importlib; importlib.import_module('scripts.seed_earnings_profiles')" 2>&1 | head -5 \
  && python -c "from stock_agent.tools import AUTONOMOUS_TOOLS, CHAT_TOOLS; print(len(AUTONOMOUS_TOOLS), len(CHAT_TOOLS))"
```
Expected: prints the two counts (47 and 11 unless the lists changed); no ImportError. `seed_earnings_profiles` may error on missing env at runtime — that's fine; we only care that the *import* of `get_earnings_results` resolves (no ImportError on that line).

- [ ] **Step 5: Lint for orphans (if ruff available)**

Run: `cd agent && ruff check src/stock_agent/tools/ 2>/dev/null || echo "ruff not installed, skipping"`
Expected: no unused-import (F401) errors in the submodules. Fix any by pruning.

- [ ] **Step 6: Commit**

```bash
cd agent && git add -A && git commit -m "refactor(tools): rebuild __init__ as thin tool-list assembler"
```

---

### Task 11: Verify both graphs load end-to-end

**Files:** none (verification only)

- [ ] **Step 1: Confirm the running `langgraph dev` reloaded cleanly**

The dev server watches files and reloads on change. After the final commit, check its log for a successful re-import of both graphs and no traceback:

Run: `grep -iE "error|traceback|Importing graph|Application startup" /tmp/<langgraph-dev-output>.log | tail -20`
Expected: `Importing graph` entries for `monet_agent` and `autonomous_loop`, no `Traceback`. (If the dev server isn't running, start it: `cd agent && langgraph dev --no-browser` and watch startup.)

- [ ] **Step 2: Smoke-test the agent endpoint**

Run: `curl -s -o /dev/null -w "%{http_code}\n" http://127.0.0.1:2024/ok`
Expected: `200`.

- [ ] **Step 3: Final surface check**

Run the surface-diff command from Task 1 Step 2.
Expected: `SURFACE OK`.

---

## Self-Review notes

- **Spec coverage:** every function from the original `tools.py` (60 defs + constants) is assigned to exactly one module in the File Structure table; `AUTONOMOUS_TOOLS`/`CHAT_TOOLS` rebuilt in `__init__`; the two external importers (`backtest/data.py`, `scripts/seed_earnings_profiles.py`) covered by re-exports + Task 10 Step 4.
- **No behavior change:** bodies move verbatim; only edits are (a) `from .factor_scoring` → `from ..factor_scoring` in moved bodies, (b) import headers, (c) `__init__` assembly.
- **Cycle safety:** submodules import only `_shared` + non-`tools` modules; enforced by the dependency rule and caught by `test_package_imports_cleanly`.
- **Known soft spot:** the per-module import headers are best-effort; the characterization test + `ruff` are the mechanism that finalizes them. The `factors.py` db-import placeholder is called out explicitly to be replaced.
