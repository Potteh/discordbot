# DealHunter Discord bot

A self-hosted Discord alerting bot for Amazon/Walmart deal observations. **This is a functional monitoring and alerting engine, not a turnkey retailer crawler.** It needs a legitimate authorized product/deal data feed. It does not scrape Amazon or Walmart, discover coupons itself, validate coupon eligibility, or verify in-store penny clearance.

## Setup on Ubuntu

1. Install Python 3.11+ and create a Discord application/bot at https://discord.com/developers/applications.
2. Invite the bot with `bot` and `applications.commands` scopes; grant View Channel, Send Messages, Embed Links.
3. `python3 -m venv .venv && source .venv/bin/activate && pip install -r requirements.txt`
4. `cp .env.example .env`, then edit `.env` to add bot token, server (guild) ID, channel ID, and your authorized `DEAL_FEED_URL`.
5. `python bot.py`

## Feed contract

`GET DEAL_FEED_URL` must return a JSON array or `{"deals": [...]}`. Each record needs `retailer` (`amazon`/`walmart`), `product_id`, `title`, `price`, `url`; optional `regular_price`, `coupon_amount`. URLs must be HTTPS retailer product URLs. Prices are in USD. `coupon_amount` is a **flat dollar amount**, not a percent. The feed provider must independently establish that any coupon is available and applicable. Do not use sample_feed.json as real deal data.

The engine calculates the estimated effective price and posts on price <= `MAX_PENNY_PRICE`, discount >= `MIN_DISCOUNT_PERCENT`, or coupon > 0 and total discount >= 40%. A discount is based on the supplied reference price, which may be inflated or stale. It deduplicates identical product/listed-price/coupon combinations in SQLite, records observations, and supports `/dealstatus` and admin-only `/dealscan`.

## Production limitations

No automatic source discovery or scraping is bundled. For real alerts, connect an appropriately licensed retailer API or authorized deal feed. Walmart store-specific penny clearance requires location-aware inventory/pricing data and cannot be verified by this bot. Coupons may require login, clipping, minimum spend, or eligibility; tax and shipping are excluded. SQLite access assumes one bot process. A restart preserves deduplication history. Alert changes are not edited or deleted when listings expire. Never expose the Discord token.

## Run as systemd

Copy `dealhunter.service.example` and update `User`, `WorkingDirectory`, and `ExecStart` to your deployment paths. Then `sudo cp dealhunter.service.example /etc/systemd/system/dealhunter.service && sudo systemctl daemon-reload && sudo systemctl enable --now dealhunter`.

## Version 2: Walmart store monitoring

The v2 database adds store watchlists, store observations, and scope-specific alert deduplication without deleting the original v1 tables. Run one bot process only. Backup `deals.sqlite3` before upgrading.

New commands: `/watchstore store_id [store_name]` (admin), `/unwatchstore store_id` (admin), `/stores`, `/pricehistory retailer product_id [store_id]`. `/dealscan` and `/dealstatus` remain.

To report an **online** listing, omit `scope` or set `scope: "online"`. To report a **Walmart store** listing, use `scope: "store"`, a numeric `store_id`, and optionally `store_name`, `availability` (`in_stock`, `limited`, `out_of_stock`, `unknown`), integer `quantity`, ISO 8601 UTC `verified_at`, and `source`. See `sample_store_feed.json` (illustrative, NOT real inventory). Store alerts require a watched store, a recent provider verification timestamp, a qualifying price, and availability not explicitly out of stock. Unknown inventory is clearly labeled as unknown; provider data is not independently verified by the bot. An observation timestamp alone does not establish inventory verification.

**Data source limitations:** This package does not access Walmart internal store inventory, scan store shelves, guarantee penny clearance, or independently verify store prices or coupon stacking. Connect an authorized store-specific provider to `DEAL_FEED_URL`; if no provider offers this data, these features remain inactive. Online product data likewise requires a legitimate source. Prices, availability and coupons may vary by store, customer, time and checkout. `DEAL_FEED_URL` should be a trusted HTTPS endpoint; never configure it to an untrusted server because it receives your bearer token.

**Deployment:** Stop the v1 service, back up the SQLite database, replace bot source and dependencies, update `.env` (including `MAX_OBSERVATION_AGE_MINUTES`), and restart the service. The bot needs Discord slash-command permissions. Store watches are guild-scoped but the configured alert channel is global; run one bot per Discord server to avoid cross-server alert routing.
