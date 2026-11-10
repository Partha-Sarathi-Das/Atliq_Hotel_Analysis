#!/usr/bin/env python3
"""Portfolio backtest of the three candidate strategies (see references/strategies.md).

Usage: python3 backtest.py [--refresh] [--out results.json]
Prices are cached in trading/data/ (git-ignored).
"""
import argparse
import copy
import json
import os
import sys

import numpy as np
import pandas as pd

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
from position_size import charges, load_config, size_trade  # noqa: E402

ROOT = os.path.abspath(os.path.join(HERE, "..", "..", "..", ".."))
START, OOS_START = "2014-01-01", "2023-01-01"
UNIVERSES = {  # history file, in-sample start, extra benchmark ticker
    "nifty100": ("nifty100_history.json", "2015-01-01", None),
    "midcap150": ("midcap150_history.json", "2017-01-01", "^NSEMDCP50"),
}
UNI = "nifty100"


def cache_path():
    return os.path.join(ROOT, "trading", "data", f"prices_{UNI}.pkl")


def fetch_one(ticker, session):
    """Daily bars from Yahoo's chart endpoint (query1 only), adjusted for splits and dividends."""
    import time
    from urllib.parse import quote
    url = "https://query1.finance.yahoo.com/v8/finance/chart/" + quote(ticker)
    params = dict(period1=int(pd.Timestamp(START).timestamp()), period2=int(time.time()),
                  interval="1d", events="div,split")
    for attempt in range(4):
        r = session.get(url, params=params, timeout=30)
        if r.status_code == 200:
            break
        if r.status_code == 404:
            return None
        time.sleep(2 ** attempt)
    else:
        return None
    res = r.json()["chart"]["result"][0]
    if "timestamp" not in res:
        return None
    q = res["indicators"]["quote"][0]
    df = pd.DataFrame({k.capitalize(): q[k] for k in ("open", "high", "low", "close", "volume")},
                      index=pd.to_datetime(res["timestamp"], unit="s").normalize())
    adj = pd.Series(res["indicators"]["adjclose"][0]["adjclose"], index=df.index)
    f = adj / df["Close"]
    for k in ("Open", "High", "Low", "Close"):
        df[k] = df[k] * f
    df = df.dropna(subset=["Close"])
    return df[~df.index.duplicated(keep="last")]


def load_history():
    """Point-in-time Nifty 100 membership: list of [effective_from, members], oldest first."""
    with open(os.path.join(HERE, "..", "references", UNIVERSES[UNI][0])) as f:
        return json.load(f)["history"]


def load_prices(refresh=False):
    if os.path.exists(cache_path()) and not refresh:
        return pd.read_pickle(cache_path())
    import requests
    session = requests.Session()
    session.headers["User-Agent"] = "Mozilla/5.0"
    syms = sorted({x for _, m in load_history() for x in m})
    frames, missing = {}, []
    for t in [x + ".NS" for x in syms] + ["^NSEI"] + [b for b in [UNIVERSES[UNI][2]] if b]:
        df = fetch_one(t, session)
        if df is None or df.empty:
            missing.append(t)
        else:
            frames[t] = df
    import time
    for t in list(missing):  # second pass: rate limits cause transient failures
        time.sleep(1.5)
        df = fetch_one(t, session)
        if df is not None and not df.empty:
            frames[t] = df
            missing.remove(t)
    if missing:
        print("No data for:", ", ".join(missing), file=sys.stderr)
    raw = pd.concat(frames, axis=1, sort=True).swaplevel(axis=1).sort_index(axis=1)
    os.makedirs(os.path.dirname(cache_path()), exist_ok=True)
    raw.to_pickle(cache_path())
    return raw


def rsi(close, n):
    d = close.diff()
    up = d.clip(lower=0).ewm(alpha=1 / n, adjust=False, min_periods=n).mean()
    dn = (-d.clip(upper=0)).ewm(alpha=1 / n, adjust=False, min_periods=n).mean()
    return 100 - 100 / (1 + up / dn)


