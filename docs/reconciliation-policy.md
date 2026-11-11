# Reconciliation policy

FolioScreen never invents financial transactions. This page defines exactly what it does instead.

## Source of truth

1. **Today's holdings and cash are what the brokerage reports** (SnapTrade positions and balances).
   They are stored and shown unchanged.
2. **History is reconstructed backwards** from those values using only the reported transactions:
   `units(d) = reported units today − Σ units of transactions dated after d`, and the same for cash.
   Values are end-of-day.
3. Transactions are kept exactly as reported (type, units, amount, fee, price, date). Signs are
   checked against SnapTrade's convention but never changed.

## Conventions verified on the SnapTrade Sandbox

- `units` is always the signed change in holdings: transfers out and reverse splits are negative; splits,
  stock dividends, spinoffs, mergers and reinvestments are positive *changes*, not new totals.
- BUY `amount` = −units × price (fees reported separately); SELL `amount` is positive.
- On asset transfers, `amount` is the market value of the shares moved (its sign follows the units). It is
  **not** cash: it is kept for display and excluded from cash reconstruction. The external flow is valued at
  that day's close.

## What is never done

No deposit, withdrawal, opening balance, adjustment or "plug" transaction is generated, ever.
No source value is altered, netted or dropped. Duplicate transaction IDs are counted once and flagged.

## When transactions cannot explain the reported values

| Situation | Issue code | Severity | Effect |
|---|---|---|---|
| Units held before the earliest available transaction | `HELD_BEFORE_HISTORY_START` | Warning | Values from the history start are valid. Cost basis uses the broker's reported figure; realized gains on those units are unavailable. |
| Transactions imply negative units at some point (missing sale or transfer-out) | `NEGATIVE_UNITS_IN_HISTORY` | Error | Performance unavailable up to the last affected date (**Partial**). |
| Transaction type not recognised, with units or cash | `UNCLASSIFIED_ACTIVITY` | Error | Unknown whether it is an external flow: performance unavailable up to that date (**Partial**) until the type is mapped in `config.json` → `type_map`. |
| Units or amount sign contradicts SnapTrade's convention | `UNEXPECTED_SIGN` | Error | Kept as reported; performance unavailable up to that date. |
| Transactions imply negative cash (margin, or missing deposits/fees) | `CASH_HISTORY_NEGATIVE` | Warning | Performance shown but marked **Incomplete**. |
| Holding or cash not in USD, option, crypto, bond, or a security Tiingo cannot price | `UNPRICED_HOLDING`, `NON_USD_*`, `OPTION_ACTIVITY` | Error | Excluded from totals and listed; performance **Unavailable** for that account. |
| Position flagged by SnapTrade as a cash equivalent | `CASH_EQUIVALENT_POSITION` | Info | Not valued as a security (it is already inside cash, so counting it would double count). Its buys and sells move neither units nor cash; its dividends count as income. |
| Brokerage cash adjustment (`ADJUSTMENT` without units) | `BROKER_ADJUSTMENT` | Info | Counted as investment return, not as a deposit or withdrawal. |
| No transactions at all | — | — | Holdings and value today only; performance **Unavailable**. |
| Connection disabled at SnapTrade | `CONNECTION_DISABLED` | Error | Data is SnapTrade's last cached state; the report says so. |
| Connection has trading access | `CONNECTION_NOT_READ_ONLY` | Error | Sync is blocked unless `allow_trade_connections` is set. |

## Performance status

Each account, and the portfolio, carries one status and a start date:

- **Complete**: every reported value is explained from the start date.
- **Partial**: complete, but only from a later start date than the available history.
- **Incomplete**: shown, with a warning that some inputs could not be verified.
- **Unavailable**: not calculated.

The portfolio start is the latest start among accounts that limit it. An account whose reconstructed
opening state is empty (no units, no cash) was worth zero before its first transaction, so it does
not limit the portfolio.
