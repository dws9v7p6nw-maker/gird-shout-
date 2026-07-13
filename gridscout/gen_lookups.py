#!/usr/bin/env python3
"""
GridScout lookup generators -> dynstop_lookup.js + holdplan_lookup.js

Full Python port of the page's detailedSim (long / neutral / short, geo/arith,
fees, stop, max-drawdown), then two 3-year studies over real Binance history:

DYNSTOP[sym] = {p,s,b,u,dd,t}
  Set-&-forget stop study: neutral geo grid, 30-day segments re-banded to the
  prior 30-day range, stop distances 6%..30% below the segment low tested per
  starting regime (SMA20/50). s/b/u = best distance per sideways/bear/bull
  start; dd = average max-drawdown points cut vs no-stop at the sideways
  distance; p='None' when no-stop beat every stop overall (drawdown-tolerant
  coin); t = trust from sample size + dd cut.

HOLDPLAN[sym][d7|d30|d90|d365] = {g,m,p,gy,pb,ps,pr,n,bs,mv,tr}
  Holding-period planner study: forward windows over the last ~3y.
  pb/ps/pr = bull/side/bear base rates (regime-conditioned when the current
  regime has >=15 windows, bs='now-regime:<reg>', else bs='all'); the
  volatility-scaled threshold matches computeLivePlan. m = mode rule identical
  to the prediction board (long if pb>=45&&pb>ps; short if pr>=40&&pr>ps; else
  neutral). g/gy = median optimal grid count & median net P&L of that mode's
  grid across sampled windows (n-sweep 5..29 step 2, geo-preferred SP_TOL=1,
  parsimony within 0.5pp).

REGIME[sym] = current regime (also marks ~3y-history coins for the page's filter).

All numbers computed from real data. Sampling strides are documented inline.
"""
import json, math, time, sys
try: sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception: pass
from gen_predict import fetch_daily, SYMBOLS

SP_TOL = 1.0

def regimes(P):
    N = len(P); reg = [None]*N
    for i in range(49, N):
        s20 = sum(P[i-19:i+1])/20.0
        s50 = sum(P[i-49:i+1])/50.0
        p = P[i]
        reg[i] = "bull" if (p>s20 and s20>s50) else ("bear" if (p<s20 and s20<s50) else "side")
    return reg

def dsim(prices, low, high, n, dirn="neutral", spacing="geo", fee=0.001, stop=None):
    """Faithful port of detailedSim -> dict(realized, net, rt, maxdd, stopped). % on 10k."""
    if low <= 0: low = 1e-9
    if high <= low: high = low*1.01
    if spacing == "arith":
        sw = (high-low)/n; levels = [low+sw*i for i in range(n+1)]
    else:
        r = (high/low)**(1.0/n); levels = [low*(r**i) for i in range(n+1)]
    invest = 10000.0; v = invest/n; p0 = prices[0]; endP = prices[-1]
    realized = 0.0; rt = 0; peak = invest; maxdd = 0.0; stopped = False
    if dirn == "short":
        shorts = []
        for i in range(n+1):
            if levels[i] > p0: shorts.append([i, v/p0, p0])
        for t in range(1, len(prices)):
            prev, cur = prices[t-1], prices[t]
            if stopped: continue
            if stop is not None and cur >= stop:
                for s in shorts:
                    f = (s[1]*stop)*fee; realized += (s[2]-stop)*s[1]-f
                shorts = []; stopped = True
                eqv = invest+realized
                peak = max(peak, eqv); maxdd = max(maxdd, (peak-eqv)/peak); continue
            if cur > prev:
                for i in range(n+1):
                    L = levels[i]
                    if L > prev and L <= cur: shorts.append([i, v/L, L])
            elif cur < prev:
                for i in range(n+1):
                    L = levels[i]
                    if L <= prev and L > cur:
                        idx = -1
                        for k in range(len(shorts)):
                            if shorts[k][0] > i: idx = k; break
                        if idx >= 0:
                            lot = shorts.pop(idx)
                            f = (lot[1]*L)*fee; realized += (lot[2]-L)*lot[1]-f; rt += 1
            eqv = invest+realized+sum((s[2]-cur)*s[1] for s in shorts)
            peak = max(peak, eqv); maxdd = max(maxdd, (peak-eqv)/peak if peak>0 else 0)
        openPL = sum((s[2]-endP)*s[1] for s in shorts)
    else:
        anchor = high if dirn == "long" else p0
        cash = invest; lots = []
        for i in range(n+1):
            if levels[i] > anchor:
                q = v/p0; cash -= v; cash -= v*fee; lots.append([i, q, v])
        for t in range(1, len(prices)):
            prev, cur = prices[t-1], prices[t]
            if stopped: continue
            if stop is not None and cur <= stop:
                for lot in lots:
                    proceeds = lot[1]*stop; f = proceeds*fee
                    cash += proceeds-f; realized += proceeds-lot[2]-f
                lots = []; stopped = True
                peak = max(peak, cash); maxdd = max(maxdd, (peak-cash)/peak); continue
            if cur < prev:
                for i in range(n+1):
                    L = levels[i]
                    if L <= prev and L > cur and cash >= v:
                        q = v/L; cash -= v; cash -= v*fee; lots.append([i, q, v])
            elif cur > prev:
                for i in range(n+1):
                    L = levels[i]
                    if L > prev and L <= cur:
                        idx = -1
                        for k in range(len(lots)):
                            if lots[k][0] < i: idx = k; break
                        if idx >= 0:
                            lot = lots.pop(idx)
                            proceeds = lot[1]*L; f = proceeds*fee
                            cash += proceeds-f; realized += proceeds-lot[2]-f; rt += 1
            eqv = cash+sum(l[1]*cur for l in lots)
            peak = max(peak, eqv); maxdd = max(maxdd, (peak-eqv)/peak if peak>0 else 0)
        openPL = sum(l[1]*endP for l in lots) - sum(l[2] for l in lots)
    net = realized+openPL
    return {"realized": realized/invest*100, "net": net/invest*100, "rt": rt,
            "maxdd": maxdd*100, "stopped": stopped}

