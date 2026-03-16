import { NextResponse } from "next/server";
import YahooFinance from "yahoo-finance2";

const yf = new YahooFinance({ suppressNotices: ["yahooSurvey"] });

/** Fetch a Wikipedia thumbnail for a person's name. Returns URL or null. */
async function fetchWikiPhoto(name: string): Promise<string | null> {
  try {
    // Remove honorifics/suffixes for better Wikipedia matching
    const cleaned = name
      .replace(/^(Mr\.|Ms\.|Mrs\.|Dr\.|Prof\.)\s*/i, "")
      .replace(/\s+(Jr\.|Sr\.|III|IV|II|CPA|CFA)$/i, "")
      .trim();
    const title = cleaned.replace(/\s+/g, "_");
    const url = `https://en.wikipedia.org/w/api.php?action=query&titles=${encodeURIComponent(title)}&prop=pageimages&format=json&pithumbsize=200`;
    const res = await fetch(url);
    if (!res.ok) return null;
    const data = await res.json();
    const pages = data?.query?.pages;
    if (!pages) return null;
    const page = Object.values(pages)[0] as { thumbnail?: { source: string } };
    return page?.thumbnail?.source ?? null;
  } catch {
    return null;
  }
}

export async function GET(
  _req: Request,
  { params }: { params: Promise<{ symbol: string }> },
) {
  const { symbol } = await params;
  const ticker = symbol.toUpperCase();

  try {
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    const result: any = await yf.quoteSummary(ticker, {
      modules: [
        "assetProfile",
        "earningsHistory",
        "financialData",
        "defaultKeyStatistics",
        "price",
      ],
    });

    const profile = result.assetProfile;
    const price = result.price;
    const financials = result.financialData;
    const keyStats = result.defaultKeyStatistics;

    // Company info — use parqet for reliable ticker-based logos
    const company = {
      name: price?.longName ?? price?.shortName ?? ticker,
      description: profile?.longBusinessSummary ?? null,
      sector: profile?.sector ?? null,
      industry: profile?.industry ?? null,
      website: profile?.website ?? null,
      logo: `https://assets.parqet.com/logos/symbol/${ticker}`,
      fullTimeEmployees: profile?.fullTimeEmployees ?? null,
      city: profile?.city ?? null,
      state: profile?.state ?? null,
      country: profile?.country ?? null,
    };

    // Leadership team (top 5 officers) — fetch Wikipedia photos in parallel
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    const rawOfficers = (profile?.companyOfficers ?? []).slice(0, 5);
    const photoPromises = rawOfficers.map((o: { name?: string }) =>
      fetchWikiPhoto(o.name ?? ""),
    );
    const photos = await Promise.all(photoPromises);

    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    const officers = rawOfficers.map((o: any, i: number) => ({
      name: o.name ?? "",
      title: o.title ?? "",
      age: o.age ?? null,
      photo: photos[i],
    }));

    // Key metrics
    const metrics = {
      marketCap: price?.marketCap ?? null,
      trailingPE: keyStats?.trailingEps
        ? (price?.regularMarketPrice ?? 0) / keyStats.trailingEps
        : null,
      forwardPE: keyStats?.forwardEps
        ? (price?.regularMarketPrice ?? 0) / keyStats.forwardEps
        : null,
      profitMargins: financials?.profitMargins ?? null,
      revenueGrowth: financials?.revenueGrowth ?? null,
      currentPrice: price?.regularMarketPrice ?? null,
      beta: keyStats?.beta ?? null,
    };

    // Earnings history — quarterly actuals vs estimates
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    const earningsHistory = (result.earningsHistory?.history ?? [])
      // eslint-disable-next-line @typescript-eslint/no-explicit-any
      .map((h: any) => {
        const qDate = h.quarter;
        if (!qDate) return null;
        const d = qDate instanceof Date ? qDate : new Date(qDate);
        const year = d.getFullYear().toString().slice(-2);
        const q = Math.ceil((d.getMonth() + 1) / 3);
        return {
          quarter: `Q${q}'${year}`,
          estimated_eps: h.epsEstimate ?? null,
          actual_eps: h.epsActual ?? null,
          surprise_pct:
            h.epsEstimate && h.epsActual
              ? ((h.epsActual - h.epsEstimate) / Math.abs(h.epsEstimate)) * 100
              : h.surprisePercent ?? 0,
        };
      })
      .filter(Boolean)
      .reverse(); // oldest first

    return NextResponse.json({
      company,
      officers,
      metrics,
      earningsHistory,
    });
  } catch (err) {
    console.error(`Failed to fetch stock detail for ${ticker}:`, err);
    return NextResponse.json(
      { error: "Failed to fetch company data" },
      { status: 502 },
    );
  }
}