def build(raw):
    """Indicators and signals as date x symbol frames."""
    idx = raw["Close"]["^NSEI"].dropna()
    cal = idx.index
    stocks = [c for c in raw["Close"].columns if not c.startswith("^") and raw["Close"][c].notna().sum() > 260]
    O, H, L, C, V = (raw[k][stocks].reindex(cal) for k in ("Open", "High", "Low", "Close", "Volume"))
    pc = C.shift(1)
    tr = np.maximum(H - L, np.maximum((H - pc).abs(), (L - pc).abs()))
    atr = tr.rolling(14).mean()
    sma = lambda n: C.rolling(n).mean()
    sma200, sma50, sma5 = sma(200), sma(50), sma(5)
    ema20 = C.ewm(span=20, adjust=False, min_periods=20).mean()
    regime = (idx > idx.rolling(200).mean()).reindex(cal).fillna(False)

    member = pd.DataFrame(False, index=cal, columns=stocks)
    hist = load_history()
    for k, (start, names) in enumerate(hist):
        stop = pd.Timestamp(hist[k + 1][0]) if k + 1 < len(hist) else cal[-1] + pd.Timedelta(days=1)
        rows = (cal >= pd.Timestamp(start)) & (cal < stop)
        member.loc[rows, [n + ".NS" for n in names if n + ".NS" in member.columns]] = True
    sig, rank, stop_lvl = {}, {}, {}
    near = (L <= ema20 * 1.01).astype(float).rolling(3).max() > 0
    sig["A"] = (C > sma50) & (sma50 > sma200) & near & (C > H.shift(1)) & (C > ema20)
    rank["A"] = C / C.shift(126) - 1
    stop_lvl["A"] = L.rolling(5).min() - 0.5 * atr
    volr = V / V.rolling(20).mean().shift(1)
    sig["B"] = (C > sma200) & (C > H.rolling(55).max().shift(1)) & (volr >= 1.5)
    rank["B"] = volr
    r2 = rsi(C, 2)
    sig["C"] = (C > sma200) & (r2 < 10)
    sig = {k: v & member for k, v in sig.items()}
    rank["C"] = -r2
    return dict(cal=cal, stocks=stocks, O=O, H=H, L=L, C=C, atr=atr, sma5=sma5, sma200=sma200, member=member,
                mom=C / C.shift(126) - 1,
                low10=L.rolling(10).min().shift(1), regime=regime, idx=idx,
                bench2=raw["Close"][UNIVERSES[UNI][2]].reindex(cal).ffill() if UNIVERSES[UNI][2] else None,
                sig=sig, rank=rank, stop_lvl=stop_lvl)


RULES = {  # atr_stop multiple, target in R, max holding sessions
    "A": dict(atr_stop=None, target_r=2.0, max_hold=15),
    "B": dict(atr_stop=2.0, target_r=None, max_hold=40),
    "C": dict(atr_stop=2.5, target_r=None, max_hold=7),
}