def best_grid(prices, dirn):
    """optimizeGrid parity on an n-sweep (5..29 step2): geo-preferred, parsimony."""
    pos = [p for p in prices if p > 0]
    if len(pos) < 3: return (8, 0.0)
    low, high = min(pos), max(pos)
    NS = list(range(5, 30, 2))
    geo = {n: dsim(prices, low, high, n, dirn, "geo") for n in NS}
    ari = {n: dsim(prices, low, high, n, dirn, "arith") for n in NS}
    bg = max(NS, key=lambda n: geo[n]["realized"]); ba = max(NS, key=lambda n: ari[n]["realized"])
    if ari[ba]["realized"] > geo[bg]["realized"] + SP_TOL: pool, best = ari, ba
    else:                                                  pool, best = geo, bg
    for n in NS:
        if n >= best: break
        if pool[n]["net"] >= pool[best]["net"] - 0.5: best = n; break
    return (best, pool[best]["net"])

def median(xs):
    xs = sorted(xs); k = len(xs)
    return xs[k//2] if k % 2 else (xs[k//2-1]+xs[k//2])/2.0

# ---------- DYNSTOP ----------
STOP_DISTS = [round(0.06+0.02*i, 2) for i in range(13)]   # 6%..30%

def dynstop(sym, P, reg):
    N = len(P); seg = 30; start = max(50, N-1095)
    res = {"bull": {}, "side": {}, "bear": {}}   # dist -> [net_sum, dd_sum, cnt]
    nostop = {"bull": [0,0,0], "side": [0,0,0], "bear": [0,0,0]}
    nseg = 0; i = start
    while i + seg <= N-1:
        prior = P[i-seg:i+1]; lo, hi = min(prior), max(prior)
        r = reg[i] or "side"
        s0 = dsim(P[i:i+seg+1], lo, hi, 12, "neutral", "geo")
        nostop[r][0] += s0["net"]; nostop[r][1] += s0["maxdd"]; nostop[r][2] += 1
        for d in STOP_DISTS:
            s1 = dsim(P[i:i+seg+1], lo, hi, 12, "neutral", "geo", stop=lo*(1-d))
            a = res[r].setdefault(d, [0.0, 0.0, 0])
            a[0] += s1["net"]; a[1] += s1["maxdd"]; a[2] += 1
        nseg += 1; i += seg
    if nseg < 12: return None
    out = {}; better = 0
    for r in ("bear", "side", "bull"):
        if nostop[r][2] == 0: out[r] = 0.14; continue
        base_net = nostop[r][0]/nostop[r][2]
        best_d, best_sc = None, -1e18
        for d, a in res[r].items():
            if a[2] == 0: continue
            sc = a[0]/a[2] - 0.25*(a[1]/a[2])   # net minus a drawdown penalty
            if sc > best_sc: best_sc, best_d = sc, d
        base_sc = base_net - 0.25*(nostop[r][1]/nostop[r][2])
        if best_sc > base_sc + 0.05: better += 1
        out[r] = best_d if best_d is not None else 0.14
    tot_ns_dd = sum(nostop[r][1] for r in nostop); tot_ns_n = sum(nostop[r][2] for r in nostop)
    sd = out["side"]; dd_cut = 0.0; cnt = 0
    for r in res:
        a = res[r].get(sd)
        if a and a[2]: dd_cut += (nostop[r][1]/max(nostop[r][2],1)) - a[1]/a[2]; cnt += 1
    dd_pts = max(0, round(dd_cut/max(cnt,1)))
    if better == 0:
        return {"p": "None", "s": out["side"], "b": out["bear"], "u": out["bull"], "dd": dd_pts, "t": "none"}
    t = "high" if (nseg >= 30 and dd_pts >= 4) else ("medium" if nseg >= 24 else "low")
    return {"p": "Regime-tuned stop (3y)", "s": out["side"], "b": out["bear"], "u": out["bull"], "dd": dd_pts, "t": t}

# ---------- HOLDPLAN ----------
PERIODS = [("d7", 7), ("d30", 30), ("d90", 90), ("d365", 365)]
GK = {"d7": 40, "d30": 30, "d90": 18, "d365": 10}   # sampled windows for the grid sweep

def holdplan(sym, P, reg):
    N = len(P); base = max(50, N-1095-365)
    rets = [P[i]/P[i-1]-1 for i in range(1, N) if P[i-1] > 0]
    mean = sum(rets)/len(rets); sd = math.sqrt(sum((r-mean)**2 for r in rets)/len(rets))
    cur = reg[N-1] or "side"
    plans = {}
    for pk, H in PERIODS:
        start = max(base, H); last = N-1-H
        if last-start+1 < 25: continue
        thr = max(0.06, sd*math.sqrt(H)*0.5)
        allc = [0,0,0]; regc = {"bull": [0,0,0], "side": [0,0,0], "bear": [0,0,0]}
        moves = []
        for i in range(start, last+1):
            net = P[i+H]/P[i]-1; moves.append(net)
            c = 0 if net > thr else (2 if net < -thr else 1)
            allc[c] += 1; regc[reg[i] or "side"][c] += 1
        use, bs = (regc[cur], "now-regime:"+cur) if sum(regc[cur]) >= 15 else (allc, "all")
        tot = sum(use)
        pb, ps, pr = (round(use[0]/tot*100), round(use[1]/tot*100), round(use[2]/tot*100))
        pb += 100-(pb+ps+pr)   # rounding residue to bull slot
        p = "bull" if max(pb,ps,pr) == pb else ("bear" if max(ps,pr) == pr else "side")
        m = "long" if (pb >= 45 and pb > ps) else ("short" if (pr >= 40 and pr > ps) else "neutral")
        # grid sweep on K windows sampled evenly
        K = GK[pk]; idxs = list(range(start, last+1))
        stride = max(1, len(idxs)//K); samp = idxs[::stride][:K]
        gs, ys = [], []
        for i in samp:
            g, y = best_grid(P[i:i+H+1], m)
            gs.append(g); ys.append(y)
        n_win = tot
        tr = "high" if (bs != "all" and n_win >= 50) else ("medium" if n_win >= 20 else "low")
        plans[pk] = {"g": int(round(median(gs))), "m": m, "p": p,
                     "gy": round(median(ys), 1), "pb": pb, "ps": ps, "pr": pr,
                     "n": n_win, "bs": bs, "mv": round(sum(moves)/len(moves)*100, 1), "tr": tr}
    return plans if plans else None

def main():
    dyn, hold, regmap = {}, {}, {}
    t0 = time.time()
    for i, sym in enumerate(SYMBOLS):
        P = fetch_daily(sym+"USDT")
        if len(P) < 730:
            print(f"  [{i+1}/{len(SYMBOLS)}] {sym:6s} SKIP (days={len(P)})", flush=True); continue
        reg = regimes(P)
        d = dynstop(sym, P, reg)
        h = holdplan(sym, P, reg)
        if d: dyn[sym] = d
        if h: hold[sym] = h
        regmap[sym] = reg[-1] or "side"
        print(f"  [{i+1}/{len(SYMBOLS)}] {sym:6s} dynstop={'None' if not d else d['p'][:6]+'/'+str(d['s'])} plans={len(h) if h else 0} ({time.time()-t0:.0f}s)", flush=True)
    hdr = "/* generated %s from Binance daily klines (data-api.binance.vision) — see gen_lookups.py for methodology */\n" % time.strftime("%Y-%m-%d %H:%MZ", time.gmtime())
    with open("dynstop_lookup.js", "w", encoding="utf-8") as f:
        f.write(hdr+"var DYNSTOP="+json.dumps(dyn, separators=(",", ":"))+";\n")
    with open("holdplan_lookup.js", "w", encoding="utf-8") as f:
        f.write(hdr+"var HOLDPLAN="+json.dumps(hold, separators=(",", ":"))+";\nvar REGIME="+json.dumps(regmap, separators=(",", ":"))+";\n")
    none_ct = sum(1 for v in dyn.values() if v["p"] == "None")
    print(f"\nWROTE dynstop_lookup.js ({len(dyn)} coins, {none_ct} no-stop) + holdplan_lookup.js ({len(hold)} coins)")
    # validation
    bad = []
    for s, plans in hold.items():
        for pk, pl in plans.items():
            if pl["pb"]+pl["ps"]+pl["pr"] != 100: bad.append((s, pk))
            if not (2 <= pl["g"] <= 120): bad.append((s, pk, "g"))
            if pl["m"] not in ("long","neutral","short") or pl["tr"] not in ("high","medium","low"): bad.append((s, pk, "enum"))
    for s, v in dyn.items():
        if not (0.04 <= v["s"] <= 0.35): bad.append((s, "dynstop-s"))
    print("VALIDATION:", "PASS" if not bad else f"{len(bad)} problems: {bad[:6]}")

if __name__ == "__main__":
    main()
