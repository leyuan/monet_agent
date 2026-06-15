"""Reporting tools: daily recap, subscription + weekly emails, equity snapshot, performance comparison, position health."""

import html
import logging
import os
from datetime import datetime

import httpx
import yfinance as yf
from langgraph_sdk import get_sync_client

from stock_agent.db import (
    get_equity_snapshots,
    get_risk_settings,
    read_memory,
    record_equity_snapshot as db_record_equity_snapshot,
)
from stock_agent.market_data import get_historical_bars, get_portfolio, get_quote
from stock_agent.supabase_client import get_supabase

logger = logging.getLogger(__name__)

def send_daily_recap() -> dict:
    """Send a daily trade recap to the chat tab for the user to read.

    Creates a new thread on the chat graph and triggers a run that queries
    today's journal entries and generates a concise recap. The recap appears
    as a new conversation in the chat tab.

    Call this at the very end of the 4 PM reflection phase (weekdays only).

    Returns:
        Dict with thread_id and status.
    """
    today = datetime.now().strftime("%A, %B %-d")

    recap_prompt = (
        f"Today is {today}. Generate a daily recap for sharing.\n\n"
        "Query today's journal entries and trades:\n"
        "```sql\n"
        "SELECT entry_type, title, content, symbols, created_at\n"
        "FROM agent_journal WHERE created_at >= CURRENT_DATE ORDER BY created_at\n"
        "```\n"
        "```sql\n"
        "SELECT symbol, side, quantity, order_type, limit_price, status, thesis, confidence\n"
        "FROM trades WHERE created_at >= CURRENT_DATE ORDER BY created_at\n"
        "```\n\n"
        "Write a SHORT recap (aim for ~150 words). This will be screenshotted and shared.\n"
        "Format:\n"
        "1. **Market** — regime, VIX, sector rotation (1-2 sentences)\n"
        "2. **Research** — what you analyzed and key findings (2-3 sentences)\n"
        "3. **Trades** — what you bought/sold/passed on and why (1-2 sentences)\n"
        "4. **Watching** — 2-3 tickers and what you're waiting for\n\n"
        "No self-reflection, no improvement notes, no verbose explanations. "
        "Be punchy and specific — numbers, tickers, prices. "
        "Think investor newsletter, not diary entry."
    )

    try:
        langgraph_url = os.environ.get(
            "LANGGRAPH_URL",
            "https://monet-0f211e9ce05255c2a85f92d6847873b5.us.langgraph.app",
        )
        api_key = os.environ.get("LANGGRAPH_API_KEY") or os.environ.get("LANGSMITH_API_KEY")
        client = get_sync_client(url=langgraph_url, api_key=api_key)
        # Owner must match the frontend user's Supabase ID so the thread
        # appears in their chat conversation list.
        owner_id = os.environ.get("RECAP_OWNER_ID", "593fa090-4515-4a02-a79b-8462c7266999")
        thread = client.threads.create(
            metadata={"title": f"Daily Recap — {today}", "owner": owner_id},
        )
        client.runs.create(
            thread["thread_id"],
            assistant_id="monet_agent",
            input={"messages": [
                {"role": "system", "content": recap_prompt},
                {"role": "user", "content": f"Give me today's daily recap ({today})."},
            ]},
        )
        return {
            "thread_id": thread["thread_id"],
            "status": "recap_triggered",
            "message": f"Daily recap thread created. It will appear in the chat tab shortly.",
        }
    except Exception as e:
        logger.error(f"Failed to send daily recap: {e}")
        return {"status": "error", "error": str(e)}



def _fmt_currency(value: float | None) -> str:
    if value is None:
        return "N/A"
    return f"${value:,.0f}"



def _fmt_pct(value: float | None) -> str:
    if value is None:
        return "N/A"
    return f"{value:+.2f}%"



def _inline_bold(text: str) -> str:
    """Convert **bold** to <strong> tags."""
    import re
    return re.sub(r"\*\*(.+?)\*\*", r"<strong>\1</strong>", html.escape(text))



