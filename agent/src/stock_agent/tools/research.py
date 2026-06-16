"""AI-cycle and bubble-risk research tools."""

import logging
from datetime import datetime, timedelta

import pandas as pd
import yfinance as yf

from common.supabase_client import get_supabase

logger = logging.getLogger(__name__)

AI_SEMI_BASKET = {
    "NVDA", "AMD", "AVGO", "MU", "WDC", "AMAT", "LRCX", "STX",
    "TSM", "CRUS", "SMCI", "INTC", "ARM", "MRVL", "QCOM", "TXN",
}



def _rsi(closes: "pd.Series", period: int = 14) -> float:
    """Compute RSI for a price series."""
    delta = closes.diff()
    gain = delta.clip(lower=0).rolling(period).mean()
    loss = (-delta.clip(upper=0)).rolling(period).mean()
    rs = gain / loss
    return float((100 - 100 / (1 + rs)).iloc[-1])



def assess_ai_bubble_risk() -> dict:
    """Assess AI/semiconductor sector heat using pure market signals.

    Three components — all derived from market data, not from what Monet holds:

    1. SMH technical overextension (0-40 pts):
       - RSI(14) component: RSI ≤ 65 = 0 pts; 65→85 linearly = 0→20 pts
       - 200-day MA gap component: ≤10% above = 0 pts; 10%→35% = 0→20 pts

    2. AI basket breadth (0-30 pts): % of basket stocks within 10% of 52-week high.
       - ≤50% near highs = 0 pts; 50%→100% linearly = 0→30 pts

    3. Valuation stretch (0-30 pts): NVDA NTM P/E vs pre-AI-boom baseline of 35x.
       - ≤35x = 0 pts; 35x→70x linearly = 0→30 pts; falls back to AMD if unavailable

    Returns:
        Dict with score (0-100), level, smh_rsi, smh_vs_200ma_pct,
        basket_breadth_pct, nvda_forward_pe, action, and as_of timestamp.
    """
    score = 0

    # --- Component 1: SMH technical overextension (0-40 pts) ---
    smh_rsi: float = 0.0
    smh_vs_200ma_pct: float = 0.0
    try:
        end = datetime.now()
        start = end - timedelta(days=300)  # enough for 200-day MA + RSI warmup
        smh_hist = yf.download(
            "SMH",
            start=start.strftime("%Y-%m-%d"),
            end=end.strftime("%Y-%m-%d"),
            progress=False,
            auto_adjust=True,
        )["Close"].squeeze()

        smh_rsi = round(_rsi(smh_hist), 1)
        ma200 = float(smh_hist.rolling(200).mean().iloc[-1])
        current = float(smh_hist.iloc[-1])
        smh_vs_200ma_pct = round((current / ma200 - 1) * 100, 1)

        # RSI sub-score: 0 below 65, linear 65→85 = 0→20
        rsi_pts = min(20, max(0, round((smh_rsi - 65) / 20 * 20)))
        # 200MA gap sub-score: 0 below 10%, linear 10%→35% = 0→20
        ma_pts = min(20, max(0, round((smh_vs_200ma_pct - 10) / 25 * 20)))
        score += rsi_pts + ma_pts
    except Exception:
        pass

    # --- Component 2: Basket breadth — % near 52-week highs (0-30 pts) ---
    basket_breadth_pct: float = 0.0
    try:
        end = datetime.now()
        start = end - timedelta(days=370)  # 52-week window + buffer
        basket_hist = yf.download(
            list(AI_SEMI_BASKET),
            start=start.strftime("%Y-%m-%d"),
            end=end.strftime("%Y-%m-%d"),
            progress=False,
            auto_adjust=True,
        )["Close"]

        near_high_count = 0
        valid_count = 0
        for sym in AI_SEMI_BASKET:
            if sym not in basket_hist.columns:
                continue
            series = basket_hist[sym].dropna()
            if len(series) < 20:
                continue
            valid_count += 1
            high_52w = float(series.max())
            current_price = float(series.iloc[-1])
            if current_price >= high_52w * 0.90:  # within 10% of 52-week high
                near_high_count += 1

        if valid_count > 0:
            basket_breadth_pct = round(near_high_count / valid_count * 100, 1)
            # Linear: 50%→100% = 0→30 pts
            breadth_pts = min(30, max(0, round((basket_breadth_pct - 50) / 50 * 30)))
            score += breadth_pts
    except Exception:
        pass

    # --- Component 3: Valuation stretch — NVDA NTM P/E vs 35x baseline (0-30 pts) ---
    nvda_forward_pe: float | None = None
    try:
        for bellwether in ["NVDA", "AMD"]:
            info = yf.Ticker(bellwether).info
            pe = info.get("forwardPE")
            if pe and pe > 0:
                nvda_forward_pe = round(float(pe), 1)
                break

        if nvda_forward_pe is not None:
            # Linear: 35x→70x = 0→30 pts; below 35x = 0
            val_pts = min(30, max(0, round((nvda_forward_pe - 35) / 35 * 30)))
            score += val_pts
    except Exception:
        pass

    # --- Determine level and action ---
    score = min(100, score)
    if score <= 30:
        level = "low"
        action = "Sector heat is low. No constraints on AI/semi BUYs."
    elif score <= 60:
        level = "moderate"
        action = "Sector moderately extended. Note in journal."
    elif score <= 80:
        level = "elevated"
        action = "Sector overheated. Note 'AI sector elevated (score: X)' in Step 5 journal recap."
    else:
        level = "high"
        action = "Sector at high heat. Limit new AI-basket BUYs to 1 this run."

    return {
        "score": score,
        "level": level,
        "smh_rsi": smh_rsi,
        "smh_vs_200ma_pct": smh_vs_200ma_pct,
        "basket_breadth_pct": basket_breadth_pct,
        "nvda_forward_pe": nvda_forward_pe,
        "action": action,
        "as_of": datetime.now().isoformat(),
    }


