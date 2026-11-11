#!/usr/bin/env python3
"""NSE intraday opening-range tools, adapted from the US day-trader-skill pack.

Commands:
  backtest --setup orb60|orb15 --universe nifty100|midcap150 [--refresh]
  scan     [--universe nifty100] [--at HH:MM]
  check    --entry X --stop Y [--target Z] [--time HH:MM] [--trades-today N] [--loss-today RS]
  replay   SYMBOL --entry X --stop Y [--target Z] [--at HH:MM] [--paths 10000] [--seed 19]

Rules are in references/rules.md. This script never places orders.
"""
import argparse
import datetime as dt
import json
import math
import os
import sys
import time
import warnings
from urllib.parse import quote

import numpy as np
import pandas as pd

HERE = os.path.dirname(os.path.abspath(__file__))
SKILL = os.path.dirname(HERE)
ROOT = os.path.abspath(os.path.join(SKILL, "..", "..", ".."))
REF = os.path.join(ROOT, ".claude", "skills", "india-swing-trader", "references")
DATA = os.path.join(ROOT, "trading", "data")
OUT = os.path.join(ROOT, "trading", "intraday")
IST = "Asia/Kolkata"
HIST = {"nifty100": "nifty100_history.json", "midcap150": "midcap150_history.json"}
BENCH = {"nifty100": ("^NSEI", "Nifty 50"), "midcap150": ("^NSEMDCP50", "Nifty Midcap 50")}
SETUPS = {
    "orb15": dict(interval="5m", range="60d", or_bars=3, last_trigger="11:00"),
    "orb60": dict(interval="60m", range="730d", or_bars=1, last_trigger="12:15"),
}
SPLIT = "2025-07-01"


# ---------------------------------------------------------------- basics

def load_config():
    with open(os.path.join(SKILL, "config.json")) as f:
        return json.load(f)


def charges(buy, sell, cfg):
    """Dhan intraday charges in rupees for one buy and one sell."""
    c = cfg["charges"]
    brk = lambda v: min(v * c["brokerage_pct"] / 100, c["brokerage_cap_rs"]) if v > 0 else 0.0
    b, t = brk(buy) + brk(sell), buy + sell
    txn, sebi = t * c["exchange_txn_pct"] / 100, t * c["sebi_pct"] / 100
    total = b + sell * c["stt_sell_pct"] / 100 + txn + sebi + buy * c["stamp_buy_pct"] / 100
    return round(total + (b + txn + sebi) * c["gst_pct"] / 100, 2)


def size(equity, entry, stop, cfg):
    """Whole shares inside the risk and position limits (no margin unless leverage > 1)."""
    risk = entry - stop
    if risk <= 0:
        return 0
    return math.floor(min(cfg["risk_per_trade_pct"] / 100 * equity / risk,
                          equity * cfg["leverage"] / cfg["max_positions"] / entry))


def history(universe):
    with open(os.path.join(REF, HIST[universe])) as f:
        return json.load(f)["history"]


def members_on(hist, day):
    day, cur = str(day), hist[0][1]
    for start, names in hist:
        if start > day:
            break
        cur = names
    return set(cur)


def members_since(hist, day):
    day, out = str(day), set()
    for k, (_, names) in enumerate(hist):
        end = hist[k + 1][0] if k + 1 < len(hist) else "9999"
        if end > day:
            out |= set(names)
    return out


def slots(interval):
    step = 5 if interval == "5m" else 60
    t, out = dt.datetime(2000, 1, 1, 9, 15), []
    while t.time() < dt.time(15, 30):
        out.append(t.strftime("%H:%M"))
        t += dt.timedelta(minutes=step)
    return out


_session = None


def fetch(ticker, interval, rng):
    """Bars from Yahoo's chart endpoint, indexed by naive IST bar-start time."""
    global _session
    if _session is None:
        import requests
        _session = requests.Session()
        _session.headers["User-Agent"] = "Mozilla/5.0"
    url = "https://query1.finance.yahoo.com/v8/finance/chart/" + quote(ticker)
    for attempt in range(5):
        try:
            r = _session.get(url, params=dict(range=rng, interval=interval), timeout=30)
        except Exception:
            r = None
        if r is not None and r.status_code == 200:
            break
        if r is not None and r.status_code == 404:
            return None
        time.sleep(2 ** attempt)
    else:
        return None
    res = r.json()["chart"]["result"]
    if not res or "timestamp" not in res[0]:
        return None
    q = res[0]["indicators"]["quote"][0]
    idx = pd.to_datetime(res[0]["timestamp"], unit="s", utc=True).tz_convert(IST).tz_localize(None)
    df = pd.DataFrame({k[0].upper(): q[k] for k in ("open", "high", "low", "close", "volume")}, index=idx)
    df = df.dropna(subset=["C"]).astype(float)
    return df[~df.index.duplicated(keep="last")]


