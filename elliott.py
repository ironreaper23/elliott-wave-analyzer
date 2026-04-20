#!/usr/bin/env python3
"""
Elliott Wave Analyzer
Automatically identifies Elliott Wave structures on any trading symbol.
Supports crypto (Binance) and stocks/ETFs/forex (Yahoo Finance).
Generates interactive HTML charts + written analysis reports.

Usage:
  python3 elliott.py                            # BTC all timeframes (Binance)
  python3 elliott.py --symbol ETHUSDT           # ETH (auto: Binance)
  python3 elliott.py --symbol AAPL --tf 1d      # Apple stock (auto: Yahoo)
  python3 elliott.py --symbol SPY --tf 4h       # S&P 500 ETF
  python3 elliott.py --symbol SLV --tf 1h       # Silver ETF
  python3 elliott.py --symbol BTCUSDT --tf 4h --report
"""

import argparse
import os
import sys
from datetime import datetime, timezone

import numpy as np
import pandas as pd
import plotly.graph_objects as go
import requests
from plotly.subplots import make_subplots

# ─── SOURCE DETECTION ────────────────────────────────────────────────────────

CRYPTO_SUFFIXES = ("USDT", "BUSD", "BTC", "ETH", "BNB", "USDC")

def is_crypto(symbol: str) -> bool:
    """Return True if symbol looks like a Binance crypto pair."""
    return any(symbol.upper().endswith(s) for s in CRYPTO_SUFFIXES)

# ─── TIMEFRAMES ──────────────────────────────────────────────────────────────

# Crypto timeframes (Binance)
TIMEFRAMES_CRYPTO = {
    "1h":  {"interval": "1h",  "label": "1 Hour",  "start": "2024-01-01"},
    "4h":  {"interval": "4h",  "label": "4 Hour",  "start": "2023-01-01"},
    "12h": {"interval": "12h", "label": "12 Hour", "start": "2022-11-01"},
    "1d":  {"interval": "1d",  "label": "Daily",   "start": "2022-11-01"},
}

# Stock/ETF timeframes (Yahoo Finance)
# Yahoo limits hourly to ~60 days, so 1h/4h use period; 1d/1w use start date
TIMEFRAMES_STOCK = {
    "1h":  {"interval": "1h",  "label": "1 Hour",  "period": "60d",   "start": None},
    "4h":  {"interval": "1h",  "label": "4 Hour",  "period": "60d",   "start": None,  "resample": "4h"},
    "1d":  {"interval": "1d",  "label": "Daily",   "period": None,    "start": "2022-01-01"},
    "1w":  {"interval": "1wk", "label": "Weekly",  "period": None,    "start": "2018-01-01"},
}

TIMEFRAMES = TIMEFRAMES_CRYPTO  # overridden per-symbol at runtime

# ─── DATA FETCH ───────────────────────────────────────────────────────────────

def fetch_binance(symbol: str, interval: str, start_date: str) -> pd.DataFrame:
    """Fetch OHLCV from Binance, paginating through all available candles."""
    url = "https://api.binance.us/api/v3/klines"
    start_ms = int(pd.Timestamp(start_date).timestamp() * 1000)
    all_rows = []
    fetch_start = start_ms

    while True:
        params = {"symbol": symbol, "interval": interval, "limit": 1000, "startTime": fetch_start}
        try:
            r = requests.get(url, params=params, timeout=15)
            r.raise_for_status()
        except requests.RequestException as e:
            # Try Binance.com as fallback
            try:
                url_fb = url.replace("binance.us", "binance.com")
                r = requests.get(url_fb, params=params, timeout=15)
                r.raise_for_status()
            except requests.RequestException:
                raise RuntimeError(f"Could not fetch data for {symbol}. Check the symbol name.") from e

        raw = r.json()
        if not raw or isinstance(raw, dict):
            break
        all_rows.extend(raw)
        if len(raw) < 1000:
            break
        fetch_start = raw[-1][6] + 1

    if not all_rows:
        raise RuntimeError(f"No data returned for {symbol} {interval}. Check symbol.")

    df = pd.DataFrame(all_rows, columns=[
        "ts", "open", "high", "low", "close", "volume",
        "close_ts", "quote_vol", "trades", "taker_buy_base", "taker_buy_quote", "ignore"
    ])
    df["ts"] = pd.to_datetime(df["ts"], unit="ms", utc=True)
    for col in ["open", "high", "low", "close", "volume"]:
        df[col] = df[col].astype(float)
    return df[["ts", "open", "high", "low", "close", "volume"]].reset_index(drop=True)