def _markdown_to_html(lines: list[str]) -> str:
    """Convert markdown lines to email-safe HTML (headings, bullets, tables, paragraphs)."""
    out: list[str] = []
    i = 0
    while i < len(lines):
        line = lines[i]

        # ## Heading
        if line.startswith("#"):
            import re
            text = re.sub(r"^#{1,3}\s+", "", line)
            out.append(
                f"<p style='margin:18px 0 8px 0; font-size:15px; font-weight:700; color:#111827;'>"
                f"{_inline_bold(text)}</p>"
            )
            i += 1
            continue

        # Table block
        if line.startswith("|") and line.endswith("|"):
            cells = [c.strip() for c in line.split("|")[1:-1]]
            # skip separator
            j = i + 1
            import re
            while j < len(lines) and re.match(r"^\|[\s\-:|]+\|$", lines[j]):
                j += 1
            rows: list[list[str]] = []
            while j < len(lines) and lines[j].startswith("|") and lines[j].endswith("|"):
                rows.append([c.strip() for c in lines[j].split("|")[1:-1]])
                j += 1
            th = "".join(
                f"<th style='padding:4px 8px; font-size:12px; font-weight:700; color:#111827; "
                f"background:#f9fafb; border-bottom:2px solid #d1d5db; text-align:left;'>"
                f"{html.escape(c)}</th>"
                for c in cells
            )
            body = ""
            for row in rows:
                tds = "".join(
                    f"<td style='padding:4px 8px; font-size:12px; color:#374151; "
                    f"border-bottom:1px solid #e5e7eb;'>{_inline_bold(c)}</td>"
                    for c in row
                )
                body += f"<tr>{tds}</tr>"
            out.append(
                f"<table width='100%' cellpadding='0' cellspacing='0' "
                f"style='border-collapse:collapse; margin:8px 0 12px 0;'>"
                f"<thead><tr>{th}</tr></thead><tbody>{body}</tbody></table>"
            )
            i = j
            continue

        # Bullet
        if line.startswith("- ") or line.startswith("* "):
            text = line.lstrip("-* ")
            out.append(
                f"<p style='margin:0 0 4px 0; padding-left:12px; font-size:14px; "
                f"line-height:1.6; color:#374151;'>&bull;&nbsp;{_inline_bold(text)}</p>"
            )
            i += 1
            continue

        # Plain paragraph
        out.append(
            f"<p style='margin:0 0 12px 0; line-height:1.6; color:#374151;'>"
            f"{_inline_bold(line)}</p>"
        )
        i += 1

    return "".join(out)