def now_ist():
    return pd.Timestamp.now(tz=IST).tz_localize(None)


# ---------------------------------------------------------------- data

def load_bars(universe, setup, refresh=False):
    s = SETUPS[setup]
    path = os.path.join(DATA, f"intraday_{universe}_{s['interval']}.pkl")
    if os.path.exists(path) and not refresh:
        return pd.read_pickle(path)
    days_back = 1150 if s["interval"] == "60m" else 100
    syms = sorted(members_since(history(universe), (now_ist() - pd.Timedelta(days=days_back)).date()))
    frames, missing = {}, []
    for sym in syms:
        df = fetch(sym + ".NS", s["interval"], s["range"])
        if df is not None and len(df):
            frames[sym] = df
        else:
            missing.append(sym)
        time.sleep(0.3)
    for sym in list(missing):
        time.sleep(2)
        df = fetch(sym + ".NS", s["interval"], s["range"])
        if df is not None and len(df):
            frames[sym] = df
            missing.remove(sym)
    if missing:
        print("No intraday data for:", ", ".join(missing), file=sys.stderr)
    data = dict(bars=frames, missing=missing, fetched=str(now_ist()))
    os.makedirs(DATA, exist_ok=True)
    pd.to_pickle(data, path)
    return data


def build(frames, interval):
    syms = sorted(frames)
    F = {f: pd.DataFrame({s: frames[s][f] for s in syms}).sort_index() for f in "OHLCV"}
    keep = F["C"].index.strftime("%H:%M").isin(slots(interval))
    return syms, {f: v[keep] for f, v in F.items()}


# ---------------------------------------------------------------- simulation

def simulate(syms, F, member_fn, setup, cfg, universe, start, end, capital):
    """Portfolio simulation of the opening-range breakout. Returns (daily curve, trades)."""
    s = SETUPS[setup]
    k, slip = s["or_bars"], cfg["slippage_pct"][universe] / 100
    O, H, L, C, V = (F[f].values for f in "OHLCV")
    idx = F["C"].index
    times, dates = np.array(idx.strftime("%H:%M")), np.array(idx.date)
    starts = np.flatnonzero(np.r_[True, dates[1:] != dates[:-1]])
    eq, curve, trades = capital, [], []
    for a, b in zip(starts, list(starts[1:]) + [len(dates)]):
        d = dates[a]
        if not (start <= str(d) < end) or times[a] != "09:15" or b - a <= k + 1:
            continue
        tt, o, h, l, c, v = times[a:b], O[a:b], H[a:b], L[a:b], C[a:b], V[a:b]
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", RuntimeWarning)
            orh, orl = np.nanmax(h[:k], axis=0), np.nanmin(l[:k], axis=0)
        mid = (orh + orl) / 2
        flat = np.flatnonzero(tt >= cfg["flat_by"])
        fi, has_flat = (flat[0], True) if len(flat) else (len(tt) - 1, False)
        lt = np.flatnonzero(tt <= s["last_trigger"])[-1]
        with np.errstate(invalid="ignore"):
            above = c[k:lt + 1] > orh
        cand = []
        for j in np.flatnonzero(member_fn(d) & above.any(axis=0) & np.isfinite(orh)):
            i = k + int(np.argmax(above[:, j]))
            if i + 1 < fi:
                cand.append((i + 1, -c[i, j] * np.nan_to_num(v[i, j]), j))
        cand.sort()
        day_eq, realized, taken, pos, ci = eq, 0.0, 0, {}, 0

        def close(j, px, why, t):
            p = pos.pop(j)
            ex = px * (1 - slip)
            fee = charges(p["qty"] * p["ent"], p["qty"] * ex, cfg)
            pnl = p["qty"] * (ex - p["ent"]) - fee
            trades.append(dict(date=str(d), symbol=syms[j], entry_time=tt[p["t"]], exit_time=tt[t],
                               qty=p["qty"], entry=round(p["ent"], 2), stop=round(p["stop"], 2),
                               target=round(p["tgt"], 2), exit=round(ex, 2), fees=fee,
                               pnl=round(pnl, 2), r=round(pnl / (p["qty"] * p["R"]), 2), reason=why))
            return pnl

        for t in range(k + 1, fi + 1):
            if t == fi:
                for j in list(pos):
                    px = o[t, j] if has_flat and np.isfinite(o[t, j]) else None
                    if px is None:
                        cs = c[:t + 1, j]
                        px = cs[np.isfinite(cs)][-1]
                    realized += close(j, px, "flat", t)
                break
            while ci < len(cand) and cand[ci][0] == t:
                j = cand[ci][2]
                ci += 1
                if (taken >= cfg["max_trades_per_day"] or len(pos) >= cfg["max_positions"]
                        or realized <= -cfg["daily_loss_limit_pct"] / 100 * day_eq or not np.isfinite(o[t, j])):
                    continue
                ent, stop = o[t, j] * (1 + slip), mid[j]
                if ent <= stop or (ent - stop) / ent * 100 < cfg["min_stop_pct"]:
                    continue
                qty = size(day_eq, ent, stop, cfg)
                if qty < 1:
                    continue
                pos[j] = dict(qty=qty, ent=ent, stop=stop, tgt=ent + cfg["target_r"] * (ent - stop),
                              t=t, R=ent - stop)
                taken += 1
            for j in list(pos):
                p, lo, hi, op = pos[j], l[t, j], h[t, j], o[t, j]
                if not np.isfinite(lo):
                    continue
                op = op if np.isfinite(op) else c[t, j]
                if lo <= p["stop"]:
                    realized += close(j, min(op, p["stop"]), "stop", t)
                elif hi >= p["tgt"]:
                    realized += close(j, max(op, p["tgt"]), "target", t)
        eq = day_eq + realized
        curve.append((d, eq))
    return curve, trades