def fetch_yahoo(symbol: str, tf_cfg: dict) -> pd.DataFrame:
    """Fetch OHLCV from Yahoo Finance for stocks, ETFs, indices, forex."""
    try:
        import yfinance as yf
    except ImportError:
        raise RuntimeError("yfinance not installed. Run: pip install yfinance")

    interval = tf_cfg["interval"]
    period   = tf_cfg.get("period")
    start    = tf_cfg.get("start")
    resample = tf_cfg.get("resample")

    ticker = yf.Ticker(symbol)
    if period:
        raw = ticker.history(period=period, interval=interval)
    else:
        raw = ticker.history(start=start, interval=interval)

    if raw.empty:
        raise RuntimeError(f"No data returned for {symbol}. Check the ticker symbol.")

    raw = raw.reset_index()
    # yfinance uses 'Datetime' for intraday, 'Date' for daily/weekly
    ts_col = "Datetime" if "Datetime" in raw.columns else "Date"
    raw = raw.rename(columns={
        ts_col: "ts", "Open": "open", "High": "high",
        "Low": "low", "Close": "close", "Volume": "volume"
    })
    raw = raw[["ts", "open", "high", "low", "close", "volume"]].copy()
    raw["ts"] = pd.to_datetime(raw["ts"], utc=True)
    raw = raw.dropna(subset=["close"]).reset_index(drop=True)

    # Resample 1h → 4h if needed
    if resample:
        raw = raw.set_index("ts")
        raw = raw.resample(resample).agg({
            "open": "first", "high": "max", "low": "min",
            "close": "last", "volume": "sum"
        }).dropna(subset=["close"]).reset_index()

    return raw


# ─── SWING DETECTION ─────────────────────────────────────────────────────────

def find_swings(df: pd.DataFrame, order: int = 5) -> pd.DataFrame:
    highs = df["high"].values
    lows  = df["low"].values
    n = len(df)
    swing_high = np.zeros(n, dtype=bool)
    swing_low  = np.zeros(n, dtype=bool)

    for i in range(order, n - order):
        if highs[i] > highs[i-order:i].max() and highs[i] > highs[i+1:i+order+1].max():
            swing_high[i] = True
        if lows[i] < lows[i-order:i].min() and lows[i] < lows[i+1:i+order+1].min():
            swing_low[i] = True

    df = df.copy()
    df["swing_high"] = swing_high
    df["swing_low"]  = swing_low
    return df


def get_swing_points(df: pd.DataFrame) -> list:
    events = []
    for i, row in df.iterrows():
        if row["swing_high"]:
            events.append({"idx": i, "ts": row["ts"], "price": row["high"], "type": "H"})
        if row["swing_low"]:
            events.append({"idx": i, "ts": row["ts"], "price": row["low"],  "type": "L"})

    if not events:
        return []

    # Merge consecutive same-type, keep most extreme
    merged = [events[0]]
    for e in events[1:]:
        if e["type"] == merged[-1]["type"]:
            if (e["type"] == "H" and e["price"] > merged[-1]["price"]) or \
               (e["type"] == "L" and e["price"] < merged[-1]["price"]):
                merged[-1] = e
        else:
            merged.append(e)
    return merged

# ─── ELLIOTT WAVE RULES ───────────────────────────────────────────────────────

def validate_impulse(pts: list) -> bool:
    """Check Elliott Wave impulse rules for a 5-point sequence."""
    if len(pts) < 5:
        return False
    p = [pt["price"] for pt in pts[:5]]
    t = [pt["type"]  for pt in pts[:5]]

    # Bullish: L H L H L
    if t == ["L", "H", "L", "H", "L"]:
        w1 = p[1] - p[0]
        w3 = p[3] - p[2]
        rule1 = p[2] > p[0]           # Wave 2 can't undercut Wave 1 start
        rule3 = w3 >= min(w1, 0.001)  # Wave 3 not shortest
        rule4 = p[4] > p[1]           # Wave 4 can't overlap Wave 1 top
        return rule1 and rule3 and rule4

    # Bearish: H L H L H
    if t == ["H", "L", "H", "L", "H"]:
        w1 = p[0] - p[1]
        w3 = p[2] - p[3]
        rule1 = p[2] < p[0]
        rule3 = w3 >= min(w1, 0.001)
        rule4 = p[4] < p[1]
        return rule1 and rule3 and rule4

    return False