def _build_subscription_email(
    today_label: str,
    reflection: dict | None,
    trades: list[dict],
    portfolio: dict | None,
    overall_return_pct: float | None,
    spy_return_pct: float | None,
    alpha_pct: float | None,
    recipient_email: str | None = None,
) -> tuple[str, str]:
    """Build HTML and plain-text daily recap email content.

    Args:
        today_label: Human-readable date string, e.g. "Tuesday, March 17, 2026".
        reflection: Today's journal reflection dict (title, content) or None.
        trades: List of today's trade dicts from the trades table.
        portfolio: Live portfolio dict from get_portfolio(), or None.
        overall_return_pct: Portfolio return since $100k inception (matches dashboard).
        spy_return_pct: SPY cumulative return since inception (from equity_snapshots).
        alpha_pct: overall_return_pct - spy_return_pct, or None if unavailable.
        recipient_email: Subscriber email used to generate a personalized unsubscribe link.
    """
    import urllib.parse

    reflection_body = (reflection or {}).get("content") or "No reflection entry was recorded today."
    lines = [line.strip() for line in reflection_body.splitlines() if line.strip()]

    latest_equity = portfolio.get("equity") if portfolio else None
    daily_pnl = portfolio.get("daily_pnl") if portfolio else None

    def _val_color(val: float | None) -> str:
        """Return green/red/dark based on sign of val."""
        if val is None:
            return "#111827"
        return "#16a34a" if val > 0 else ("#dc2626" if val < 0 else "#111827")

    def _metric_cell(label: str, value: str, val_color: str = "#111827") -> str:
        """Single metric card as a <td> for table-based 2x2 grid."""
        return (
            f"<td style='width:50%; padding:6px; vertical-align:top;'>"
            f"<div style='border:1px solid #e5e7eb; border-radius:14px; padding:14px 16px; background:#fafaf9;'>"
            f"<p style='margin:0; font-size:12px; color:#6b7280; text-transform:uppercase; letter-spacing:0.06em;'>"
            f"{html.escape(label)}</p>"
            f"<p style='margin:8px 0 0 0; font-size:22px; font-weight:700; color:{val_color};'>"
            f"{html.escape(value)}</p>"
            f"</div></td>"
        )

    # Trade lines — coalesce filled_avg_price → limit_price for both buys and sells
    trade_lines = []
    for trade in trades[:5]:
        qty = trade.get("filled_quantity") or trade.get("quantity")
        price = trade.get("filled_avg_price") or trade.get("limit_price")
        price_text = f" @ ${float(price):.2f}" if price else ""
        trade_lines.append(f"{trade.get('side', '').upper()} {qty} {trade.get('symbol', '')}{price_text}")

    # ── Plain-text version ───────────────────────────────────────────────────
    text_parts = [
        f"Monet Daily Recap — {today_label}",
        "",
        f"Portfolio equity : {_fmt_currency(latest_equity)}",
        f"Daily P&L        : {_fmt_currency(daily_pnl)}",
        f"Return           : {_fmt_pct(overall_return_pct)}",
        f"SPY return       : {_fmt_pct(spy_return_pct)}",
        f"Alpha vs SPY     : {_fmt_pct(alpha_pct)}",
        "",
        *lines,
    ]
    if trade_lines:
        text_parts.extend(["", "Today's trades:", *[f"  - {t}" for t in trade_lines]])
    app_url = os.environ.get("NEXT_APP_URL", "https://monet.app")
    if recipient_email:
        unsub_url = f"{app_url}/api/unsubscribe?email={urllib.parse.quote(recipient_email)}"
    else:
        unsub_url = f"{app_url}/unsubscribe"
    text_parts.extend(["", "---", f"Unsubscribe: {unsub_url}"])

    # ── HTML version ─────────────────────────────────────────────────────────
    html_paragraphs = _markdown_to_html(lines)

    trades_html = ""
    if trade_lines:
        items = "".join(
            f"<li style='margin-bottom:4px;'>{html.escape(t)}</li>" for t in trade_lines
        )
        trades_html = (
            "<div style='margin-top:20px;'>"
            "<p style='margin:0 0 8px 0; font-size:12px; font-weight:600; "
            "text-transform:uppercase; letter-spacing:0.06em; color:#6b7280;'>Today&rsquo;s trades</p>"
            f"<ul style='padding-left:20px; margin:0; color:#374151;'>{items}</ul>"
            "</div>"
        )

    # Metric grid — use <table> for email client compatibility (CSS Grid is not supported)
    metrics_html = (
        "<table width='100%' cellpadding='0' cellspacing='0' style='border-collapse:collapse;'>"
        "<tr>"
        + _metric_cell("Portfolio equity", _fmt_currency(latest_equity))
        + _metric_cell("Daily P&L", _fmt_currency(daily_pnl), _val_color(daily_pnl))
        + "</tr><tr>"
        + _metric_cell("Return", _fmt_pct(overall_return_pct), _val_color(overall_return_pct))
        + _metric_cell("Alpha vs SPY", _fmt_pct(alpha_pct), _val_color(alpha_pct))
        + "</tr></table>"
    )

    # Benchmark — always rendered; shows "—" when data is unavailable
    spy_display = _fmt_pct(spy_return_pct) if spy_return_pct is not None else "—"
    alpha_display = _fmt_pct(alpha_pct) if alpha_pct is not None else "—"
    benchmark_html = (
        "<div style='margin-top:20px; padding:16px 18px; border-radius:16px; background:#111827; color:#f9fafb;'>"
        "<p style='margin:0 0 10px 0; font-size:12px; text-transform:uppercase; "
        "letter-spacing:0.08em; color:#9ca3af;'>Benchmark</p>"
        "<table width='100%' cellpadding='0' cellspacing='0'>"
        "<tr>"
        f"<td style='color:#9ca3af; font-size:13px;'>SPY return</td>"
        f"<td style='text-align:right; font-size:15px; font-weight:700; color:#f9fafb;'>"
        f"{html.escape(spy_display)}</td>"
        "</tr><tr>"
        f"<td style='color:#9ca3af; font-size:13px; padding-top:8px;'>Monet alpha</td>"
        f"<td style='text-align:right; font-size:15px; font-weight:700; padding-top:8px; "
        f"color:{_val_color(alpha_pct) if alpha_pct is not None else '#9ca3af'};'>"
        f"{html.escape(alpha_display)}</td>"
        "</tr></table>"
        "</div>"
    )

    # Unsubscribe footer
    unsubscribe_html = (
        "<div style='margin-top:28px; padding-top:16px; border-top:1px solid #e5e7eb; text-align:center;'>"
        "<p style='margin:0; font-size:12px; color:#9ca3af;'>"
        "You&rsquo;re receiving this because you subscribed to Monet&rsquo;s daily recap.&nbsp;"
        f"<a href='{unsub_url}' style='color:#6b7280; text-decoration:underline;'>Unsubscribe</a>"
        "</p></div>"
    )

    html_body = (
        "<div style='font-family:Arial,sans-serif; max-width:680px; margin:0 auto; "
        "padding:28px 24px; color:#111827; background:#f4f1ea;'>"
        "<div style='background:#ffffff; border:1px solid #e7e0d2; border-radius:24px; padding:28px;'>"
        "<p style='margin:0 0 8px 0; font-size:12px; letter-spacing:0.08em; "
        "text-transform:uppercase; color:#6b7280;'>Monet daily recap</p>"
        f"<h1 style='margin:0 0 8px 0; font-size:28px; line-height:1.15; color:#111827;'>"
        f"Executive summary for {html.escape(today_label)}</h1>"
        "<p style='margin:0 0 20px 0; color:#6b7280; line-height:1.6;'>"
        "Your end-of-day investor brief with portfolio performance, benchmark context, "
        "and today&rsquo;s key takeaways.</p>"
        f"{metrics_html}"
        f"{benchmark_html}"
        "<div style='margin-top:24px; padding-top:22px; border-top:1px solid #e5e7eb;'>"
        "<p style='margin:0 0 12px 0; font-size:12px; text-transform:uppercase; "
        "letter-spacing:0.08em; color:#6b7280;'>Today&rsquo;s recap</p>"
        f"{html_paragraphs}"
        f"{trades_html}"
        "</div>"
        f"{unsubscribe_html}"
        "</div></div>"
    )

    return html_body, "\n".join(text_parts)



