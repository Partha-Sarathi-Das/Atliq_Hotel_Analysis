#!/usr/bin/env python3
"""Monthly rotation signal (strategies D and E) for paper or live use.

Ranks the universe on the last completed month-end and prints what to sell and buy at the first
session of the following month. Fill prices are unadjusted opens when that session has happened.

Usage: python3 rotation_signal.py --capital 12500 [--held SYM1,SYM2] [--cash 1234] [--refresh]
"""
import argparse
import json
import sys
import os

import numpy as np
import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import backtest as bt  # noqa: E402
from position_size import charges, load_config  # noqa: E402


def raw_bar(ticker, day):
    """Unadjusted OHLC for one session, or None."""
    import requests
    from urllib.parse import quote
    p1 = int(pd.Timestamp(day).timestamp())
    r = requests.get("https://query1.finance.yahoo.com/v8/finance/chart/" + quote(ticker),
                     params=dict(period1=p1 - 86400, period2=p1 + 2 * 86400, interval="1d"),
                     headers={"User-Agent": "Mozilla/5.0"}, timeout=30)
    if r.status_code != 200:
        return None
    res = r.json()["chart"]["result"][0]
    q = res["indicators"]["quote"][0]
    for i, ts in enumerate(res.get("timestamp", [])):
        if pd.Timestamp(ts, unit="s").normalize() == pd.Timestamp(day):
            return {k: q[k][i] for k in ("open", "high", "low", "close")}
    return None


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--universe", default="midcap150", choices=list(bt.UNIVERSES))
    ap.add_argument("--positions", type=int, default=5)
    ap.add_argument("--capital", type=float, required=True, help="equity allotted to the strategy")
    ap.add_argument("--cash", type=float, help="cash available now (default: capital, i.e. no holdings)")
    ap.add_argument("--held", default="", help="comma-separated symbols currently held")
    ap.add_argument("--bear-exit", action="store_true", default=True, help="strategy E (default)")
    ap.add_argument("--refresh", action="store_true")
    a = ap.parse_args()
    bt.UNI = a.universe
    cfg, d = load_config(), bt.build(bt.load_prices(a.refresh))
    cal, n, slip = d["cal"], a.positions, load_config()["slippage_pct_per_side"] / 100
    ends = [i for i in range(len(cal) - 1) if cal[i].month != cal[i + 1].month]
    y = ends[-1]                      # last completed month-end with a following session
    t = y + 1
    C, mom, s200 = d["C"].values, d["mom"].values, d["sma200"].values
    ok = (C[y] > s200[y]) & ~np.isnan(mom[y]) & d["member"].values[y]
    order = [j for j in np.argsort(-np.where(ok, mom[y], -np.inf)) if ok[j]]
    name = lambda j: d["stocks"][j][:-3]
    regime = bool(d["regime"].values[y])
    held = [h for h in a.held.split(",") if h]
    keep = {name(j) for j in order[:2 * n]} if regime else set()
    sells = [h for h in held if h not in keep]
    out = dict(universe=a.universe, signal_date=str(cal[y].date()), action_date=str(cal[t].date()),
               last_candle=str(cal[-1].date()), market_filter_on=regime,
               nifty_close=round(float(d["idx"].iloc[y]), 1),
               nifty_sma200=round(float(d["idx"].rolling(200).mean().iloc[y]), 1),
               eligible=len(order), sell=sells, keep=[h for h in held if h in keep],
               top_ranked=[dict(symbol=name(j), six_month_return_pct=round(100 * mom[y, j], 1),
                                close=round(float(C[y, j]), 2)) for j in order[:2 * n]], buy=[])
    cash = a.cash if a.cash is not None else a.capital
    free = n - len(out["keep"])
    if regime:
        for j in order:
            if free <= 0:
                break
            if name(j) in held:
                continue
            bar = raw_bar(d["stocks"][j], cal[t])
            ref = bar["open"] if bar else float(C[y, j])
            entry = ref * (1 + slip)
            qty = int((cash / free - 20) // entry)
            if qty < 1:
                out.setdefault("skipped_too_expensive", []).append(name(j))
                continue
            fee = charges(qty * entry, 0, cfg)
            out["buy"].append(dict(symbol=name(j), qty=qty, price_basis="action-day open" if bar else "signal close",
                                   entry_price=round(entry, 2), value=round(qty * entry, 2), buy_charges=fee))
            cash -= qty * entry + fee
            free -= 1
    out["cash_after"] = round(cash, 2)
    print(json.dumps(out, indent=2))


if __name__ == "__main__":
    main()
