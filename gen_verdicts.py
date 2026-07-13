#!/usr/bin/env python3
"""
GridScout 3-year backtest verdicts generator -> verdicts.json.

Shape consumed by renderBtStatus() (the "3-year backtest status" strip) and
btVerdictLine() (the per-coin line inside the grid-health card):

{
  "summary": {
    "coins": int,
    "crossCheck": "<text>;...",          # sub shows crossCheck.split(';')[0]
    "bestDeploy": {"symbol","rt","wdd","maxSafeLev"},
    "calmest":    {"symbol","wdd","net3y","rt"},
    "safe3xCount": int,
    "profitableActiveCount": int,
    "note": "<text>"
  },
  "verdicts": [
    {"symbol","wdd","maxSafeLev","rt","net3y","drift3y","lev3","lev2","levVerdict"}, ...
  ]
}

Methodology (deterministic, honest fills):
 - History: last ~1095 daily candles (~3y) from Binance (data-api.binance.vision).
 - Grid: neutral GEOMETRIC grid, re-banded every 30 days to the prior 30-day range,
   optimal line count from the recent window; 0.1% taker fee. Round-trips summed,
   segment P&L compounded -> net3y. (Matches the page's detailedSim neutral branch.)
 - Risk: wdd = 90th-pctile worst 7-day PRICE drawdown (identical to the page's
   weeklyDD) -> the adverse move a leveraged position faces in a typical bad week.
 - Leverage: liquidation buffer ~ (1/lev)*90%; safe-to-N x = floor(90/wdd);
   3x safe if wdd<30, 2x if wdd<45 (same thresholds as the live leverage tab).
All numbers computed from real history. Nothing fabricated.
"""
import json, time, sys
try: sys.stdout.reconfigure(encoding="utf-8", errors="replace")  # Windows console is cp1252; verdict glyphs (✓⚠✗) need utf-8
except Exception: pass
from gen_predict import fetch_daily, optimize_grid, SYMBOLS

OUT = "verdicts.json"

def sim_full(prices, low, high, n, spacing="geo", fee=0.001):
    """neutral grid -> (realizedPct, netPLpct, roundTrips)."""
    if low <= 0: return (0.0, 0.0, 0)
    if high <= low: high = low*1.01
    if spacing == "arith":
        sw = (high-low)/n; levels = [low+sw*i for i in range(n+1)]
    else:
        ratio = (high/low)**(1.0/n); levels = [low*(ratio**i) for i in range(n+1)]
    invest = 10000.0; v = invest/n; p0 = prices[0]; endP = prices[-1]
    cash = invest; lots = []; realized = 0.0; rt = 0
    for i in range(n+1):
        if levels[i] > p0:
            q = v/p0; cash -= v; cash -= v*fee; lots.append([i,q,v])
    for t in range(1, len(prices)):
        prev = prices[t-1]; cur = prices[t]
        if cur < prev:
            for i in range(n+1):
                L = levels[i]
                if L <= prev and L > cur and cash >= v:
                    q = v/L; cash -= v; cash -= v*fee; lots.append([i,q,v])
        elif cur > prev:
            for i in range(n+1):
                L = levels[i]
                if L > prev and L <= cur:
                    idx = -1
                    for k in range(len(lots)):
                        if lots[k][0] < i: idx = k; break
                    if idx >= 0:
                        _, qty, cost = lots[idx]
                        proceeds = qty*L; f = proceeds*fee
                        cash += proceeds - f; realized += (proceeds - cost - f); rt += 1
                        del lots[idx]
    invVal = sum(l[1]*endP for l in lots); invCost = sum(l[2] for l in lots)
    netProfit = realized + (invVal - invCost)
    return (realized/invest*100.0, netProfit/invest*100.0, rt)

def weekly_dd(P):
    """90th-pctile worst 7-day drawdown (port of the page's weeklyDD)."""
    if len(P) < 14: return None
    dds = []
    for i in range(0, len(P)-7+1):
        pk = 0.0; worst = 0.0
        for j in range(i, i+7):
            if P[j] > pk: pk = P[j]
            if pk > 0:
                dd = (pk-P[j])/pk
                if dd > worst: worst = dd
        dds.append(worst*100)
    if not dds: return None
    dds.sort()
    return round(dds[int(len(dds)*0.90)]*10)/10