def send_daily_subscription_emails() -> dict:
    """Send the daily recap email to all active subscribers once per day."""
    resend_api_key = os.environ.get("RESEND_API_KEY")
    from_email = os.environ.get("DAILY_RECAP_FROM_EMAIL")

    if not resend_api_key or not from_email:
        return {
            "status": "skipped",
            "message": "Email delivery not configured. Set RESEND_API_KEY and DAILY_RECAP_FROM_EMAIL.",
        }

    sb = get_supabase()
    today = datetime.now()
    today_label = today.strftime("%A, %B %-d, %Y")
    today_start = today.strftime("%Y-%m-%d")

    try:
        subs_result = (
            sb.table("email_subscriptions")
            .select("id, email, last_sent_at")
            .eq("status", "active")
            .execute()
        )
        subscriptions = subs_result.data or []
        due_subscriptions = []
        for subscription in subscriptions:
            last_sent_at = subscription.get("last_sent_at")
            if not last_sent_at or str(last_sent_at)[:10] < today_start:
                due_subscriptions.append(subscription)

        if not due_subscriptions:
            return {"status": "ok", "sent": 0, "message": "No subscribers due for delivery."}

        reflection_result = (
            sb.table("agent_journal")
            .select("title, content, created_at")
            .eq("entry_type", "reflection")
            .gte("created_at", f"{today_start}T00:00:00")
            .order("created_at", desc=True)
            .limit(1)
            .execute()
        )
        reflection = reflection_result.data[0] if reflection_result.data else None

        trades_result = (
            sb.table("trades")
            .select("symbol, side, quantity, filled_quantity, filled_avg_price, limit_price, created_at")
            .gte("created_at", f"{today_start}T00:00:00")
            .order("created_at", desc=True)
            .limit(5)
            .execute()
        )
        trades = trades_result.data or []

        try:
            portfolio = get_portfolio()
        except Exception:
            logger.warning("Failed to load live portfolio for subscription email.")
            portfolio = None

        perf_result = get_performance_comparison(days=30)
        performance = None if perf_result.get("error") else perf_result

        # ── Compute metrics aligned with dashboard calculations ────────────────
        # Dashboard (PerformanceCard + BenchmarkCard) uses a hardcoded $100k
        # starting equity and live Alpaca equity, so we replicate that here.
        _STARTING_EQUITY = 100_000
        current_equity = portfolio.get("equity") if portfolio else None
        overall_return_pct: float | None = (
            round(((current_equity - _STARTING_EQUITY) / _STARTING_EQUITY) * 100, 2)
            if current_equity
            else None
        )
        # SPY return comes from equity_snapshots (inception-to-date).
        spy_return_pct: float | None = (
            performance.get("cumulative_spy_return") if performance else None
        )
        # Alpha: live portfolio return minus SPY (don't rely on stored alpha
        # which is NULL when deployed_pct ≤ 50% — dashboard always computes it).
        alpha_pct: float | None = (
            round(overall_return_pct - spy_return_pct, 2)
            if (overall_return_pct is not None and spy_return_pct is not None)
            else None
        )

        subject = f"Monet Daily Recap - {today_label}"
        sent_ids: list[str] = []

        with httpx.Client(timeout=20.0) as client:
            for subscription in due_subscriptions:
                # Build per-subscriber HTML so the unsubscribe link is personalised.
                html_body, text_body = _build_subscription_email(
                    today_label,
                    reflection,
                    trades,
                    portfolio,
                    overall_return_pct,
                    spy_return_pct,
                    alpha_pct,
                    recipient_email=subscription["email"],
                )
                response = client.post(
                    "https://api.resend.com/emails",
                    headers={
                        "Authorization": f"Bearer {resend_api_key}",
                        "Content-Type": "application/json",
                    },
                    json={
                        "from": from_email,
                        "to": [subscription["email"]],
                        "subject": subject,
                        "html": html_body,
                        "text": text_body,
                    },
                )
                response.raise_for_status()
                sent_ids.append(subscription["id"])

        if sent_ids:
            (
                sb.table("email_subscriptions")
                .update({"last_sent_at": datetime.now().isoformat()})
                .in_("id", sent_ids)
                .execute()
            )

        return {
            "status": "ok",
            "sent": len(sent_ids),
            "message": f"Sent daily recap email to {len(sent_ids)} subscribers.",
        }
    except Exception as e:
        logger.error("Failed to send daily subscription emails: %s", e)
        return {"status": "error", "error": str(e)}



