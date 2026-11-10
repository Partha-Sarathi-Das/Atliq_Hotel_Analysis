# Candidate strategies

All three are long only, use daily candles, generate signals on the close and enter at the next
session's open. Shared rules:

- Universe: Nifty 100. Skip a stock whose price is above one third of equity (cannot buy 1 share).
- Market filter: Nifty 50 close above its 200-day simple moving average (SMA).
- Never enter a stock already held. Maximum 3 open positions.
- If the next open gaps above the signal close by more than 2%, skip the trade.
- If more signals than free slots, rank as stated per strategy.
- Stop-loss is a hard price level, checked against the day's low. If the open gaps below the
  stop, exit at the open.
- ATR = 14-day average true range. R = entry price minus stop price.

## A. Trend pullback

- Trend: close > 50-day SMA > 200-day SMA.
- Pullback: within the last 3 sessions the low came within 1% of the 20-day EMA (or below it).
- Trigger: today's close is above yesterday's high and above the 20-day EMA.
- Stop: lowest low of the last 5 sessions minus 0.5 × ATR.
- Target: entry + 2R.
- Time exit: close the trade at the open after 15 sessions if neither level was hit.
- Rank: highest 6-month price return first.

## B. Breakout momentum

- Trend: close > 200-day SMA.
- Trigger: close above the highest high of the previous 55 sessions, with volume at least
  1.5 × the 20-day average volume.
- Stop: entry − 2 × ATR.
- Exit: close below the lowest low of the previous 10 sessions (trailing), or after 40 sessions.
  No fixed target.
- Rank: highest volume ratio first.

## C. Oversold bounce (mean reversion)

- Trend: close > 200-day SMA.
- Trigger: 2-day RSI below 10.
- Stop: entry − 2.5 × ATR.
- Exit: first close above the 5-day SMA, or after 7 sessions.
- Rank: lowest 2-day RSI first.

Parameters above are the starting values. Any change must be made before looking at
out-of-sample results, and recorded in `trading/state.json` under `rule_changes`.

## D. Monthly momentum rotation (low turnover)

Added after A, B and C failed the backtest on costs. Different in kind: it is always close to
fully invested, trades once a month, and has no per-trade stop, so the 1.5% risk-per-trade rule
does not apply. Risk is controlled by the rotation rules and the account kill switches.

- Signal day: last session of each month. Eligible: close above the stock's 200-day SMA.
- Rank eligible stocks by 6-month (126-session) return, highest first.
- First session of the next month, at the open: sell any holding no longer in the top 2N
  (N = maximum positions). Then, only if the Nifty 50 market filter is on, fill empty slots
  with the highest-ranked stocks not already held, splitting available cash equally.
- Skip a stock if one share costs more than the slot's cash. Kept holdings are not resized.
- In the trade log the `r` column for D is the trade's return as a fraction of position value.

## E. Monthly rotation with bear-market exit

Identical to D, except that when the Nifty 50 market filter is off on the signal day, every
holding is sold at the next open and the account stays in cash until the filter turns on again.
Added to cut D's drawdowns; expect lower returns and more trades than D.

## Universes

Each candidate can be run on `nifty100` or `midcap150` (`--universe`). Midcap 150 membership
history is approximate and reliable from September 2016, so midcap tests start in 2017.