def find_impulse_waves(swings: list, min_wave_pct: float = 0.008) -> list:
    waves = []
    n = len(swings)
    for i in range(n - 4):
        window = swings[i:i + 5]
        prices = [w["price"] for w in window]
        spans  = [abs(prices[j+1] - prices[j]) / max(prices[j], 1e-9) for j in range(4)]
        if min(spans) < min_wave_pct:
            continue
        if validate_impulse(window):
            direction = "bullish" if window[0]["type"] == "L" else "bearish"
            waves.append({"points": window, "direction": direction})

    # Remove overlapping sequences, keep most recent
    if not waves:
        return []
    result = [waves[-1]]
    for w in reversed(waves[:-1]):
        if w["points"][4]["ts"] < result[0]["points"][0]["ts"]:
            result.insert(0, w)
    return result[-2:]  # keep at most 2 most recent


def find_corrective_wave(swings: list, after_ts) -> dict | None:
    """Look for A-B-C correction after the impulse endpoint."""
    after = [s for s in swings if s["ts"] > after_ts]
    for i in range(len(after) - 2):
        a, b, c = after[i], after[i+1], after[i+2]
        if a["type"] == "H" and b["type"] == "L" and c["type"] == "H":
            return {"points": [a, b, c], "type": "bearish_abc"}
        if a["type"] == "L" and b["type"] == "H" and c["type"] == "L":
            return {"points": [a, b, c], "type": "bullish_abc"}
    return None

# ─── FIBONACCI ANALYSIS ───────────────────────────────────────────────────────

def fibonacci_targets(wave: dict) -> dict:
    """
    Given a 5-point impulse wave, compute:
    - Wave 2 retracement depth (% of Wave 1)
    - Wave 3 extension vs Wave 1
    - Wave 4 retracement depth (% of Wave 3)
    - Projected Wave 5 targets (0.618×W1, 1×W1, 1.618×W1 from W4 end)
    """
    pts = wave["points"]
    p   = [pt["price"] for pt in pts]
    direction = wave["direction"]

    if direction == "bullish":
        w1_len = p[1] - p[0]
        w3_len = p[3] - p[2]
        w2_retrace = (p[1] - p[2]) / w1_len * 100 if w1_len else 0
        w4_retrace = (p[3] - p[4]) / w3_len * 100 if w3_len else 0
        w3_ext     = w3_len / w1_len if w1_len else 0
        w5_targets = {
            "0.618×W1": p[4] + 0.618 * w1_len,
            "1.0×W1":   p[4] + 1.000 * w1_len,
            "1.618×W1": p[4] + 1.618 * w1_len,
        }
    else:
        w1_len = p[0] - p[1]
        w3_len = p[2] - p[3]
        w2_retrace = (p[2] - p[1]) / w1_len * 100 if w1_len else 0
        w4_retrace = (p[4] - p[3]) / w3_len * 100 if w3_len else 0
        w3_ext     = w3_len / w1_len if w1_len else 0
        w5_targets = {
            "0.618×W1": p[4] - 0.618 * w1_len,
            "1.0×W1":   p[4] - 1.000 * w1_len,
            "1.618×W1": p[4] - 1.618 * w1_len,
        }

    return {
        "w1_len": w1_len,
        "w3_len": w3_len,
        "w3_extension": round(w3_ext, 3),
        "w2_retrace_pct": round(w2_retrace, 1),
        "w4_retrace_pct": round(w4_retrace, 1),
        "w5_targets": w5_targets,
    }

# ─── CHARTING ─────────────────────────────────────────────────────────────────

COLORS = {"bullish": "#00d4aa", "bearish": "#ff4d4d", "abc": "#ffa500"}


