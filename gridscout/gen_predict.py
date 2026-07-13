#!/usr/bin/env python3
"""
GridScout prediction-board data generator.

Produces predict.json in the exact shape the page's predictBoard() consumes:

{
  "coins": [
    { "symbol": "BTC", "curRegime": "bull|side|bear",
      "h": {
        "<horizon>": {                       # horizon in h24,d7,d30,m6,y1
          "all":   {"bull":%, "side":%, "bear":%, "n":int, "success":%|null},
          "byReg": { "bull": {...}, "side": {...}, "bear": {...} },   # only regimes with >=10 windows
          "cfgN": int, "cfgSp": "geo|arith"
        }, ...
      }
    }, ...
  ]
}

Methodology (matches the board's d-note + the live planner's logic):
 - Forward move over each horizon classified bull/side/bear with a volatility-scaled
   threshold thr = max(0.06, daily_sd * sqrt(H) * 0.5)  (same rule as computeLivePlan).
 - "all"  = climatology (every start day).  "byReg" = conditioned on the start regime
   (SMA20 vs SMA50, identical to the page's liveRegime()).
 - success = share of windows a NEUTRAL grid (banded to the prior H-day range, best
   geo/arith config by the same optimizeGrid rule) finished in profit.
 - The board itself blends 60% all + 40% current-regime ("M5_blend") at render time.

All numbers are real, computed from Binance daily klines. Nothing is fabricated.
"""
import urllib.request, json, math, time, sys

BASE = "https://data-api.binance.vision/api/v3/klines"
OUT  = "predict.json"

# CoinGecko-symbol -> assumed Binance USDT base. For majors these match 1:1.
SYMBOLS = [
 "BTC","ETH","BNB","XRP","SOL","ADA","DOGE","TRX","LINK","DOT","LTC","BCH","AVAX",
 "XLM","ATOM","UNI","ETC","FIL","NEAR","ICP","HBAR","VET","ALGO","AAVE","GRT","SAND",
 "MANA","EOS","XTZ","THETA","AXS","CAKE","NEO","DASH","ZEC","MKR","CHZ","GALA","APT",
 "ARB","OP","INJ","RUNE","CRV","COMP","SNX","LDO","IMX","STX","SUI","SEI","TIA","FET",
 "AR","EGLD","FLOW","KAVA","ENJ","IOTA","KSM","1INCH","BAT","ZRX","QNT","SUSHI","DYDX",
]

HORIZONS   = [("h24",1),("d7",7),("d30",30),("m6",180),("y1",365)]
MIN_WIN    = 30     # min windows for a horizon to be included
SUCC_CAP   = 280    # cap on grid-sim windows per horizon (sampled); distribution uses ALL
SP_TOL     = 1.0

def fetch_daily(pair, max_days=2000):
    # disk cache (<6h old) so back-to-back generator runs don't re-download the same history
    import os
    cdir = ".kcache"; fp = os.path.join(cdir, pair + ".json")
    try:
        if os.path.exists(fp) and time.time() - os.path.getmtime(fp) < 6*3600:
            with open(fp, encoding="utf-8") as fh:
                cached = json.load(fh)
            if cached: return cached[-max_days:]
    except Exception:
        pass
    out = {}
    end = None
    for _ in range(3):
        url = BASE + "?symbol=" + pair + "&interval=1d&limit=1000"
        if end is not None: url += "&endTime=" + str(end)
        try:
            req = urllib.request.Request(url, headers={"User-Agent":"gridscout-gen/1.0"})
            data = json.load(urllib.request.urlopen(req, timeout=30))
        except Exception:
            break
        if not data: break
        for k in data: out[int(k[0])] = float(k[4])
        end = int(data[0][0]) - 1
        if len(out) >= max_days: break
        time.sleep(0.12)
    if not out: return []
    series = [out[t] for t in sorted(out.keys())][-max_days:]
    try:
        os.makedirs(cdir, exist_ok=True)
        with open(fp, "w", encoding="utf-8") as fh:
            json.dump(series, fh)
    except Exception:
        pass
    return series

