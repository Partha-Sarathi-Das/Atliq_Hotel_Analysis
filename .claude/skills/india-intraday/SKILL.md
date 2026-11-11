---
name: india-intraday
description: NSE intraday (day-trading) research tools for Indian stocks, adapted from the US day-trader-skill pack - opening-range breakout scan on NSE 5-minute bars in IST, a pre-trade check that sizes the position and applies Dhan intraday charges and the risk limits, a 10,000-path replay of a planned trade, and a backtest of the opening-range rules on Nifty 100 or Midcap 150. Use for any intraday or day-trading question about NSE stocks, such as "scan NSE for opening range breakouts", "check this intraday trade", "replay this trade", "backtest ORB on Indian stocks", or "is this day trade worth taking". For swing or monthly trading use india-swing-trader.
---

# India Intraday

Opening-range breakout (ORB) tools for NSE, adapted from the US day-trader-skill pack (github.com/jakeschincariol/day-trader-skill,
MIT, commit 3d0f4ef; no longer installed here): its scanner,
entry timer, exit planner, time machine, budget manager and risk manager, rebuilt for NSE hours
(09:15–15:30 IST), `.NS` symbols, point-in-time Nifty index membership and Dhan's intraday
(MIS) charges. Long only, no margin, nothing held overnight. **Nothing here places orders.**

The pack's news monitor, earnings analyst, Pelosi tracker, price alerts and Alpaca/IBKR order
executor were not adapted: they depend on US-only sources (SEC EDGAR, the US House Clerk) or
US brokers, and NSE's own announcement feed refuses automated requests from this environment.

## Current standing (read this first)

Both pre-registered setups **failed** their backtests on 10–11 Nov 2026 (see the table in
`trading/state.json` and the files in `trading/intraday/`). Until a setup passes:

- Do not give intraday buy or sell calls for real money. The tools are for research and for
  showing the user, with their own numbers, why a trade is or is not worth taking.
- The user's plan is unchanged: half the capital in a Nifty 50 index fund, half paper trading
  the monthly rotation (strategy E) in `india-swing-trader`.
- Any new intraday idea is written into `references/rules.md` before it is tested, logged in
  `trading/state.json`, and counted. Eight rule sets have been tested in this project so far.

## Tools

All commands run from the repository root:

```
python3 .claude/skills/india-intraday/scripts/intraday.py <command> ...
```

| Command | Adapted from | What it does |
|---|---|---|
| `scan [--universe nifty100\|midcap150] [--at HH:MM]` | trader-scanner, trader-entry | 15-minute opening range on 5-minute bars for every current index member: triggered (first close above the range high, by 11:00), waiting (distance to trigger), or expired. Writes `trading/intraday/watchlist.json` |
| `check --entry X --stop Y [--target Z] [--time HH:MM] [--trades-today N] [--loss-today RS]` | trader-exit, trader-budget, trader-risk | Sizes the trade, prices Dhan charges, and returns PASS or BLOCK with reasons |
| `replay SYMBOL --entry X --stop Y [--target Z] [--at HH:MM]` | trader-timemachine | Rebuilds the rest of the session 10,000 times from the stock's last 60 sessions of 5-minute bars, and reruns the ORB15 rule on each of those sessions |
| `backtest --setup orb15\|orb60 --universe nifty100\|midcap150 [--refresh]` | new | Portfolio backtest of the pre-registered rules in `references/rules.md` |

### Check rules (from `config.json`)

- Stop below entry and at least 0.4% away; target defaults to 2R.
- Entries only between 09:30 and 11:05 IST; everything is closed by 15:15, before Dhan's
  auto square-off.
- Risk 1% of equity per trade, position value at most equity ÷ 3, whole shares, no margin.
- At most 3 trades a day; no new trades once the day's loss reaches 3% of equity.
- Reward to risk after charges at least 1.5.

## How to answer

- For a scan, list triggered stocks first with range high, stop (range midpoint) and trigger
  time, then the nearest waiting ones. Say which session the data is from; if the market is
  closed, say it is the last session.
- The replay draws each 5-minute bar independently from past sessions, which understates trending
  days. Read its odds next to the `history` block (the rule rerun on the stock's real sessions),
  and trust the history more when they disagree.
- For a check or replay, lead with the verdict, then quantity, rupee risk, charges, and the
  replay odds. Always remind the user that the setup failed its backtest.
- State that data is free, delayed Yahoo Finance bars, not ticks, and must be checked against
  the broker before acting.
- Never estimate a price, a level or an outcome without running the tool on fresh data.

## Things to tell the user when relevant

- Intraday profits are speculative business income for Indian tax purposes, taxed at slab rates,
  not as capital gains. Suggest they keep contract notes and ask a tax adviser.
- SEBI's studies of individual traders have found that most lose money in intraday trading.
- MIS margin multiplies losses as much as gains; the config keeps leverage at 1 for that reason.