def send_weekly_cycle_report(agent_commentary: str = "") -> dict:
    """Send the weekly AI cycle durability report to all active subscribers.

    Reads the latest ai_cycle_durability and ai_bubble_risk from agent_memory,
    renders the WeeklyCycleReportEmail template, and sends via Resend.

    Args:
        agent_commentary: Free-form commentary from the agent about what changed
            this week and what to watch for. Supports markdown bullet points.

    Returns:
        Dict with status, sent count, and any errors.
    """
    resend_api_key = os.environ.get("RESEND_API_KEY")
    from_email = os.environ.get("DAILY_RECAP_FROM_EMAIL")

    if not resend_api_key or not from_email:
        return {
            "status": "skipped",
            "message": "Email delivery not configured. Set RESEND_API_KEY and DAILY_RECAP_FROM_EMAIL.",
        }

    sb = get_supabase()
    today = datetime.now()
    week_label = today.strftime("%B %-d, %Y")

    try:
        # Fetch subscribers
        subs_result = (
            sb.table("email_subscriptions")
            .select("id, email")
            .eq("status", "active")
            .execute()
        )
        subscriptions = subs_result.data or []
        if not subscriptions:
            return {"status": "ok", "sent": 0, "message": "No active subscribers."}

        # Read cycle durability data
        cycle_row = (
            sb.table("agent_memory")
            .select("value")
            .eq("key", "ai_cycle_durability")
            .maybe_single()
            .execute()
        )
        cycle_data = cycle_row.data.get("value") if cycle_row.data else None
        if not cycle_data:
            return {"status": "skipped", "message": "No cycle durability data yet. Run assess_ai_cycle_durability first."}

        # Read heat data for companion context
        heat_row = (
            sb.table("agent_memory")
            .select("value")
            .eq("key", "ai_bubble_risk")
            .maybe_single()
            .execute()
        )
        heat_data = heat_row.data.get("value") if heat_row.data else {}

        # Read previous week's score for delta display
        prev_row = (
            sb.table("agent_memory")
            .select("value")
            .eq("key", "ai_cycle_durability_prev")
            .maybe_single()
            .execute()
        )
        prev_score = None
        if prev_row.data and prev_row.data.get("value"):
            prev_score = prev_row.data["value"].get("score")

        # Save current as prev for next week's delta
        sb.table("agent_memory").upsert(
            {"key": "ai_cycle_durability_prev", "value": {"score": cycle_data["score"], "as_of": today.isoformat()}},
            on_conflict="key",
        ).execute()

        signals = cycle_data.get("signals", {})
        stack = signals.get("stack_breadth", {})
        layers = stack.get("layers", {})

        app_url = os.environ.get("NEXT_APP_URL", "https://monet.app")
        subject = f"Monet AI Cycle Report — Week of {week_label}"
        sent_count = 0

        with httpx.Client(timeout=20.0) as client:
            for sub in subscriptions:
                import urllib.parse
                unsub_url = f"{app_url}/api/unsubscribe?email={urllib.parse.quote(sub['email'])}"

                # Build email payload for React Email renderer
                render_payload = {
                    "template": "weekly_cycle_report",
                    "weekLabel": week_label,
                    "cycleScore": cycle_data["score"],
                    "cyclePhaseLabel": cycle_data.get("phase_label", "Unknown"),
                    "cycleOutlook": cycle_data.get("outlook", ""),
                    "layersParticipating": stack.get("layers_participating", 0),
                    "totalLayers": stack.get("total_layers", 5),
                    "layers": layers,
                    "infraVsSpy": signals.get("infra_momentum", {}).get("vs_spy_pct"),
                    "memoryVsSpy": signals.get("memory_demand", {}).get("vs_spy_pct"),
                    "equipmentVsSpy": signals.get("equipment_demand", {}).get("vs_spy_pct"),
                    "capexDirection": signals.get("capex_signal", {}).get("direction", "unknown"),
                    "spyReturn3m": cycle_data.get("spy_return_3m_pct"),
                    "heatScore": heat_data.get("score"),
                    "heatLevel": heat_data.get("level"),
                    "prevCycleScore": prev_score,
                    "agentCommentary": agent_commentary,
                    "recipientEmail": sub["email"],
                }

                # Try React Email renderer first, fall back to plain HTML
                html_body = None
                text_body = None
                try:
                    render_resp = client.post(
                        f"{app_url}/api/email/render",
                        json=render_payload,
                        timeout=15.0,
                    )
                    if render_resp.status_code == 200:
                        rendered = render_resp.json()
                        html_body = rendered.get("html")
                        text_body = rendered.get("text")
                except Exception:
                    pass

                # Fallback plain text
                if not text_body:
                    text_body = (
                        f"Monet AI Cycle Report — {week_label}\n\n"
                        f"Cycle Durability: {cycle_data['score']} ({cycle_data.get('phase_label', '')})\n"
                        f"Sector Heat: {heat_data.get('score', '—')} ({heat_data.get('level', '—')})\n\n"
                        f"{cycle_data.get('outlook', '')}\n\n"
                        f"{agent_commentary}\n\n---\nUnsubscribe: {unsub_url}"
                    )
                if not html_body:
                    html_body = text_body.replace("\n", "<br>")

                response = client.post(
                    "https://api.resend.com/emails",
                    headers={
                        "Authorization": f"Bearer {resend_api_key}",
                        "Content-Type": "application/json",
                    },
                    json={
                        "from": from_email,
                        "to": [sub["email"]],
                        "subject": subject,
                        "html": html_body,
                        "text": text_body,
                    },
                )
                response.raise_for_status()
                sent_count += 1

        return {
            "status": "ok",
            "sent": sent_count,
            "message": f"Sent weekly cycle report to {sent_count} subscribers.",
        }
    except Exception as e:
        logger.error("Failed to send weekly cycle report: %s", e)
        return {"status": "error", "error": str(e)}