def regimes(P):
    N = len(P); reg = [None]*N
    for i in range(49, N):
        s20 = sum(P[i-19:i+1])/20.0
        s50 = sum(P[i-49:i+1])/50.0
        p = P[i]
        reg[i] = "bull" if (p>s20 and s20>s50) else ("bear" if (p<s20 and s20<s50) else "side")
    return reg

def sim(prices, low, high, n, spacing, fee=0.001):
    """neutral grid, returns (realizedPct, netPLpct) — matches detailedSim neutral branch."""
    if low <= 0: return (0.0, 0.0)
    if high <= low: high = low*1.01
    if spacing == "arith":
        sw = (high-low)/n; levels = [low+sw*i for i in range(n+1)]
    else:
        ratio = (high/low)**(1.0/n); levels = [low*(ratio**i) for i in range(n+1)]
    invest = 10000.0; v = invest/n; p0 = prices[0]; endP = prices[-1]
    cash = invest; lots = []; realized = 0.0
    # AUDIT FIX: lot cost includes the entry fee (parity with the page's corrected detailedSim)
    for i in range(n+1):
        if levels[i] > p0:
            q = v/p0; cash -= v; cash -= v*fee; lots.append([i,q,v+v*fee])
    for t in range(1, len(prices)):
        prev = prices[t-1]; cur = prices[t]
        if cur < prev:
            for i in range(n+1):
                L = levels[i]
                if L <= prev and L > cur and cash >= v:
                    q = v/L; cash -= v; cash -= v*fee; lots.append([i,q,v+v*fee])
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
                        cash += proceeds - f; realized += (proceeds - cost - f)
                        del lots[idx]
    invVal = sum(l[1]*endP for l in lots); invCost = sum(l[2] for l in lots)
    netProfit = realized + (invVal - invCost)
    return (realized/invest*100.0, netProfit/invest*100.0)

def optimize_grid(prices):
    pos = [p for p in prices if p > 0]
    if len(pos) < 3: return (8, "geo")
    low = min(pos); high = max(pos)
    if high <= low: high = low*1.01
    geo = {}; ari = {}; bg = None; ba = None
    for n in range(5, 31):
        rg = sim(prices, low, high, n, "geo");  geo[n] = rg
        if bg is None or rg[0] > bg[0]: bg = (rg[0], rg[1], n)
        ra = sim(prices, low, high, n, "arith"); ari[n] = ra
        if ba is None or ra[0] > ba[0]: ba = (ra[0], ra[1], n)
    if ba[0] > bg[0] + SP_TOL: spacing, pool, best = "arith", ari, ba
    else:                      spacing, pool, best = "geo",   geo, bg
    chosen = best[2]
    for n in range(5, best[2]):
        if pool[n][1] >= best[1] - 0.5: chosen = n; break
    return (chosen, spacing)

def pct(counts):
    tot = counts[0]+counts[1]+counts[2]
    if tot == 0: return None
    b = round(counts[0]/tot*100); s = round(counts[1]/tot*100); be = round(counts[2]/tot*100)
    diff = 100 - (b+s+be); m = max(b, s, be)
    if   m == b:  b += diff
    elif m == s:  s += diff
    else:         be += diff
    return {"bull": b, "side": s, "bear": be, "n": tot}