# ============================================================
# AI Cycle Durability Assessment
# ============================================================

# Stock baskets for each AI infrastructure layer

AI_CYCLE_LAYERS = {
    "Compute": ["NVDA", "AMD", "AVGO", "ARM", "TSM"],
    "Memory": ["MU", "WDC", "STX"],
    "Power": ["ETN", "VRT", "VST"],
    "Networking": ["ANET", "CSCO"],
    "Equipment": ["AMAT", "LRCX", "KLAC"],
}



def assess_ai_cycle_durability() -> dict:
    """Assess AI capex cycle durability — how much runway the buildout has left.

    Companion to assess_ai_bubble_risk (which measures heat/stretch).
    This measures whether the underlying investment cycle is healthy and broadening.

    Five signals, each 0-20 pts = 0-100 total:

    1. Stack breadth (0-20): How many AI stack layers outperform SPY over 3 months?
       5 layers (Compute, Memory, Power, Networking, Equipment) × 4 pts each.

    2. Infra momentum (0-20): Power/cooling plays (ETN, VRT, VST) avg 3-month
       return vs SPY. >0% outperformance starts scoring; 20%+ = full marks.

    3. Memory demand (0-20): MU 3-month return vs SPY as proxy for HBM pricing.
       0% outperformance = 0; 25%+ = full marks.

    4. Equipment demand (0-20): Semi-equipment (AMAT, LRCX, KLAC) avg 3-month
       return vs SPY. 0% = 0; 20%+ = full marks.

    5. Capex signal (0-20): From ai_capex_tracker memory (quarterly manual update).
       accelerating = 20, stable = 12, decelerating = 4, unknown = 10.

    Cycle phases:
      75-100 = "Full Build"  — all layers firing, capex accelerating
      50-74  = "Expanding"   — most layers participating, strong demand
      25-49  = "Maturing"    — narrowing participation, watch for turns
      0-24   = "Cooling"     — cycle winding down, be selective

    Returns:
        Dict with score, phase, layer details, sub-signal values, and as_of.
    """
    import yfinance as yf

    score = 0
    details: dict = {}

    # ── Helper: 3-month return for a list of tickers ──
    end = datetime.now()
    start_3m = end - timedelta(days=95)  # ~3 months with buffer

    def _avg_return(symbols: list[str], period_start=start_3m, period_end=end) -> float | None:
        """Average 3-month return for a basket of symbols. Returns pct or None."""
        try:
            hist = yf.download(
                symbols,
                start=period_start.strftime("%Y-%m-%d"),
                end=period_end.strftime("%Y-%m-%d"),
                progress=False,
                auto_adjust=True,
            )["Close"]
            if len(symbols) == 1:
                hist = hist.to_frame(symbols[0]) if hasattr(hist, "to_frame") else hist
            returns = []
            cols = [symbols[0]] if len(symbols) == 1 else hist.columns
            for sym in cols:
                series = hist[sym].dropna() if sym in hist.columns else hist.dropna()
                if len(series) < 10:
                    continue
                ret = (float(series.iloc[-1]) / float(series.iloc[0]) - 1) * 100
                returns.append(ret)
            return round(sum(returns) / len(returns), 1) if returns else None
        except Exception:
            return None

    # ── SPY benchmark return ──
    spy_return = _avg_return(["SPY"])
    if spy_return is None:
        spy_return = 0.0

    # ── Signal 1: Stack Breadth (0-20 pts) ──
    # 5 layers × 4 pts each for outperforming SPY
    layers_participating = 0
    layer_details: dict[str, dict] = {}
    for layer_name, symbols in AI_CYCLE_LAYERS.items():
        layer_ret = _avg_return(symbols)
        outperforming = layer_ret is not None and layer_ret > spy_return
        layer_details[layer_name] = {
            "return_3m_pct": layer_ret,
            "vs_spy_pct": round(layer_ret - spy_return, 1) if layer_ret is not None else None,
            "participating": outperforming,
        }
        if outperforming:
            layers_participating += 1

    breadth_pts = layers_participating * 4
    score += breadth_pts
    details["stack_breadth"] = {
        "score": breadth_pts,
        "layers_participating": layers_participating,
        "total_layers": len(AI_CYCLE_LAYERS),
        "layers": layer_details,
    }

    # ── Signal 2: Infra Momentum (0-20 pts) ──
    infra_return = _avg_return(AI_CYCLE_LAYERS["Power"])
    infra_vs_spy = round(infra_return - spy_return, 1) if infra_return is not None else 0.0
    infra_pts = min(20, max(0, round(infra_vs_spy / 20 * 20)))
    score += infra_pts
    details["infra_momentum"] = {
        "score": infra_pts,
        "return_3m_pct": infra_return,
        "vs_spy_pct": infra_vs_spy,
        "tickers": AI_CYCLE_LAYERS["Power"],
    }

    # ── Signal 3: Memory Demand (0-20 pts) ──
    mu_return = _avg_return(["MU"])
    mu_vs_spy = round(mu_return - spy_return, 1) if mu_return is not None else 0.0
    memory_pts = min(20, max(0, round(mu_vs_spy / 25 * 20)))
    score += memory_pts
    details["memory_demand"] = {
        "score": memory_pts,
        "mu_return_3m_pct": mu_return,
        "vs_spy_pct": mu_vs_spy,
    }

    # ── Signal 4: Equipment Demand (0-20 pts) ──
    equip_return = _avg_return(AI_CYCLE_LAYERS["Equipment"])
    equip_vs_spy = round(equip_return - spy_return, 1) if equip_return is not None else 0.0
    equip_pts = min(20, max(0, round(equip_vs_spy / 20 * 20)))
    score += equip_pts
    details["equipment_demand"] = {
        "score": equip_pts,
        "return_3m_pct": equip_return,
        "vs_spy_pct": equip_vs_spy,
        "tickers": AI_CYCLE_LAYERS["Equipment"],
    }

    # ── Signal 5: Capex Signal (0-20 pts) ──
    # Read from ai_capex_tracker memory (quarterly manual update by agent/user)
    capex_direction = "unknown"
    capex_detail = "No capex tracker data — update ai_capex_tracker after earnings."
    try:
        sb = get_supabase()
        cap_row = (
            sb.table("agent_memory")
            .select("value")
            .eq("key", "ai_capex_tracker")
            .maybe_single()
            .execute()
        )
        if cap_row.data and cap_row.data.get("value"):
            tracker = cap_row.data["value"]
            capex_direction = tracker.get("guidance_direction", "unknown")
            capex_detail = tracker.get("summary", capex_detail)
    except Exception:
        pass

    capex_scores = {"accelerating": 20, "stable": 12, "decelerating": 4, "unknown": 10}
    capex_pts = capex_scores.get(capex_direction, 10)
    score += capex_pts
    details["capex_signal"] = {
        "score": capex_pts,
        "direction": capex_direction,
        "detail": capex_detail,
    }

    # ── Phase determination ──
    score = min(100, score)
    if score >= 75:
        phase = "full_build"
        outlook = "All layers firing. Cycle has strong runway — new AI infra positions supported."
    elif score >= 50:
        phase = "expanding"
        outlook = "Most layers participating. Cycle healthy — favor picks-and-shovels plays."
    elif score >= 25:
        phase = "maturing"
        outlook = "Participation narrowing. Be selective — prefer leaders with pricing power."
    else:
        phase = "cooling"
        outlook = "Cycle winding down. Avoid new capex-cycle entries — focus on AI software/services."

    result = {
        "score": score,
        "phase": phase,
        "phase_label": phase.replace("_", " ").title(),
        "outlook": outlook,
        "spy_return_3m_pct": spy_return,
        "signals": details,
        "as_of": datetime.now().isoformat(),
    }

    # Persist to agent_memory for dashboard card
    try:
        sb = get_supabase()
        sb.table("agent_memory").upsert(
            {"key": "ai_cycle_durability", "value": result},
            on_conflict="key",
        ).execute()
    except Exception:
        pass

    return result


# ============================================================
# Tier 1 Monitoring: Factor IC drift + live vs backtest divergence
# ============================================================