def build_chart(df, swings, waves, correction, symbol, tf_label) -> go.Figure:
    fig = make_subplots(
        rows=2, cols=1, shared_xaxes=True,
        row_heights=[0.8, 0.2], vertical_spacing=0.03,
        subplot_titles=[f"{symbol} — {tf_label} | Elliott Wave Analyzer", "Volume"]
    )

    # Candlesticks
    fig.add_trace(go.Candlestick(
        x=df["ts"], open=df["open"], high=df["high"], low=df["low"], close=df["close"],
        name=symbol,
        increasing_line_color="#00d4aa", decreasing_line_color="#ff4d4d",
        increasing_fillcolor="#00d4aa", decreasing_fillcolor="#ff4d4d",
    ), row=1, col=1)

    # Volume
    bar_colors = ["#00d4aa" if c >= o else "#ff4d4d" for c, o in zip(df["close"], df["open"])]
    fig.add_trace(go.Bar(
        x=df["ts"], y=df["volume"], name="Volume",
        marker_color=bar_colors, opacity=0.5,
    ), row=2, col=1)

    # Swing markers
    sh = df[df["swing_high"]]
    sl = df[df["swing_low"]]
    fig.add_trace(go.Scatter(
        x=sh["ts"], y=sh["high"], mode="markers",
        marker=dict(symbol="triangle-down", size=7, color="#ffcc00"),
        name="Swing High", hoverinfo="skip",
    ), row=1, col=1)
    fig.add_trace(go.Scatter(
        x=sl["ts"], y=sl["low"], mode="markers",
        marker=dict(symbol="triangle-up", size=7, color="#88ccff"),
        name="Swing Low", hoverinfo="skip",
    ), row=1, col=1)

    price_range = df["high"].max() - df["low"].min()

    # Impulse waves
    for wave in waves:
        pts = wave["points"]
        color = COLORS[wave["direction"]]
        xs = [p["ts"]    for p in pts]
        ys = [p["price"] for p in pts]

        fig.add_trace(go.Scatter(
            x=xs, y=ys, mode="lines+markers",
            line=dict(color=color, width=2.5),
            marker=dict(size=10, color=color, symbol="circle"),
            name=f"{wave['direction'].title()} Impulse",
            showlegend=False,
        ), row=1, col=1)

        labels = ["①", "②", "③", "④", "⑤"] if len(pts) == 5 else [str(i) for i in range(len(pts))]
        for j, (x, y, pt) in enumerate(zip(xs, ys, pts)):
            offset = price_range * 0.015
            ya = y + offset if pt["type"] == "H" else y - offset
            fig.add_annotation(
                x=x, y=ya, text=f"<b>{labels[j]}</b>", showarrow=False,
                font=dict(size=14, color=color),
                bgcolor="rgba(13,17,23,0.8)", borderpad=3, row=1, col=1,
            )

        # Fibonacci targets for Wave 5 from Wave 4 end
        fibs = fibonacci_targets(wave)
        for label, target in fibs["w5_targets"].items():
            fig.add_hline(
                y=target, line_dash="dot", line_color=color, line_width=1,
                opacity=0.45,
                annotation_text=f"  W5 {label} ${target:,.0f}",
                annotation_font_size=10, annotation_font_color=color,
                row=1, col=1,
            )

    # A-B-C correction
    if correction:
        pts = correction["points"]
        color = COLORS["abc"]
        xs = [p["ts"]    for p in pts]
        ys = [p["price"] for p in pts]
        fig.add_trace(go.Scatter(
            x=xs, y=ys, mode="lines+markers",
            line=dict(color=color, width=2.5, dash="dot"),
            marker=dict(size=10, color=color),
            name="A-B-C Correction",
            showlegend=False,
        ), row=1, col=1)
        for j, (x, y, pt) in enumerate(zip(xs, ys, pts)):
            label = ["Ⓐ", "Ⓑ", "Ⓒ"][j]
            offset = price_range * 0.015
            ya = y + offset if pt["type"] == "H" else y - offset
            fig.add_annotation(
                x=x, y=ya, text=f"<b>{label}</b>", showarrow=False,
                font=dict(size=14, color=color),
                bgcolor="rgba(13,17,23,0.8)", borderpad=3, row=1, col=1,
            )

    last = df["close"].iloc[-1]
    ts   = df["ts"].iloc[-1].strftime("%Y-%m-%d %H:%M UTC")
    fig.update_layout(
        template="plotly_dark",
        paper_bgcolor="#0d1117", plot_bgcolor="#0d1117",
        font=dict(color="#c9d1d9", family="'JetBrains Mono', monospace"),
        xaxis_rangeslider_visible=False,
        height=780,
        margin=dict(l=70, r=40, t=70, b=50),
        legend=dict(orientation="h", y=1.02, x=0),
        title=dict(
            text=f"{symbol}  |  {tf_label}  |  Last: ${last:,.2f}  |  {ts}",
            font=dict(size=13, color="#8b949e"), x=0.5,
        ),
    )
    fig.update_xaxes(gridcolor="#21262d")
    fig.update_yaxes(gridcolor="#21262d", tickprefix="$")
    return fig

# ─── ANALYSIS REPORT ─────────────────────────────────────────────────────────