def stats(curve, trades, bench, capital):
    eq = pd.Series([e for _, e in curve], index=pd.to_datetime([d for d, _ in curve]))
    yrs = max((eq.index[-1] - eq.index[0]).days, 1) / 365.25
    full = pd.concat([pd.Series([capital], index=[eq.index[0] - pd.Timedelta(days=1)]), eq])
    mv = full.resample("ME").last()
    m = mv.pct_change()
    m.iloc[0] = mv.iloc[0] / capital - 1
    pnl = np.array([t["pnl"] for t in trades])
    r = np.array([t["r"] for t in trades])
    w, l_ = pnl[pnl > 0], pnl[pnl <= 0]
    fees = sum(t["fees"] for t in trades)
    reasons = pd.Series([t["reason"] for t in trades]).value_counts().to_dict()
    b = bench[(bench.index >= eq.index[0]) & (bench.index <= eq.index[-1])]
    return dict(
        sessions=len(eq), trades=len(trades), trades_per_day=round(len(trades) / len(eq), 2),
        win_rate=round(100 * len(w) / max(len(pnl), 1), 1),
        avg_r=round(float(r.mean()), 3) if len(r) else 0,
        profit_factor=round(float(w.sum() / -l_.sum()), 2) if l_.sum() < 0 else None,
        final_equity=round(float(eq.iloc[-1])),
        cagr_pct=round(100 * ((eq.iloc[-1] / capital) ** (1 / yrs) - 1), 1),
        max_dd_pct=round(100 * (full / full.cummax() - 1).min(), 1),
        avg_month_pct=round(100 * m.mean(), 2), worst_month_pct=round(100 * m.min(), 1),
        months_positive_pct=round(100 * (m > 0).mean()), fees_rs=round(fees),
        fees_pct_of_gross=round(100 * fees / (pnl.sum() + fees)) if pnl.sum() + fees > 0 else None,
        exits=reasons,
        bench_cagr_pct=round(100 * ((b.iloc[-1] / b.iloc[0]) ** (1 / yrs) - 1), 1) if len(b) > 1 else None,
        bench_max_dd_pct=round(100 * (b / b.cummax() - 1).min(), 1) if len(b) > 1 else None)


def member_mask_fn(syms, universe):
    hist, cache = history(universe), {}

    def fn(day):
        key = max((s for s, _ in hist if s <= str(day)), default=hist[0][0])
        if key not in cache:
            names = members_on(hist, day)
            cache[key] = np.array([s in names for s in syms])
        return cache[key]
    return fn