# ============================================================
# Bracket / Position Protection tools
# ============================================================


def record_daily_snapshot() -> dict:
    """Record today's portfolio equity and SPY close for benchmark tracking.

    Call this during EOD reflection (4 PM ET) to log a daily data point.
    Cumulative returns vs SPY are auto-computed from the first snapshot (inception).

    Returns:
        Dict with today's snapshot including portfolio return, SPY return, and alpha.
    """
    portfolio = get_portfolio()
    equity = float(portfolio.get("equity", 0))
    cash = float(portfolio.get("cash", 0))

    # Use yfinance for SPY close — Alpaca quotes return 0 bid/ask at market close
    try:
        spy_ticker = yf.Ticker("SPY")
        spy_hist = spy_ticker.history(period="1d")
        spy_close = round(float(spy_hist["Close"].iloc[-1]), 2) if not spy_hist.empty else 0.0
    except Exception:
        spy_close = 0.0

    # Fallback: try Alpaca quote if yfinance failed
    if spy_close == 0.0:
        spy_quote = get_quote("SPY")
        bid = float(spy_quote.get("bid_price", 0))
        ask = float(spy_quote.get("ask_price", 0))
        spy_close = round((bid + ask) / 2, 2) if bid and ask else 0.0

    today = datetime.now().strftime("%Y-%m-%d")
    snapshot = db_record_equity_snapshot(today, equity, cash, spy_close)

    return {
        "date": today,
        "portfolio_equity": equity,
        "spy_close": spy_close,
        "portfolio_cumulative_return": snapshot.get("portfolio_cumulative_return"),
        "spy_cumulative_return": snapshot.get("spy_cumulative_return"),
        "alpha": snapshot.get("alpha"),
    }



