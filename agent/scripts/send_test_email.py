"""One-off: send a single daily-digest test email to a chosen address.

Reuses the live data-gathering + builder from tools.py, but sends to ONE
recipient via Resend and does NOT touch email_subscriptions / last_sent_at.
"""
import os
import sys

import httpx
from dotenv import load_dotenv

load_dotenv(os.path.join(os.path.dirname(__file__), "..", ".env"))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from datetime import datetime

from stock_agent.tools import (  # noqa: E402
    _build_subscription_email,
    get_equity_snapshots,
    get_portfolio,
    get_supabase,
)

RECIPIENT = sys.argv[1] if len(sys.argv) > 1 else "leyuan.ly@gmail.com"
STARTING_EQUITY = 100_000


def read_mem(sb, key: str) -> dict:
    try:
        r = sb.table("agent_memory").select("value").eq("key", key).maybe_single().execute()
        return (r.data or {}).get("value", {}) if r and r.data else {}
    except Exception:
        return {}


def main() -> None:
    resend_api_key = os.environ["RESEND_API_KEY"]
    from_email = os.environ["DAILY_RECAP_FROM_EMAIL"]

    sb = get_supabase()
    today = datetime.now()
    today_label = today.strftime("%A, %B %-d, %Y")
    today_start = today.strftime("%Y-%m-%d")

    # Reflection + trades (today)
    refl = (
        sb.table("agent_journal").select("title, content, created_at")
        .eq("entry_type", "reflection").gte("created_at", f"{today_start}T00:00:00")
        .order("created_at", desc=True).limit(1).execute()
    )
    reflection = refl.data[0] if refl.data else None

    tr = (
        sb.table("trades")
        .select("symbol, side, quantity, filled_quantity, filled_avg_price, limit_price, portfolio, created_at")
        .gte("created_at", f"{today_start}T00:00:00").order("created_at", desc=True).limit(8).execute()
    )
    trades = [
        {"portfolio": t.get("portfolio", "quant"), "side": t.get("side"), "symbol": t.get("symbol"),
         "qty": t.get("filled_quantity") or t.get("quantity"),
         "price": t.get("filled_avg_price") or t.get("limit_price")}
        for t in (tr.data or [])
    ]

    # Per-book metrics (mirror tools.py)
    try:
        pa = sb.table("agent_memory").select("value").eq("key", "performance_adjustments").maybe_single().execute()
        perf_adj = (pa.data or {}).get("value", {}).get("adjustments", []) if pa and pa.data else []
    except Exception:
        perf_adj = []

    def book(name: str, slug: str) -> dict:
        try:
            p = get_portfolio(slug)
        except Exception as e:
            print(f"  ! get_portfolio({slug}) failed: {e}")
            return {"name": name, "equity": None, "daily_pnl": None, "return_pct": None,
                    "spy_pct": None, "alpha_pct": None, "adjustment": 0}
        mine = [a for a in perf_adj if (a.get("portfolio") or "quant") == slug]
        adj_total = sum(float(a.get("amount") or 0) for a in mine)
        adj_today = sum(float(a.get("amount") or 0) for a in mine if a.get("date") == today_start)
        eq = p.get("equity")
        eq_adj = (eq + adj_total) if eq else eq
        ret = round((eq_adj - STARTING_EQUITY) / STARTING_EQUITY * 100, 2) if eq_adj else None
        spy = None
        try:
            snaps = get_equity_snapshots(days=1, portfolio=slug)
            if snaps:
                spy = snaps[0].get("spy_cumulative_return")
        except Exception:
            pass
        alpha = round(ret - spy, 2) if (ret is not None and spy is not None) else None
        daily = (p.get("daily_pnl") or 0) + adj_today
        return {"name": name, "equity": eq_adj, "daily_pnl": daily, "return_pct": ret,
                "spy_pct": spy, "alpha_pct": alpha, "adjustment": adj_total}

    books = [book("Quant Core", "quant"), book("Conviction", "conviction")]

    dur, cap, bub = read_mem(sb, "ai_cycle_durability"), read_mem(sb, "ai_capex_tracker"), read_mem(sb, "ai_bubble_risk")
    cycle = None
    if dur or cap or bub:
        cycle = {"phase_label": dur.get("phase_label"), "score": dur.get("score"),
                 "capex_direction": cap.get("guidance_direction"), "hyperscaler_yoy": cap.get("hyperscaler_total_yoy"),
                 "heat_level": bub.get("level"), "heat_score": bub.get("score")}

    sig = read_mem(sb, "ai_cycle_signals")
    cycle_signals = sig if (sig and sig.get("signals")) else None

    email_data = {"today_label": today_label, "books": books, "cycle": cycle,
                  "cycle_signals": cycle_signals, "trades": trades, "reflection": reflection}

    # Subject (mirror tools.py)
    try:
        short_date = today.strftime("%b %-d")
    except Exception:
        short_date = today_label
    subject = f"Monet Daily Digest - {today_label}"
    top = (cycle_signals or {}).get("signals") or []
    if top and (hl := (top[0].get("headline") or "").strip()):
        if len(hl) > 64:
            hl = hl[:63].rsplit(" ", 1)[0].rstrip(",.;:—- ") + "…"
        subject = f"Monet · {hl} · {short_date}"

    print("Recipient :", RECIPIENT)
    print("From      :", from_email)
    print("Subject   :", subject)
    print("Books     :", [(b["name"], b["equity"], b["return_pct"]) for b in books])
    print("Cycle     :", "yes" if cycle else "none")
    print("Signals   :", len(top))
    print("Trades    :", len(trades), " Reflection:", "yes" if reflection else "none")

    html_body, text_body = _build_subscription_email(email_data, recipient_email=RECIPIENT)

    with httpx.Client(timeout=20.0) as client:
        resp = client.post(
            "https://api.resend.com/emails",
            headers={"Authorization": f"Bearer {resend_api_key}", "Content-Type": "application/json"},
            json={"from": from_email, "to": [RECIPIENT], "subject": f"[TEST] {subject}",
                  "html": html_body, "text": text_body},
        )
        resp.raise_for_status()
        print("\nSent ✓  Resend id:", resp.json().get("id"))


if __name__ == "__main__":
    main()
