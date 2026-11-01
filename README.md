# MNQ TradingView Bot

Automated trading of **Micro E-mini Nasdaq-100 futures (MNQ)** driven by a TradingView strategy.

```
TradingView (Pine strategy)  ──webhook JSON──▶  this server  ──REST──▶  Tradovate (demo/live)
   signals + alerts                               auth, risk checks,        MNQ orders with
                                                  position reconcile        OCO stop/target bracket
```

TradingView can't place futures orders on its own from a strategy. The usual approach: a strategy fires **webhook alerts** and a small server you control turns them into broker orders. That's what this repo does.

> ⚠️ **Risk warning.** Futures are leveraged: MNQ is **$2 per index point** (~$0.50 per 0.25 tick), and on a fast day the index can move hundreds of points. This code is a starting point, not a proven, profitable system. Backtest it, paper trade it, run it on a Tradovate **demo** account for weeks, and only then think about small live size. You are responsible for every order it places.

## What's included

| Path | Purpose |
|---|---|
| `pine/mnq_strategy.pine` | Pine v6 strategy: 9/21 EMA cross with a VWAP filter, ATR stop, 2R target, entries only during RTH (09:35–15:45 NY), forced flat at 15:50, max entries per day. Sends a JSON alert on every order fill. |
| `bot/app.py` | FastAPI webhook server (`/webhook`, `/health`, `/status`, `/kill`, `/resume`). |
| `bot/executor.py` | Reconciles the broker position to the signal's desired position (`long`/`short`/`flat`), so repeated or out-of-order alerts don't stack positions. |
| `bot/risk.py` | Risk gate: kill switch, max contracts, entry time window, no weekends, max trades/day, daily loss limit (trips the kill switch), stale-signal rejection, stop-side sanity check, duplicate signal IDs. **Exits are never blocked.** |
| `bot/brokers/paper.py` | In-memory paper broker (the default). |
| `bot/brokers/tradovate.py` | Tradovate REST broker: market entry plus broker-side OCO stop/target bracket (`placeOSO`), liquidate, and cancelling leftover bracket orders. |
| `mcp_server/server.py` | MCP server so Claude can check status and place orders through the bot (see §6). |
| `bot/contracts.py` | Picks the front-month contract automatically (e.g. `MNQZ6`) and rolls 8 days before expiry. |

## 1. Backtest in TradingView

1. Open an `MNQ1!` chart (1–5 min works well for this logic).
2. Pine Editor → paste `pine/mnq_strategy.pine` → **Add to chart**.
3. Look over the **Strategy Tester** results. Commission ($0.62/side) and 1 tick of slippage are already set. Tune the inputs, and be careful not to overfit.

## 2. Run the server (paper mode)

```bash
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env        # set WEBHOOK_SECRET and ADMIN_TOKEN at minimum
uvicorn bot.app:app --host 0.0.0.0 --port 8000 --env-file .env
pytest -q                   # 22 tests, no network needed
```

Simulate a signal:

```bash
curl -X POST localhost:8000/webhook -H 'content-type: application/json' \
  -d '{"secret":"<WEBHOOK_SECRET>","action":"long","qty":1,"price":21000,"stop":20980,"target":21040}'
curl localhost:8000/status -H 'x-admin-token: <ADMIN_TOKEN>'
```

## 3. Expose it to TradingView

TradingView webhooks need a **public HTTPS URL on port 443 (or 80)**, plus a paid TradingView plan and 2FA turned on.
- **Hosting:** a small VPS (ideally in or near Chicago/US-East, close to CME and Tradovate) running Docker (`docker build -t mnqbot . && docker run --env-file .env -p 8000:8000 mnqbot`) behind Caddy or nginx for TLS.
- **Quick testing:** `cloudflared tunnel --url http://localhost:8000` or ngrok.
- Optionally set `ALLOWED_IPS` to TradingView's webhook IPs (listed in `.env.example`). Behind a reverse proxy, also make sure it forwards the client IP.

## 4. Create the TradingView alert

On the chart that has the strategy: **Alerts → Create**
- **Condition:** `MNQ Trend Bot` → *Order fills only*
- **Message:** exactly `{{strategy.order.alert_message}}`
- **Notifications:** ✅ Webhook URL → `https://your-host/webhook`
- **Expiration:** open-ended
- In the strategy's settings, set **Webhook secret** to the same value as `WEBHOOK_SECRET`.

