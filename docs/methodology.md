# Calculation methodology (proof of concept)

These rules are implemented twice, independently: in DAX (the semantic model) and in Python
(`folio/engine.py`). `folio verify` compares the two row by row.

- **Trading calendar**: the benchmark's price dates (SPY live; `MKT-X` in the demo).
- **Holdings and cash** on date *d*: the reconstructed end-of-day step tables (see reconciliation-policy.md).
- **Prices**: each holding is valued at its last available **raw** close on or before *d*
  (not dividend-adjusted: dividends arrive as cash, so adjusted prices would count them twice).
  Days where a price was carried forward are counted (`Filled Price Days`); positions with no price at all
  are counted (`Missing Price Days`) and never valued as zero silently.
- **Splits**: the brokerage's split transaction changes the units; raw prices change on the same day.
  `Unconfirmed Splits` counts Tiingo split events on held securities with no matching split transaction.
- **External flows**: deposits, withdrawals and transfers in/out (assets valued at that day's close).
  A flow dated after the previous trading date and up to *d* belongs to *d* (weekend deposits land on Monday).
- **Portfolio value** `V_d` = securities + cash.
- **Daily return** `r_d = (V_d − F_d) / V_{d−1} − 1` (flows end-of-day); `r_d = 0` when `V_{d−1}` is zero.
- **Time-weighted return index** starts at 1 on the first trading date on or after the performance start
  and chains `(1 + r_d)`. `TWR Since Start` = latest index − 1.

Money-weighted return, realized/unrealized P&L, dividends, benchmark comparison and period windows are
Phase 4 scope; the proof of concept proves the data path and the daily value/TWR mechanics they build on.