def generate_report(symbol: str, tf: str, df: pd.DataFrame,
                    waves: list, correction) -> str:
    last   = df["close"].iloc[-1]
    hi     = df["high"].max()
    lo     = df["low"].min()
    ts     = df["ts"].iloc[-1].strftime("%Y-%m-%d %H:%M UTC")
    lines  = []

    lines.append("=" * 60)
    lines.append(f"  ELLIOTT WAVE ANALYSIS REPORT")
    lines.append(f"  {symbol}  |  {TIMEFRAMES[tf]['label']}  |  {ts}")
    lines.append("=" * 60)
    lines.append(f"\nLast price : ${last:,.2f}")
    lines.append(f"Range high : ${hi:,.2f}")
    lines.append(f"Range low  : ${lo:,.2f}")
    lines.append(f"Change     : {(last - lo) / lo * 100:+.1f}% from range low\n")

    if not waves:
        lines.append("No valid Elliott Wave impulse sequences detected.")
        lines.append("Market may be in consolidation or data range too short.\n")
    else:
        for i, wave in enumerate(waves, 1):
            pts  = wave["points"]
            fibs = fibonacci_targets(wave)
            d    = wave["direction"].upper()
            lines.append(f"── IMPULSE WAVE {i} ({d}) ────────────────────────")
            lines.append(f"  Start : {pts[0]['ts'].strftime('%Y-%m-%d')}  ${pts[0]['price']:>12,.2f}")
            lines.append(f"  Wave 1: {pts[1]['ts'].strftime('%Y-%m-%d')}  ${pts[1]['price']:>12,.2f}")
            lines.append(f"  Wave 2: {pts[2]['ts'].strftime('%Y-%m-%d')}  ${pts[2]['price']:>12,.2f}  (retrace {fibs['w2_retrace_pct']:.1f}% of W1)")
            lines.append(f"  Wave 3: {pts[3]['ts'].strftime('%Y-%m-%d')}  ${pts[3]['price']:>12,.2f}  ({fibs['w3_extension']:.2f}× W1 extension)")
            lines.append(f"  Wave 4: {pts[4]['ts'].strftime('%Y-%m-%d')}  ${pts[4]['price']:>12,.2f}  (retrace {fibs['w4_retrace_pct']:.1f}% of W3)")
            lines.append(f"\n  Wave 5 projections from Wave 4 low:")
            for label, target in fibs["w5_targets"].items():
                lines.append(f"    {label:12s}  ${target:>12,.2f}")
            lines.append("")

    if correction:
        pts = correction["points"]
        ctype = "Bearish" if "bearish" in correction["type"] else "Bullish"
        lines.append(f"── A-B-C CORRECTION ({ctype}) ─────────────────────")
        labels = ["A", "B", "C"]
        for j, (label, pt) in enumerate(zip(labels, pts)):
            lines.append(f"  Wave {label}: {pt['ts'].strftime('%Y-%m-%d')}  ${pt['price']:>12,.2f}")
        lines.append("")

    # Pattern notes
    lines.append("── NOTES ──────────────────────────────────────────────")
    if waves:
        w = waves[-1]
        f = fibonacci_targets(w)
        lines.append(f"  W2 retrace {f['w2_retrace_pct']:.1f}% — " +
                     ("golden zone ✓" if 38 < f['w2_retrace_pct'] < 70 else "outside golden zone"))
        lines.append(f"  W3 extension {f['w3_extension']:.2f}× — " +
                     ("strong ✓" if f['w3_extension'] >= 1.618 else
                      "typical ✓" if f['w3_extension'] >= 1.0 else "weak"))
        lines.append(f"  W4 retrace {f['w4_retrace_pct']:.1f}% — " +
                     ("normal ✓" if 23 < f['w4_retrace_pct'] < 62 else "extended"))
    lines.append(f"\n  Generated by Elliott Wave Analyzer")
    lines.append(f"  Data: Binance  |  Timeframe: {TIMEFRAMES[tf]['label']}")
    lines.append("=" * 60)

    return "\n".join(lines)

# ─── MAIN ─────────────────────────────────────────────────────────────────────