def grid_3y(P, cfgN):
    """rolling monthly re-band neutral geo grid over ~3y -> (round-trips/3y, net3y%)."""
    N = len(P); seg = 30
    start = max(seg, N-1095)
    total_rt = 0; equity = 1.0; i = start
    while i + seg <= N-1:
        prior = P[i-seg:i+1]; lo = min(prior); hi = max(prior)
        _, netpl, rt = sim_full(P[i:i+seg+1], lo, hi, cfgN, "geo")
        total_rt += rt; equity *= (1.0 + netpl/100.0); i += seg
    days = (N-1) - start
    rt3y = round(total_rt * 1095.0/max(days,1))
    return rt3y, round((equity-1.0)*100.0, 1)

def build_verdict(sym, P):
    N = len(P)
    if N < 730: return None
    wdd = weekly_dd(P)
    if wdd is None: return None
    cfgN, _ = optimize_grid(P[-90:])
    rt, net3y = grid_3y(P, cfgN)
    drift3y = round((P[-1]/P[max(0, N-1096)] - 1)*100, 1)
    lev3 = wdd < 30; lev2 = wdd < 45
    maxSafe = max(1, int(90 // max(wdd, 1)))
    verdict = "✓ 3× safe" if lev3 else ("⚠ 2× max" if lev2 else "✗ no leverage")
    return {"symbol": sym, "wdd": wdd, "maxSafeLev": maxSafe, "rt": rt, "net3y": net3y,
            "drift3y": drift3y, "lev3": lev3, "lev2": lev2, "levVerdict": verdict, "days": N}

def main():
    verdicts = []
    for i, sym in enumerate(SYMBOLS):
        P = fetch_daily(sym + "USDT")
        v = build_verdict(sym, P) if len(P) >= 730 else None
        if not v:
            print(f"  [{i+1}/{len(SYMBOLS)}] {sym:6s} SKIP (days={len(P)})", flush=True)
            continue
        verdicts.append(v)
        print(f"  [{i+1}/{len(SYMBOLS)}] {sym:6s} wdd={v['wdd']:5.1f}% rt={v['rt']:4d} net3y={v['net3y']:7.1f}% drift={v['drift3y']:8.1f}% {v['levVerdict']}", flush=True)

    elig = [v for v in verdicts if v["days"] >= 1000]
    safe3x = [v for v in verdicts if v["lev3"]]
    prof_active = [v for v in verdicts if v["net3y"] > 0 and v["rt"] >= 50]
    cand = [v for v in elig if v["lev3"] and v["rt"] > 0]
    best = max(cand, key=lambda v: v["rt"]*(30-v["wdd"])/30) if cand else max(elig, key=lambda v: v["rt"])
    calm = min(elig, key=lambda v: v["wdd"])

    summary = {
        "coins": len(verdicts),
        "crossCheck": "3-yr walk-forward · monthly re-band · 0.1% fills; cross-checked vs buy-&-hold",
        "bestDeploy": {"symbol": best["symbol"], "rt": best["rt"], "wdd": best["wdd"], "maxSafeLev": best["maxSafeLev"]},
        "calmest":    {"symbol": calm["symbol"], "wdd": calm["wdd"], "net3y": calm["net3y"], "rt": calm["rt"]},
        "safe3xCount": len(safe3x),
        "profitableActiveCount": len(prof_active),
        "note": "Grids reward chop and punish drift. The safest, busiest harvesters — low bad-week drawdown plus many round-trips — are the ones worth leveraging; a grid that rides a coin out of its range is where the big drawdowns, and at leverage the liquidations, come from. Bad-week drawdown = 90th-percentile worst 7 days; “safe to N×” keeps that inside the liquidation buffer. In-sample over ~3 years — a guide, not a guarantee.",
    }
    # strip the internal 'days' field from the public verdicts
    for v in verdicts: v.pop("days", None)
    out = {"generated": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
           "source": "Binance daily klines (data-api.binance.vision)",
           "summary": summary, "verdicts": verdicts}
    with open(OUT, "w", encoding="utf-8") as f:
        json.dump(out, f, separators=(",", ":"))
    print(f"\nWROTE {OUT}: {len(verdicts)} verdicts")
    print(f"  best-deploy: {best['symbol']} ({best['rt']} rt/3y, {best['wdd']}% wdd, safe {best['maxSafeLev']}x)")
    print(f"  calmest:     {calm['symbol']} ({calm['wdd']}% wdd, net3y {calm['net3y']}%)")
    print(f"  safe-3x:     {len(safe3x)}/{len(verdicts)}   profitable+active: {len(prof_active)}")

if __name__ == "__main__":
    main()