def simulate(d, strat, cfg, start, end):
    rule, slip = RULES[strat], cfg["slippage_pct_per_side"] / 100
    cal = d["cal"]
    days = np.where((cal >= start) & (cal < end))[0]
    a = {k: d[k].values for k in ("O", "H", "L", "C", "atr", "sma5", "low10")}
    sig, rnk, slv = d["sig"][strat].values, d["rank"][strat].values, d["stop_lvl"].get(strat, d["C"]).values
    regime = d["regime"].values
    cash, pos, trades, curve, invested = float(cfg["starting_capital"]), {}, [], [], 0

    def close(j, price, t, reason):
        nonlocal cash
        p = pos.pop(j)
        px = price * (1 - slip)
        fee = charges(0, p["qty"] * px, cfg)
        cash += p["qty"] * px - fee
        pnl = p["qty"] * (px - p["entry"]) - fee - p["buy_fee"]
        trades.append(dict(symbol=d["stocks"][j], entry_date=str(cal[p["t"]].date()),
                           exit_date=str(cal[t].date()), entry=round(p["entry"], 2), exit=round(px, 2),
                           qty=p["qty"], pnl=round(pnl, 2), r=round(pnl / p["risk"], 2),
                           fees=round(fee + p["buy_fee"], 2), reason=reason))

    for t in days:
        # 1. exits at the open: flagged yesterday, or gap through the stop
        for j in list(pos):
            p, o = pos[j], a["O"][t, j]
            if np.isnan(o):
                continue
            if p["flag"]:
                close(j, o, t, p["flag"])
            elif o <= p["stop"]:
                close(j, o, t, "stop_gap")
        # 2. entries at the open from yesterday's signals
        y = t - 1
        if regime[y] and len(pos) < cfg["max_positions"]:
            equity = cash + sum(p["qty"] * a["C"][y, j] for j, p in pos.items())
            cands = [j for j in np.where(sig[y])[0] if j not in pos and not np.isnan(rnk[y, j])]
            for j in sorted(cands, key=lambda j: -rnk[y, j]):
                if len(pos) >= cfg["max_positions"]:
                    break
                o = a["O"][t, j]
                if np.isnan(o) or o > a["C"][y, j] * 1.02:
                    continue
                entry = o * (1 + slip)
                stop = entry - rule["atr_stop"] * a["atr"][y, j] if rule["atr_stop"] else slv[y, j]
                if np.isnan(stop) or stop >= entry:
                    continue
                target = entry + rule["target_r"] * (entry - stop) if rule["target_r"] else None
                s = size_trade(equity, entry, stop, target, cfg)
                if not s["ok"]:
                    continue
                qty = min(s["qty"], int((cash - 25) // entry))
                if qty < 1:
                    continue
                fee = charges(qty * entry, 0, cfg)
                cash -= qty * entry + fee
                pos[j] = dict(qty=qty, entry=entry, stop=stop, target=target, t=t, flag=None,
                              buy_fee=fee, risk=qty * (entry - stop))
        # 3. intraday stop / target (stop checked first), then close-based exit flags
        for j in list(pos):
            p = pos[j]
            lo, hi, c = a["L"][t, j], a["H"][t, j], a["C"][t, j]
            if np.isnan(c):
                continue
            if lo <= p["stop"]:
                close(j, p["stop"], t, "stop")
            elif p["target"] and hi >= p["target"]:
                close(j, p["target"], t, "target")
            elif strat == "B" and c < a["low10"][t, j]:
                p["flag"] = "trail"
            elif strat == "C" and c > a["sma5"][t, j]:
                p["flag"] = "bounce"
            elif t - p["t"] + 1 >= rule["max_hold"]:
                p["flag"] = "time"
        invested += bool(pos)
        mtm = sum(p["qty"] * (a["C"][t, j] if not np.isnan(a["C"][t, j]) else p["entry"]) for j, p in pos.items())
        curve.append(cash + mtm)
    eq = pd.Series(curve, index=cal[days])
    return eq, trades, invested / max(len(days), 1)


def simulate_rotation(d, cfg, start, end, exit_on_bear=False):
    """Strategy D: monthly momentum rotation (see references/strategies.md)."""
    n, slip, cal = cfg["max_positions"], cfg["slippage_pct_per_side"] / 100, d["cal"]
    days = np.where((cal >= start) & (cal < end))[0]
    O, C, mom, s200, regime, member = (d[k].values for k in ("O", "C", "mom", "sma200", "regime", "member"))
    cash, pos, trades, curve, invested = float(cfg["starting_capital"]), {}, [], [], 0
    for t in days:
        y = t - 1
        if cal[t].month != cal[y].month:  # first session of a month: act on month-end ranking
            ok = (C[y] > s200[y]) & ~np.isnan(mom[y]) & member[y]
            order = [j for j in np.argsort(-np.where(ok, mom[y], -np.inf)) if ok[j]]
            keep = set(order[:2 * n]) if (regime[y] or not exit_on_bear) else set()
            for j in [j for j in pos if j not in keep and not np.isnan(O[t, j])]:
                p = pos.pop(j)
                px = O[t, j] * (1 - slip)
                fee = charges(0, p["qty"] * px, cfg)
                cash += p["qty"] * px - fee
                pnl = p["qty"] * (px - p["entry"]) - fee - p["buy_fee"]
                trades.append(dict(symbol=d["stocks"][j], entry_date=str(cal[p["t"]].date()),
                                   exit_date=str(cal[t].date()), entry=round(p["entry"], 2),
                                   exit=round(px, 2), qty=p["qty"], pnl=round(pnl, 2),
                                   r=round(pnl / (p["qty"] * p["entry"]), 3),
                                   fees=round(fee + p["buy_fee"], 2), reason="rotation"))
            if regime[y]:
                for j in order:
                    free = n - len(pos)
                    if free <= 0:
                        break
                    if j in pos or np.isnan(O[t, j]):
                        continue
                    entry = O[t, j] * (1 + slip)
                    qty = int((cash / free - 20) // entry)
                    if qty < 1:
                        continue
                    fee = charges(qty * entry, 0, cfg)
                    cash -= qty * entry + fee
                    pos[j] = dict(qty=qty, entry=entry, t=t, buy_fee=fee)
        invested += bool(pos)
        curve.append(cash + sum(p["qty"] * (C[t, j] if not np.isnan(C[t, j]) else p["entry"])
                                for j, p in pos.items()))
    return pd.Series(curve, index=cal[days]), trades, invested / max(len(days), 1)


def stats(eq, trades, tim, idx, cfg, bench2=None):
    yrs = (eq.index[-1] - eq.index[0]).days / 365.25
    cagr = lambda s: (s.iloc[-1] / s.iloc[0]) ** (1 / yrs) - 1
    dd = lambda s: (s / s.cummax() - 1).min()
    m = pd.concat([pd.Series([cfg["starting_capital"]], index=[eq.index[0] - pd.Timedelta(days=1)]), eq])
    m = m.resample("ME").last().pct_change().dropna()
    pnl = np.array([x["pnl"] for x in trades]); r = np.array([x["r"] for x in trades])
    w, l = pnl[pnl > 0], pnl[pnl <= 0]
    fees = sum(x["fees"] for x in trades)
    bh = idx.reindex(eq.index).ffill()
    extra = {}
    if bench2 is not None:
        b2 = bench2.reindex(eq.index).ffill().dropna()
        extra = dict(midcap50_cagr_pct=round(100 * cagr(b2), 1), midcap50_max_dd_pct=round(100 * dd(b2), 1))
    return dict(
        trades=len(trades), win_rate=round(100 * len(w) / max(len(pnl), 1), 1),
        avg_win_r=round(float(r[pnl > 0].mean()), 2) if len(w) else 0,
        avg_loss_r=round(float(r[pnl <= 0].mean()), 2) if len(l) else 0,
        profit_factor=round(float(w.sum() / -l.sum()), 2) if len(l) and l.sum() < 0 else None,
        final_equity=round(float(eq.iloc[-1])), cagr_pct=round(100 * cagr(eq), 1),
        max_dd_pct=round(100 * dd(eq), 1), avg_month_pct=round(100 * m.mean(), 2),
        worst_month_pct=round(100 * m.min(), 1), months_positive_pct=round(100 * (m > 0).mean()),
        time_in_market_pct=round(100 * tim), fees_rs=round(fees),
        fees_pct_of_gross=round(100 * fees / (pnl.sum() + fees), 0) if pnl.sum() + fees > 0 else None,
        nifty_cagr_pct=round(100 * cagr(bh), 1), nifty_max_dd_pct=round(100 * dd(bh), 1), **extra)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--refresh", action="store_true")
    ap.add_argument("--positions", default="3,5", help="comma-separated max_positions values to test")
    ap.add_argument("--strategies", default="ABCDE")
    ap.add_argument("--capital", type=float, help="override starting_capital from config.json")
    ap.add_argument("--universe", default="nifty100", choices=list(UNIVERSES))
    ap.add_argument("--out")
    args = ap.parse_args()
    global UNI
    UNI = args.universe
    args.out = args.out or os.path.join(ROOT, "trading", f"backtest_results_{UNI}.json")
    IS_START = UNIVERSES[UNI][1]
    d = build(load_prices(args.refresh))
    end = str((d["cal"][-1] + pd.Timedelta(days=1)).date())
    base, out, rows = load_config(), {}, []
    if args.capital:
        base["starting_capital"] = args.capital
    wanted = {x + ".NS" for _, m in load_history() for x in m}
    out["meta"] = dict(universe=UNI, capital=base["starting_capital"], symbols=len(d["stocks"]), no_price_data=sorted(wanted - set(d["stocks"])), last_candle=str(d["cal"][-1].date()),
                       periods={"in_sample": [IS_START, OOS_START], "out_of_sample": [OOS_START, end]})
    for strat in args.strategies:
        for n in [int(x) for x in args.positions.split(",")]:
            cfg = copy.deepcopy(base); cfg["max_positions"] = n
            for name, (s, e) in out["meta"]["periods"].items():
                eq, tr, tim = simulate_rotation(d, cfg, s, e, exit_on_bear=(strat == "E")) if strat in "DE" else simulate(d, strat, cfg, s, e)
                st = stats(eq, tr, tim, d["idx"], cfg, d["bench2"])
                out[f"{strat}_{n}pos_{name}"] = dict(stats=st, trades=tr)
                rows.append(dict(strategy=strat, positions=n, period=name, **st))
    json.dump(out, open(args.out, "w"), indent=1)
    pd.set_option("display.width", 250); pd.set_option("display.max_columns", 30)
    print(out["meta"]); print(pd.DataFrame(rows).to_string(index=False))


if __name__ == "__main__":
    main()