def build(sym, P):
    N = len(P)
    rets = [P[i]/P[i-1]-1 for i in range(1, N) if P[i-1] > 0]
    if not rets: return None
    mean = sum(rets)/len(rets)
    sd = math.sqrt(sum((r-mean)**2 for r in rets)/len(rets))
    reg = regimes(P)
    REGS = ("bull","side","bear"); CLS = {"bull":0,"side":1,"bear":2}
    h = {}
    for hk, H in HORIZONS:
        start = 49 if hk == "h24" else max(49, H)
        last  = N-1-H
        if last - start + 1 < MIN_WIN: continue
        thr = max(0.06, sd*math.sqrt(H)*0.5)
        allc = [0,0,0]; regc = {r:[0,0,0] for r in REGS}
        # success config + sampling
        cfgN, cfgSp = optimize_grid(P[-H:] if hk != "h24" else P[-7:])
        do_succ = hk != "h24"
        nwin = last - start + 1
        stride = max(1, nwin // SUCC_CAP)
        sa = [0,0]; sr = {r:[0,0] for r in REGS}
        for idx, i in enumerate(range(start, last+1)):
            net = P[i+H]/P[i] - 1
            c = "bull" if net > thr else ("bear" if net < -thr else "side")
            allc[CLS[c]] += 1
            r = reg[i] or "side"
            regc[r][CLS[c]] += 1
            if do_succ and (idx % stride == 0):
                prior = P[i-H:i+1]; lo = min(prior); hi = max(prior)
                _, netpl = sim(P[i:i+H+1], lo, hi, cfgN, cfgSp)
                ok = 1 if netpl > 0 else 0
                sa[0] += ok; sa[1] += 1
                sr[r][0] += ok; sr[r][1] += 1
        alld = pct(allc)
        if alld is None: continue
        # AUDIT FIX: success rates need >=10 simulated windows, else null (tiny stride samples were misleading)
        alld["success"] = (round(sa[0]/sa[1]*100) if (do_succ and sa[1] >= 10) else None)
        byReg = {}
        for r in REGS:
            rd = pct(regc[r])
            if rd is None or rd["n"] < 10: continue
            rd["success"] = (round(sr[r][0]/sr[r][1]*100) if (do_succ and sr[r][1] >= 10) else None)
            byReg[r] = rd
        h[hk] = {"all": alld, "byReg": byReg, "cfgN": cfgN, "cfgSp": cfgSp}
    if not h: return None
    return {"symbol": sym, "curRegime": (reg[N-1] or "side"), "h": h, "days": N}

def main():
    coins = []
    for i, sym in enumerate(SYMBOLS):
        pair = sym + "USDT"
        P = fetch_daily(pair)
        if len(P) < 110:
            print(f"  [{i+1}/{len(SYMBOLS)}] {sym:6s} SKIP (history={len(P)})", flush=True)
            continue
        c = build(sym, P)
        if not c:
            print(f"  [{i+1}/{len(SYMBOLS)}] {sym:6s} SKIP (no horizons)", flush=True)
            continue
        coins.append(c)
        print(f"  [{i+1}/{len(SYMBOLS)}] {sym:6s} ok  days={c['days']:4d} horizons={','.join(c['h'].keys())} reg={c['curRegime']}", flush=True)
    out = {
        "generated": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "source": "Binance daily klines (data-api.binance.vision)",
        "method": "forward base rates by horizon, regime-conditioned (SMA20/50); neutral-grid success rate; board blends 60% climatology + 40% current regime",
        "coins": coins,
    }
    with open(OUT, "w", encoding="utf-8") as f:
        json.dump(out, f, separators=(",", ":"))
    # self-validation against the board's contract
    bad = []
    for c in coins:
        for hk, hd in c["h"].items():
            a = hd["all"]
            if a["bull"]+a["side"]+a["bear"] != 100: bad.append((c["symbol"],hk,"all-sum",a["bull"]+a["side"]+a["bear"]))
            for r, rd in hd["byReg"].items():
                if rd["bull"]+rd["side"]+rd["bear"] != 100: bad.append((c["symbol"],hk,"reg-sum",r))
    print(f"\nWROTE {OUT}: {len(coins)} coins")
    print("VALIDATION:", "ALL DISTRIBUTIONS SUM TO 100" if not bad else f"{len(bad)} sum errors: {bad[:5]}")

if __name__ == "__main__":
    main()
