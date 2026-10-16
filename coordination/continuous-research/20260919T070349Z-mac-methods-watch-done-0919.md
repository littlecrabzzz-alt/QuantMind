# Daily methods watch done — 2026-09-19

- Run: `data/research_watch/20260919T070055.024571Z`
- Command: `python3 scripts/research_watch.py`
- Result: exit 2; all sources succeeded except the known unchanged JoinQuant dynamic-page parse limitation.
- Primary review: one new QuantConnect technical lead plus its linked QuantConnect chronology, Alpaca official order lifecycle/WebSocket/Paper documentation, and an Alpaca staff forum response.
- Actionable mapping: offline cancel/fill race regression against current QuantMind order-state semantics; no business-code change made.
- Source recovery: Qlib, RD-Agent and QuantsPlaybook returned to `ok`; no credentials required.
- Boundaries: no third-party code execution, no install, no strategy run, no trading.