def get_performance_comparison(days: int = 30) -> dict:
    """Compare portfolio performance vs SPY over a given period.

    Uses daily equity snapshots recorded by record_daily_snapshot().
    Available in both autonomous and chat modes.

    Args:
        days: Number of days to look back (default 30).

    Returns:
        Dict with portfolio return, SPY return, alpha, max drawdown, and time series.
    """
    snapshots = get_equity_snapshots(days)
    if not snapshots:
        return {"error": "No equity snapshots yet. Snapshots are recorded during EOD reflection."}

    # Snapshots come newest-first, reverse for chronological
    snapshots = list(reversed(snapshots))

    latest = snapshots[-1]
    oldest = snapshots[0]

    # Period return (not cumulative from inception — just this window)
    oldest_equity = float(oldest["portfolio_equity"])
    latest_equity = float(latest["portfolio_equity"])
    oldest_spy = float(oldest["spy_close"])
    latest_spy = float(latest["spy_close"])

    period_portfolio_return = round((latest_equity / oldest_equity - 1) * 100, 2) if oldest_equity else 0
    period_spy_return = round((latest_spy / oldest_spy - 1) * 100, 2) if oldest_spy else 0
    period_alpha = round(period_portfolio_return - period_spy_return, 2)

    # Max drawdown
    peak = 0
    max_dd = 0
    for s in snapshots:
        eq = float(s["portfolio_equity"])
        peak = max(peak, eq)
        dd = (peak - eq) / peak * 100 if peak > 0 else 0
        max_dd = max(max_dd, dd)

    # Time series for charting
    series = [
        {
            "date": s["snapshot_date"],
            "portfolio": float(s.get("portfolio_cumulative_return") or 0),
            "spy": float(s.get("spy_cumulative_return") or 0),
            "alpha": float(s.get("alpha") or 0),
        }
        for s in snapshots
    ]

    return {
        "period_days": len(snapshots),
        "portfolio_return_pct": period_portfolio_return,
        "spy_return_pct": period_spy_return,
        "alpha_pct": period_alpha,
        "max_drawdown_pct": round(max_dd, 2),
        "latest_equity": latest_equity,
        "latest_date": latest["snapshot_date"],
        "cumulative_portfolio_return": float(latest.get("portfolio_cumulative_return") or 0),
        "cumulative_spy_return": float(latest.get("spy_cumulative_return") or 0),
        "cumulative_alpha": float(latest.get("alpha") or 0),
        "series": series,
    }


# ============================================================
# Position Management tools
# ============================================================