# ---------------------------------------------------------------- commands

def cmd_backtest(a):
    cfg = load_config()
    data = load_bars(a.universe, a.setup, a.refresh)
    syms, F = build(data["bars"], SETUPS[a.setup]["interval"])
    bt, bname = BENCH[a.universe]
    bdf = fetch(bt, "1d", "5y")
    bench = bdf["C"].copy()
    bench.index = bench.index.normalize()
    first = str(F["C"].index[0].date())
    end = str((F["C"].index[-1] + pd.Timedelta(days=1)).date())
    periods = ({"in_sample": [first, SPLIT], "out_of_sample": [SPLIT, end]} if a.setup == "orb60"
               else {"check": [first, end]})
    mfn = member_mask_fn(syms, a.universe)
    out = dict(meta=dict(setup=a.setup, universe=a.universe, capital=cfg["capital"], symbols=len(syms),
                         no_data=data["missing"], benchmark=bname, periods=periods,
                         last_bar=str(F["C"].index[-1])))
    for name, (s, e) in periods.items():
        curve, trades = simulate(syms, F, mfn, a.setup, cfg, a.universe, s, e, cfg["capital"])
        out[name] = dict(stats=stats(curve, trades, bench, cfg["capital"]), trades=trades)
    os.makedirs(OUT, exist_ok=True)
    path = os.path.join(OUT, f"backtest_{a.setup}_{a.universe}.json")
    with open(path, "w") as f:
        json.dump(out, f, indent=1)
    print(json.dumps(out["meta"]))
    for name in periods:
        print(name, json.dumps(out[name]["stats"]))


def day_matrix(df, interval="5m"):
    """Per-session arrays [days, slots] of O, H, L, C with gaps filled as flat bars."""
    sl = slots(interval)
    df = df[df.index.strftime("%H:%M").isin(sl)]
    days = sorted(set(df.index.date))
    M = {f: np.full((len(days), len(sl)), np.nan) for f in "OHLC"}
    pos = {t: i for i, t in enumerate(sl)}
    di = {d: i for i, d in enumerate(days)}
    for ts, row in df.iterrows():
        for f in "OHLC":
            M[f][di[ts.date()], pos[ts.strftime("%H:%M")]] = row[f]
    C = pd.DataFrame(M["C"]).ffill(axis=1).values
    for f in "OHL":
        M[f] = np.where(np.isfinite(M[f]), M[f], C)
    M["C"] = C
    ok = np.isfinite(M["O"][:, 0])
    return [d for d, k in zip(days, ok) if k], {f: v[ok] for f, v in M.items()}, sl


