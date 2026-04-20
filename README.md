# Elliott Wave Analyzer

Automatically detects Elliott Wave structures on any Binance trading pair and generates interactive charts with Fibonacci projections.

## What It Does

- **Detects impulse waves** (①②③④⑤) using swing point analysis and Elliott Wave rules
- **Finds A-B-C corrections** after impulse sequences
- **Calculates Fibonacci targets** — Wave 2 retrace, Wave 3 extension, Wave 5 projections
- **Generates interactive HTML charts** — zoom, pan, hover — no chart platform needed
- **Outputs text reports** — sharable analysis summaries

Works on any Binance spot pair: BTC, ETH, SOL, BNB, DOGE, and hundreds more.

---

## Quick Start

**1. Install dependencies**
```bash
pip install -r requirements.txt
```

**2. Run on Bitcoin (all timeframes)**
```bash
python3 elliott.py
```

**3. Run on any coin, specific timeframe + report**
```bash
python3 elliott.py --symbol ETHUSDT --tf 4h --report
python3 elliott.py --symbol SOLUSDT --tf 1d --report
python3 elliott.py --symbol BNBUSDT --tf 1h
```

**Output:** HTML charts saved in the same folder. Open in any browser.

---

## Options

| Flag | Default | Description |
|------|---------|-------------|
| `--symbol` | `BTCUSDT` | Any Binance trading pair |
| `--tf` | all | `1h` `4h` `12h` `1d` |
| `--report` | off | Print + save text analysis |
| `--out` | script dir | Output directory |

---

## How It Works

### Swing Point Detection
Identifies statistically significant highs and lows using a configurable lookback window. Consecutive same-direction swings are merged to keep only the most extreme.

### Elliott Wave Rules Enforced
- Wave 2 never retraces beyond Wave 1's start
- Wave 3 is never the shortest impulse wave
- Wave 4 never overlaps Wave 1's price territory

### Fibonacci Targets
After detecting a complete 4-wave sequence, the tool projects Wave 5 at:
- **0.618×Wave 1** — conservative target
- **1.0×Wave 1** — equal move
- **1.618×Wave 1** — extended target

Wave 2 and Wave 4 retrace percentages are also calculated and flagged against the "golden zone" (38.2%–61.8%).

---

## Sample Output

```
============================================================
  ELLIOTT WAVE ANALYSIS REPORT
  BTCUSDT  |  4 Hour  |  2026-04-19 20:00 UTC
============================================================

Last price : $73,924.00
Range high : $124,774.00
Range low  : $62,854.00
Change     : +17.6% from range low

── IMPULSE WAVE 1 (BEARISH) ────────────────────────────
  Start : 2025-10-07   $124,774.00
  Wave 1: 2025-10-18   $106,444.00
  Wave 2: 2025-11-04   $114,024.00  (retrace 41.2% of W1)
  Wave 3: 2026-02-06    $62,854.00  (2.74× W1 extension)
  Wave 4: 2026-04-17    $77,957.00  (retrace 38.6% of W3)

  Wave 5 projections from Wave 4 high:
    0.618×W1       $59,518.00
    1.0×W1         $49,638.00
    1.618×W1       $35,421.00

── NOTES ────────────────────────────────────────────────
  W2 retrace 41.2% — golden zone ✓
  W3 extension 2.74× — strong ✓
  W4 retrace 38.6% — normal ✓
============================================================
```

---

## Requirements

- Python 3.9+
- Internet connection (fetches live data from Binance)
- No API key required

---

## Supported Pairs

Any Binance USDT pair: `BTCUSDT`, `ETHUSDT`, `SOLUSDT`, `BNBUSDT`, `DOGEUSDT`, `XRPUSDT`, `ADAUSDT`, etc.

Use `--symbol XXXUSDT` where XXX is the coin ticker.

---

## Disclaimer

This tool is for educational and analytical purposes only. Elliott Wave analysis is subjective — automated detection is a starting point, not financial advice. Always do your own research.

---

*Elliott Wave Analyzer — built for traders who want automated wave detection without a $100/month chart platform.*
