# GridScout ⚡

**Find the best coins for your grid bot.** GridScout scans the crypto market live, scores every coin 0–100 for grid-bot suitability, and hands you backtested, copy-ready settings for MEXC geometric grid bots — free, no sign-up, no API key, entirely in your browser.

## Features

- **Live scanner** — top-200 coins from CoinGecko, scored on volatility + liquidity + turnover − trend penalty, refreshed ~60s
- **Per-coin grid lab** — open any coin for a profit-optimised grid (band, line count, geometric/arithmetic spacing), bar-by-bar backtests over 7D/30D/90D/1Y, and a copy-to-MEXC settings table
- **Leverage that tells the truth** — live P&L at your chosen leverage with stop + liquidation modelled, and a risk rating (SAFE → MODERATE → RISKY → EXTREME → 🛑 LIQUIDATED)
- **3-year backtest verdicts** — walk-forward study of 66 majors: bad-week drawdown, safe leverage cap, round-trips, drift
- **🔮 Prediction board** — regime-conditioned forward base rates per horizon (24h → 1y), from ~2,000 days of history per coin
- **Grid planner** — how long will you hold? Optimal grid count + mode per holding period, with historical confidence
- **Set-&-forget stops** — per-coin stop distances from a 3-year regime study
- **Favourites monitor** — star your live grids; it only speaks up on a real issue (out of range / move the stop / pull)
- **Sideways & Leverage tabs** — coins ranging 8+ months, and coins that survive your leverage

## Run it

It's a static site — no build, no dependencies.

```bash
python -m http.server 8000
# open http://localhost:8000
```

Or enable **GitHub Pages** (Settings → Pages → deploy from branch → `main` / root) and it's live on the web.

> Opening `index.html` directly via double-click mostly works, but browsers block `fetch()` on `file://`, so the prediction board and 3-yr verdict strip need it served over http(s).

## Data files

| File | Contents | Regenerate with |
|---|---|---|
| `predict.json` | forward base rates by horizon, regime-conditioned + grid success rates | `python gen_predict.py` |
| `verdicts.json` | 3-yr walk-forward grid verdicts (drawdown, leverage caps, round-trips) | `python gen_verdicts.py` |
| `dynstop_lookup.js` | per-coin set-&-forget stop distances by regime | `python gen_lookups.py` |
| `holdplan_lookup.js` | optimal grid count/mode per holding period + regime map | `python gen_lookups.py` |

Generators need only Python 3 stdlib and pull real daily klines from Binance's public data mirror. Re-run them any time to refresh the studies.

## Honest by design

Every number is computed from real market history — nothing is fabricated. Backtests are in-sample guides, not guarantees; the UI labels confidence and sample sizes, penalises trend (grids want chop, not drift), and models liquidation instead of multiplying profit by leverage.

## Disclaimer

**Not financial advice.** Educational tool only. Crypto trading and automated grid bots carry substantial risk of loss, including total loss of capital. Scores and backtests are heuristic estimates from public data and may be delayed or inaccurate. Do your own research; never trade money you can't afford to lose.
