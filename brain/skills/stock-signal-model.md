---
title: Build a stock buy/sell signal model
tags: stocks, quant, backtest, signals, market
agents: quant
learned_from:
related: betting-model-learning
---
## When to use
"When should I buy X", screeners, watchlist reports, backtests.

## How
1. Never guess prices: `python3 scripts/market_data.py TICKER --years 5 --csv outputs/job-N/ticker.csv` (Yahoo, Stooq fallback, no key needed).
2. Get current news with WebSearch and state the date of the data.
3. Start from the indicators in `scripts/signals.py` (trend, RSI, distance from the 52-week high) and backtest them: what happened 20 days after past signal days, compared with any day.
4. Report the signal, the reasons in plain words, a stop idea and the backtest numbers.
5. To track a ticker every day, add it to `watchlist.json`.

## Gotchas
- Always include the data date and a "not financial advice" note.