def run(symbol: str, tf: str, output_dir: str, report: bool, source: str) -> str:
    crypto = (source == "binance") or (source == "auto" and is_crypto(symbol))
    tf_map = TIMEFRAMES_CRYPTO if crypto else TIMEFRAMES_STOCK

    if tf not in tf_map:
        available = list(tf_map.keys())
        raise ValueError(f"Timeframe '{tf}' not available for {'crypto' if crypto else 'stocks'}. "
                         f"Available: {available}")

    cfg   = tf_map[tf]
    label = cfg["label"]
    src   = "Binance" if crypto else "Yahoo Finance"
    print(f"\n[{symbol} {tf}] Source: {src}  |  Fetching…")

    if crypto:
        df = fetch_binance(symbol, cfg["interval"], cfg["start"])
    else:
        df = fetch_yahoo(symbol, cfg)

    last = df["close"].iloc[-1]
    print(f"[{symbol} {tf}] {len(df)} candles  |  last: ${last:,.2f}")

    order = {"1h": 8, "4h": 6, "12h": 7, "1d": 8, "1w": 5}.get(tf, 6)
    df    = find_swings(df, order=order)
    swings = get_swing_points(df)
    print(f"[{symbol} {tf}] {len(swings)} swing points detected")

    waves = find_impulse_waves(swings)
    print(f"[{symbol} {tf}] {len(waves)} impulse wave sequence(s) found")

    correction = None
    if waves:
        last_ts    = waves[-1]["points"][-1]["ts"]
        correction = find_corrective_wave(swings, last_ts)
        if correction:
            print(f"[{symbol} {tf}] A-B-C correction detected")

    fig  = build_chart(df, swings, waves, correction, symbol, label)
    slug = symbol.lower().replace("/", "").replace("^", "")
    out  = os.path.join(output_dir, f"{slug}_elliott_{tf}.html")
    fig.write_html(out, include_plotlyjs="cdn")
    print(f"[{symbol} {tf}] Chart → {out}")

    if report:
        rpt = generate_report(symbol, tf, df, waves, correction)
        print("\n" + rpt)
        rpt_out = os.path.join(output_dir, f"{slug}_elliott_{tf}_report.txt")
        with open(rpt_out, "w") as f:
            f.write(rpt)
        print(f"[{symbol} {tf}] Report → {rpt_out}")

    return out


def main():
    parser = argparse.ArgumentParser(
        description="Elliott Wave Analyzer — crypto (Binance) and stocks/ETFs (Yahoo Finance)",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python3 elliott.py                              BTC/USDT all crypto timeframes
  python3 elliott.py --symbol ETHUSDT --tf 4h    ETH 4h
  python3 elliott.py --symbol AAPL --tf 1d       Apple daily
  python3 elliott.py --symbol SPY --tf 1h        S&P 500 ETF hourly
  python3 elliott.py --symbol SLV --tf 1d --report
  python3 elliott.py --symbol TSLA --tf 1w       Tesla weekly
  python3 elliott.py --symbol GLD --tf 4h        Gold ETF 4h

Crypto timeframes:   1h, 4h, 12h, 1d
Stock timeframes:    1h, 4h, 1d, 1w
        """
    )
    parser.add_argument("--symbol", default="BTCUSDT",
                        help="Ticker symbol: BTCUSDT (crypto) or AAPL/SPY/SLV (stocks)")
    parser.add_argument("--tf", default=None,
                        help="Timeframe (crypto: 1h/4h/12h/1d  stocks: 1h/4h/1d/1w). Omit for all.")
    parser.add_argument("--source", choices=["auto", "binance", "yahoo"], default="auto",
                        help="Data source (default: auto-detect from symbol)")
    parser.add_argument("--report", action="store_true",
                        help="Print and save a text analysis report")
    parser.add_argument("--out", default=None,
                        help="Output directory (default: current directory)")
    args = parser.parse_args()

    symbol = args.symbol.upper()
    source = args.source
    crypto = (source == "binance") or (source == "auto" and is_crypto(symbol))
    tf_map = TIMEFRAMES_CRYPTO if crypto else TIMEFRAMES_STOCK

    tfs        = [args.tf] if args.tf else list(tf_map.keys())
    output_dir = args.out or os.path.dirname(os.path.abspath(__file__))
    os.makedirs(output_dir, exist_ok=True)

    src_label = "Binance (crypto)" if crypto else "Yahoo Finance (stocks/ETFs)"
    print(f"\n{'='*55}")
    print(f"  Elliott Wave Analyzer")
    print(f"  Symbol: {symbol}  |  Source: {src_label}")
    print(f"  Timeframes: {', '.join(tfs)}")
    print(f"{'='*55}")

    outputs = []
    for tf in tfs:
        try:
            out = run(symbol, tf, output_dir, args.report, source)
            outputs.append(out)
        except Exception as e:
            print(f"[ERROR] {symbol} {tf}: {e}")

    print(f"\n✓ Done. Open in browser:")
    for o in outputs:
        print(f"  {o}")


if __name__ == "__main__":
    main()
