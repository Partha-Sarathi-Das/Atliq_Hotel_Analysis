#!/usr/bin/env python3
"""Position sizing and charge estimate for NSE delivery (CNC) swing trades."""
import argparse
import json
import math
import os

CONFIG = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "config.json")


def load_config(path=CONFIG):
    with open(path) as f:
        return json.load(f)


def _brokerage(turnover, b):
    fee = min(turnover * b["brokerage_pct"] / 100, b["brokerage_cap_rs"])
    return max(fee, b.get("brokerage_min_rs", 0)) if turnover > 0 else 0.0


def charges(buy_value, sell_value, cfg):
    """Estimated total charges in rupees for one buy and one sell."""
    b, s = cfg["broker"], cfg["statutory"]
    turnover = buy_value + sell_value
    brokerage = _brokerage(buy_value, b) + _brokerage(sell_value, b)
    stt = turnover * s["stt_pct_each_side"] / 100
    txn = turnover * s["exchange_txn_pct"] / 100
    sebi = turnover * s["sebi_pct"] / 100
    stamp = buy_value * s["stamp_duty_buy_pct"] / 100
    gst = (brokerage + txn + sebi) * s["gst_pct"] / 100
    dp = b["dp_charge_per_sell_rs"] if sell_value > 0 else 0.0
    return round(brokerage + stt + txn + sebi + stamp + gst + dp, 2)


def size_trade(equity, entry, stop, target=None, cfg=None, risk_scale=1.0):
    """Return a dict describing the trade, with ok=False and a reason if rejected."""
    cfg = cfg or load_config()
    if stop >= entry:
        return {"ok": False, "reason": "stop must be below entry (long only)"}
    risk_rs = equity * cfg["risk_per_trade_pct"] / 100 * risk_scale
    cap_rs = equity / cfg["max_positions"]
    per_share_risk = entry - stop
    qty = int(math.floor(min(risk_rs / per_share_risk, cap_rs / entry)))
    out = {"ok": True, "qty": qty, "risk_budget_rs": round(risk_rs, 2),
           "position_cap_rs": round(cap_rs, 2)}
    if qty < 1:
        out.update(ok=False, reason="quantity below 1: price too high for the cap or stop too wide")
        return out
    value = qty * entry
    cost_at_stop = charges(value, qty * stop, cfg)
    out.update(
        capital_used_rs=round(value, 2),
        risk_rs=round(qty * per_share_risk, 2),
        loss_at_stop_incl_charges_rs=round(qty * per_share_risk + cost_at_stop, 2),
        round_trip_charges_rs=charges(value, value, cfg),
    )
    out["charges_pct_of_position"] = round(out["round_trip_charges_rs"] / value * 100, 2)
    if out["charges_pct_of_position"] > cfg["max_round_trip_cost_pct"]:
        out.update(ok=False, reason="charges exceed %.1f%% of position" % cfg["max_round_trip_cost_pct"])
    if target is not None:
        net_gain = qty * (target - entry) - charges(value, qty * target, cfg)
        out["net_gain_at_target_rs"] = round(net_gain, 2)
        out["reward_to_risk_after_costs"] = round(net_gain / out["loss_at_stop_incl_charges_rs"], 2)
        if out["ok"] and out["reward_to_risk_after_costs"] < cfg["min_reward_to_risk_after_costs"]:
            out.update(ok=False, reason="reward to risk after costs below %.1f"
                       % cfg["min_reward_to_risk_after_costs"])
    return out


if __name__ == "__main__":
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--equity", type=float, required=True)
    p.add_argument("--entry", type=float, required=True)
    p.add_argument("--stop", type=float, required=True)
    p.add_argument("--target", type=float)
    p.add_argument("--risk-scale", type=float, default=1.0, help="0.5 after a losing streak")
    a = p.parse_args()
    print(json.dumps(size_trade(a.equity, a.entry, a.stop, a.target, risk_scale=a.risk_scale), indent=2))
