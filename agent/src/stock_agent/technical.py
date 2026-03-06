"""Technical indicator computation using the ta library."""

import pandas as pd
import ta


def compute_indicators(df: pd.DataFrame) -> dict:
    """Compute key technical indicators from OHLCV data.

    Args:
        df: DataFrame with open, high, low, close, volume columns.

    Returns:
        Dict of indicator values and signals.
    """
    if df.empty or len(df) < 14:
        return {"error": "Insufficient data for technical analysis"}

    close = df["close"]
    high = df["high"]
    low = df["low"]
    volume = df["volume"]

    # RSI
    rsi = ta.momentum.RSIIndicator(close, window=14)
    current_rsi = round(float(rsi.rsi().iloc[-1]), 2)

    # MACD
    macd = ta.trend.MACD(close)
    macd_line = round(float(macd.macd().iloc[-1]), 4)
    signal_line = round(float(macd.macd_signal().iloc[-1]), 4)
    macd_histogram = round(float(macd.macd_diff().iloc[-1]), 4)

    # Bollinger Bands
    bb = ta.volatility.BollingerBands(close, window=20, window_dev=2)
    bb_upper = round(float(bb.bollinger_hband().iloc[-1]), 2)
    bb_middle = round(float(bb.bollinger_mavg().iloc[-1]), 2)
    bb_lower = round(float(bb.bollinger_lband().iloc[-1]), 2)
    current_price = round(float(close.iloc[-1]), 2)

    # Moving Averages
    sma_20 = round(float(close.rolling(20).mean().iloc[-1]), 2)
    sma_50 = round(float(close.rolling(50).mean().iloc[-1]), 2) if len(close) >= 50 else None
    sma_200 = round(float(close.rolling(200).mean().iloc[-1]), 2) if len(close) >= 200 else None

    # Volume analysis
    avg_volume_20 = round(float(volume.rolling(20).mean().iloc[-1]), 0)
    current_volume = int(volume.iloc[-1])
    volume_ratio = round(current_volume / avg_volume_20, 2) if avg_volume_20 > 0 else 0

    # ATR (volatility)
    atr = ta.volatility.AverageTrueRange(high, low, close, window=14)
    current_atr = round(float(atr.average_true_range().iloc[-1]), 2)

    # Signals
    signals = []
    if current_rsi < 30:
        signals.append("RSI oversold (<30)")
    elif current_rsi > 70:
        signals.append("RSI overbought (>70)")

    if macd_line > signal_line and macd_histogram > 0:
        signals.append("MACD bullish crossover")
    elif macd_line < signal_line and macd_histogram < 0:
        signals.append("MACD bearish crossover")

    if current_price < bb_lower:
        signals.append("Price below lower Bollinger Band")
    elif current_price > bb_upper:
        signals.append("Price above upper Bollinger Band")

    if sma_50 and current_price > sma_50:
        signals.append("Price above SMA 50")
    if sma_50 and current_price < sma_50:
        signals.append("Price below SMA 50")

    if volume_ratio > 1.5:
        signals.append(f"High volume ({volume_ratio}x average)")

    return {
        "price": current_price,
        "rsi": current_rsi,
        "macd": {
            "macd_line": macd_line,
            "signal_line": signal_line,
            "histogram": macd_histogram,
        },
        "bollinger_bands": {
            "upper": bb_upper,
            "middle": bb_middle,
            "lower": bb_lower,
        },
        "moving_averages": {
            "sma_20": sma_20,
            "sma_50": sma_50,
            "sma_200": sma_200,
        },
        "volume": {
            "current": current_volume,
            "avg_20": avg_volume_20,
            "ratio": volume_ratio,
        },
        "atr": current_atr,
        "signals": signals,
    }