def position_health_check(symbol: str) -> dict:
    """Get a structured health report for a held position.

    Returns P&L, days held, distance from stop/target, position weight,
    whether protective orders exist, and DCA eligibility.

    Args:
        symbol: Stock ticker to check.

    Returns:
        Dict with position health metrics.
    """
    portfolio = get_portfolio()
    positions = portfolio.get("positions", [])
    pos = next((p for p in positions if p.get("symbol") == symbol.upper()), None)
    if not pos:
        return {"error": f"No open position in {symbol}"}

    equity = float(portfolio.get("equity", 1))
    current_price = float(pos.get("current_price", 0))
    avg_entry = float(pos.get("avg_entry_price", 0))
    qty = float(pos.get("qty", 0))
    market_value = float(pos.get("market_value", 0))
    unrealized_pnl = float(pos.get("unrealized_pl", 0))
    pnl_pct = float(pos.get("unrealized_plpc", 0)) * 100 if pos.get("unrealized_plpc") else 0

    position_weight = round(market_value / equity * 100, 2) if equity else 0

    # Peak price and drawdown since entry — gives the agent visibility into
    # "this position was at +12% and is now at +5%" oscillation patterns.
    peak_price = None
    peak_pnl_pct = None
    drawdown_from_peak_pct = None
    try:
        # Get the entry date from the most recent buy trade
        sb_peek = get_supabase()
        entry_trade = (
            sb_peek.table("trades")
            .select("created_at")
            .eq("symbol", symbol.upper())
            .eq("side", "buy")
            .or_("status.ilike.%filled%,status.ilike.%FILLED%")
            .order("created_at", desc=True)
            .limit(1)
            .execute()
        )
        if entry_trade.data:
            entry_date = entry_trade.data[0]["created_at"][:10]
            from datetime import datetime as _dt

            days_since = (_dt.now() - _dt.strptime(entry_date, "%Y-%m-%d")).days + 1
            df = get_historical_bars(symbol, days=max(days_since + 5, 10))
            if df is not None and len(df) > 0:
                # Filter to bars on or after entry date
                df_since = df[df.index >= entry_date] if hasattr(df.index, '__ge__') else df.tail(days_since)
                if len(df_since) > 0:
                    peak_price = round(float(df_since["high"].max()), 2)
                    if avg_entry > 0:
                        peak_pnl_pct = round((peak_price / avg_entry - 1) * 100, 2)
                    if peak_price > 0 and current_price > 0:
                        drawdown_from_peak_pct = round((current_price / peak_price - 1) * 100, 2)
    except Exception:
        pass

    # Check stock analysis memory for targets
    stock_mem = read_memory(f"stock:{symbol.upper()}")
    target_entry = None
    target_exit = None
    confidence = None
    if stock_mem and isinstance(stock_mem.get("value"), dict):
        v = stock_mem["value"]
        target_entry = v.get("target_entry")
        target_exit = v.get("target_exit")
        confidence = v.get("confidence")

    # Distance from targets
    dist_to_exit = round((float(target_exit) / current_price - 1) * 100, 2) if target_exit and current_price else None
    dist_from_entry = round((current_price / avg_entry - 1) * 100, 2) if avg_entry else None

    # Check for protective orders
    sb = get_supabase()
    protective = (
        sb.table("trades")
        .select("id, order_class, stop_loss_price, take_profit_price, status")
        .eq("symbol", symbol.upper())
        .eq("side", "sell")
        .or_("status.ilike.%new%,status.ilike.%accepted%,status.ilike.%pending%")
        .execute()
    )
    has_stop_loss = any(
        t.get("stop_loss_price") for t in (protective.data or [])
    )
    has_take_profit = any(
        t.get("take_profit_price") for t in (protective.data or [])
    )

    # DCA eligibility
    risk_settings = get_risk_settings()
    max_pos_pct = risk_settings.get("max_position_pct", 10.0)
    dca_eligible = (
        pnl_pct < -8
        and position_weight < max_pos_pct
        and confidence is not None
        and confidence >= 0.6
    )

    return {
        "symbol": symbol.upper(),
        "quantity": qty,
        "avg_entry_price": avg_entry,
        "current_price": current_price,
        "market_value": market_value,
        "unrealized_pnl": unrealized_pnl,
        "pnl_pct": round(pnl_pct, 2),
        "position_weight_pct": position_weight,
        "dist_from_entry_pct": dist_from_entry,
        "target_exit": target_exit,
        "dist_to_exit_pct": dist_to_exit,
        "has_stop_loss": has_stop_loss,
        "has_take_profit": has_take_profit,
        "protected": has_stop_loss,
        "dca_eligible": dca_eligible,
        "confidence": confidence,
        "peak_price": peak_price,
        "peak_pnl_pct": peak_pnl_pct,
        "drawdown_from_peak_pct": drawdown_from_peak_pct,
    }


# ============================================================
# Factor-Based Scoring tools
# ============================================================