def cmd_replay(a):
    cfg = load_config()
    df = fetch(a.symbol + ".NS", "5m", "60d")
    if df is None:
        sys.exit("No 5-minute data for " + a.symbol)
    days, M, sl = day_matrix(df)
    today = now_ist().date()
    past = [i for i, d in enumerate(days) if d < today]
    at = a.at or now_ist().strftime("%H:%M")
    s0 = next((i for i, t in enumerate(sl) if t >= at), None)
    fi = sl.index(cfg["flat_by"])
    if s0 is None or s0 >= fi:
        sys.exit(f"{at} is at or after the flat-by time {cfg['flat_by']}")
    entry, stop = a.entry, a.stop
    tgt = a.target or entry + cfg["target_r"] * (entry - stop)
    if not stop < entry < tgt:
        sys.exit("Need stop < entry < target")
    slip = cfg["slippage_pct"][a.universe] / 100
    prevC = np.concatenate([M["C"][:, :1], M["C"][:, :-1]], axis=1)
    rel = {f: M[f][past] / prevC[past] for f in "OHLC"}
    rng = np.random.default_rng(a.seed)
    n, steps = a.paths, fi - s0
    picks = rng.integers(0, len(past), size=(n, steps))
    price = np.full(n, entry)
    outcome, exit_px = np.zeros(n, int), np.full(n, np.nan)
    for step, s in enumerate(range(s0, fi)):
        d = picks[:, step]
        ro, rh, rl, rc = (rel[f][d, s] for f in "OHLC")
        base = entry / ro if step == 0 else price
        op, hi, lo, cl = base * ro, base * rh, base * rl, base * rc
        if step == 0:
            op = np.full(n, entry)
        live = outcome == 0
        hs = live & (lo <= stop)
        ht = live & ~hs & (hi >= tgt)
        exit_px[hs], outcome[hs] = np.minimum(op, stop)[hs], -1
        exit_px[ht], outcome[ht] = np.maximum(op, tgt)[ht], 1
        price = cl
    exit_px[outcome == 0] = price[outcome == 0]
    qty = max(size(cfg["capital"], entry * (1 + slip), stop, cfg), 1)
    buy = entry * (1 + slip)
    fee = charges(qty * buy, qty * entry, cfg)
    net_r = (qty * (exit_px * (1 - slip) - buy) - fee) / (qty * (buy - stop))
    # history: the ORB15 rule on this stock's own past sessions
    hist_df = df[pd.Index(df.index.date).isin([days[i] for i in past])]
    syms, F = build({a.symbol: hist_df}, "5m")
    _, tr = simulate(syms, F, lambda d: np.array([True]), "orb15", dict(cfg, max_positions=1),
                     a.universe, "0000", "9999", cfg["capital"])
    hr = np.array([t["r"] for t in tr])
    res = dict(
        symbol=a.symbol, at=sl[s0], entry=entry, stop=stop, target=round(tgt, 2), paths=n, seed=a.seed,
        sessions_sampled=len(past), first_session=str(days[past[0]]), last_session=str(days[past[-1]]),
        target_first_pct=round(100 * (outcome == 1).mean(), 1),
        stop_first_pct=round(100 * (outcome == -1).mean(), 1),
        open_at_flat_pct=round(100 * (outcome == 0).mean(), 1),
        flat_price_p10_p50_p90=[round(float(x), 2) for x in np.percentile(price, [10, 50, 90])],
        avg_r_after_costs=round(float(net_r.mean()), 3),
        history=dict(times_fired=len(tr), target=sum(t["reason"] == "target" for t in tr),
                     stop=sum(t["reason"] == "stop" for t in tr), flat=sum(t["reason"] == "flat" for t in tr),
                     avg_r_after_costs=round(float(hr.mean()), 3) if len(hr) else None))
    m, h = res["avg_r_after_costs"], res["history"]["avg_r_after_costs"]
    if m < -0.1 or (h is not None and h < -0.1):
        verdict = "Negative after costs. Skip it."
    elif m > 0.1 and h is not None and h > 0.1 and len(tr) >= 15:
        verdict = "Positive after costs in both views, on a small sample. Not a promise."
    else:
        verdict = "Close to a coin flip after costs."
    res["verdict"] = verdict
    print(json.dumps(res, indent=2))


def cmd_check(a):
    cfg = load_config()
    eq = a.equity or cfg["capital"]
    entry, stop = a.entry, a.stop
    tgt = a.target or entry + cfg["target_r"] * (entry - stop)
    block = []
    if stop >= entry:
        block.append("stop must be below entry (long only)")
    elif (entry - stop) / entry * 100 < cfg["min_stop_pct"]:
        block.append(f"stop is less than {cfg['min_stop_pct']}% below entry: too tight to survive costs and noise")
    if tgt <= entry:
        block.append("target must be above entry")
    if a.time:
        lo, hi = cfg["entry_window"]
        if not lo <= a.time <= hi:
            block.append(f"{a.time} is outside the entry window {lo}-{hi}")
    if a.trades_today >= cfg["max_trades_per_day"]:
        block.append(f"already {a.trades_today} trades today (limit {cfg['max_trades_per_day']})")
    if a.loss_today >= cfg["daily_loss_limit_pct"] / 100 * eq:
        block.append(f"today's loss Rs {a.loss_today:.0f} has reached the daily limit")
    out = dict(equity=eq, entry=entry, stop=stop, target=round(tgt, 2))
    qty = size(eq, entry, stop, cfg) if stop < entry else 0
    if qty < 1 and not block:
        block.append("quantity below 1 within the position cap")
    if qty >= 1:
        v = qty * entry
        loss = qty * (entry - stop) + charges(v, qty * stop, cfg)
        gain = qty * (tgt - entry) - charges(v, qty * tgt, cfg)
        out.update(qty=qty, value=round(v, 2), round_trip_charges=charges(v, v, cfg),
                   max_loss_at_stop_incl_charges=round(loss, 2), net_gain_at_target=round(gain, 2),
                   reward_to_risk_after_costs=round(gain / loss, 2), flat_by=cfg["flat_by"])
        if gain / loss < cfg["min_reward_to_risk_after_costs"]:
            block.append(f"reward to risk after costs below {cfg['min_reward_to_risk_after_costs']}")
    out["verdict"] = "BLOCK" if block else "PASS"
    out["reasons"] = block
    print(json.dumps(out, indent=2))