An alert carries a snapshot of the script's inputs. If you change inputs or code, delete the alert and create it again.

Example payload the strategy sends:
```json
{"secret":"…","action":"long","symbol":"MNQ","qty":1,"price":21003.25,
 "stop":20981.5,"target":21046.75,"signal_id":"1793716200000-long","sent_at":1793716261123}
```

## 5. Connect Tradovate (demo first)

1. Open a Tradovate account (demo accounts are free) and enable **API Access**, a paid add-on on live accounts.
2. In Tradovate → Settings → API Access, generate an API key to get the `cid` and `sec`.
3. Fill in the `TRADOVATE_*` values in `.env`, then set `BROKER=tradovate` and `TRADOVATE_ENV=demo`.
4. Send a test signal and check the order and bracket in the Tradovate demo platform.
5. Run it on demo for a while. Compare its fills against the TradingView Strategy Tester before you switch `TRADOVATE_ENV=live`.

The Tradovate adapter is tested against a mocked API that follows Tradovate's documented endpoints. **Check its behaviour on demo before trusting it.**

## 6. Let Claude trade through MCP (optional)

`mcp_server/` is an MCP server that gives Claude these tools. It only talks to **your bot's API**, never to the broker directly, so every order still passes the same risk rules.

| Tool | Places orders? | What it does |
|---|---|---|
| `get_status` | no | Contract, position, today's P&L, entries today, kill switch, recent activity |
| `preview_order` | no | Dry run: what an order would do and whether a risk rule would block it |
| `place_order` | **yes** | Go `long`/`short` `qty` contracts, or `flat`, with an optional broker-side stop/target |
| `close_position` | **yes** | Flatten and cancel the bracket orders |
| `kill_switch` | **yes** | Block all new entries and flatten |
| `resume_trading` | no | Clear the kill switch |

Its built-in instructions tell Claude to preview first and only place an order after you approve it. The real safeguard is your MCP client's permission prompt: **never "always allow" `place_order`, `close_position` or `kill_switch`.** Auto-allowing the read-only tools is fine.

**Claude Code:**
```bash
claude mcp add mnq-bot -e BOT_URL=https://your-bot -e BOT_ADMIN_TOKEN=<ADMIN_TOKEN> \
  -- python -m mcp_server.server     # run from this repo, with requirements installed
```

**Claude Desktop** (`claude_desktop_config.json`):
```json
{
  "mcpServers": {
    "mnq-bot": {
      "command": "/path/to/TradingBot/.venv/bin/python",
      "args": ["-m", "mcp_server.server"],
      "cwd": "/path/to/TradingBot",
      "env": { "BOT_URL": "https://your-bot", "BOT_ADMIN_TOKEN": "<ADMIN_TOKEN>" }
    }
  }
}
```

Pair it with a read-only TradingView chart MCP server (for example [claude-tradingview-mcp](https://glama.ai/mcp/servers/RVAflo/claude-tradingview-mcp)). Claude can then read your MNQ chart and propose a trade, and you approve it through `place_order`.

Notes: manual orders count toward `MAX_TRADES_PER_DAY` and follow the entry window. In paper mode, pass `price` because the paper broker fills there. Keep `ADMIN_TOKEN` secret: anyone who has it can trade your account.

## Operating it

- `GET /health`: liveness check plus the active contract.
- `GET /status` (header `x-admin-token`): position, today's P&L, entries today, recent signals.
- `POST /kill` (header `x-admin-token`): blocks new entries and **flattens immediately**. Use `?flatten=false` to only block entries.
- `POST /resume`: clears the kill switch. The daily-loss kill switch stays on until you resume it by hand.
- Stops and targets sit **at the broker** as OCO orders, so your position is still protected if the server or TradingView goes down.
- Risk state (trade count, kill switch) is held in memory and resets when the server restarts.

## Ideas for next steps
- Persist state and the trade log to SQLite, and send Telegram/Discord notifications.
- Add trailing stops or breakeven moves, and other strategies (opening-range breakout, VWAP mean reversion).
- Add other brokers (NinjaTrader/Tradovate via CrossTrade, Interactive Brokers, Rithmic via a bridge).