def cmd_scan(a):
    cfg = load_config()
    s = SETUPS["orb15"]
    now = now_ist()
    syms = sorted(members_on(history(a.universe), now.date()))
    rows, session = [], None
    for sym in syms:
        df = fetch(sym + ".NS", "5m", "5d")
        time.sleep(0.2)
        if df is None or df.empty:
            continue
        session = session or max(df.index.date)
        df = df[df.index.date == session]
        cutoff = pd.Timestamp.combine(session, dt.time(*map(int, (a.at or "23:59").split(":"))))
        if session == now.date():
            cutoff = min(cutoff, now)
        df = df[df.index + pd.Timedelta(minutes=5) <= cutoff]
        df = df[df.index.strftime("%H:%M").isin(slots("5m"))]
        if len(df) < s["or_bars"] or df.index[0].strftime("%H:%M") != "09:15":
            rows.append(dict(symbol=sym, status="forming" if len(df) else "no bars"))
            continue
        orh, orl = df["H"].iloc[:3].max(), df["L"].iloc[:3].min()
        after = df.iloc[3:]
        after = after[after.index.strftime("%H:%M") <= s["last_trigger"]]
        hit = after[after["C"] > orh]
        last = float(df["C"].iloc[-1])
        row = dict(symbol=sym, or_high=round(orh, 2), or_low=round(orl, 2), stop=round((orh + orl) / 2, 2),
                   last_close=round(last, 2), last_bar=df.index[-1].strftime("%H:%M"),
                   or_width_pct=round(100 * (orh - orl) / orl, 2))
        if len(hit):
            row.update(status="triggered", trigger_bar=hit.index[0].strftime("%H:%M"),
                       trigger_close=round(float(hit["C"].iloc[0]), 2))
        elif df.index[-1].strftime("%H:%M") > s["last_trigger"]:
            row.update(status="expired")
        else:
            row.update(status="waiting", to_trigger_pct=round(100 * (orh / last - 1), 2))
        rows.append(row)
    trig = [r for r in rows if r["status"] == "triggered"]
    wait = sorted([r for r in rows if r["status"] == "waiting"], key=lambda r: r["to_trigger_pct"])
    out = dict(universe=a.universe, session=str(session), scanned_at=str(now)[:16],
               market_open_today=session == now.date(), counts=pd.Series([r["status"] for r in rows]).value_counts().to_dict(),
               triggered=sorted(trig, key=lambda r: r["trigger_bar"]), nearest_waiting=wait[:10])
    os.makedirs(OUT, exist_ok=True)
    with open(os.path.join(OUT, "watchlist.json"), "w") as f:
        json.dump(out, f, indent=1)
    print(json.dumps(out, indent=2))


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("backtest")
    p.add_argument("--setup", choices=list(SETUPS), default="orb60")
    p.add_argument("--universe", choices=list(HIST), default="nifty100")
    p.add_argument("--refresh", action="store_true")
    p = sub.add_parser("scan")
    p.add_argument("--universe", choices=list(HIST), default="nifty100")
    p.add_argument("--at", help="HH:MM, ignore bars ending after this time")
    p = sub.add_parser("check")
    for k in ("entry", "stop"):
        p.add_argument("--" + k, type=float, required=True)
    p.add_argument("--target", type=float)
    p.add_argument("--equity", type=float)
    p.add_argument("--time", help="HH:MM IST of the intended entry")
    p.add_argument("--trades-today", type=int, default=0)
    p.add_argument("--loss-today", type=float, default=0.0)
    p = sub.add_parser("replay")
    p.add_argument("symbol")
    p.add_argument("--entry", type=float, required=True)
    p.add_argument("--stop", type=float, required=True)
    p.add_argument("--target", type=float)
    p.add_argument("--at", help="HH:MM IST of the entry (default: now)")
    p.add_argument("--paths", type=int, default=10000)
    p.add_argument("--seed", type=int, default=19)
    p.add_argument("--universe", choices=list(HIST), default="nifty100")
    a = ap.parse_args()
    dict(backtest=cmd_backtest, scan=cmd_scan, check=cmd_check, replay=cmd_replay)[a.cmd](a)


if __name__ == "__main__":
    main()
