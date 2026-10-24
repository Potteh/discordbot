# DealHunter v3 — free-first, no required paid API

This version preserves the v2 SQLite schema and adds **optional public HTTPS RSS deal-lead ingestion** and **ZIP-code Walmart store selection** using an authorized store directory CSV. It does not scrape Amazon/Walmart, fabricate retailer prices, or claim to verify penny deals. RSS alerts are clearly labeled unverified leads. Real prices/inventory require an approved JSON data feed.

## Ubuntu upgrade

1. Back up `bot.py`, `.env`, and your SQLite database. **Keep your existing `.env` and database; do not overwrite them.**
2. Stop the running bot (Ctrl+C or `sudo systemctl stop dealhunter`).
3. Unzip the archive to a temporary directory and copy `bot.py` to your existing `/home/michael/dealhunter/discordbot/` directory. Copy `requirements.txt` too. The ZIP's `dealhunter/` folder contains the files.
4. Ensure the database directory is writable (`mkdir -p data`). The existing database remains compatible.
5. `cd /home/michael/dealhunter/discordbot && source .venv/bin/activate && python -m pip install -r requirements.txt`
6. Add new optional variables from `.env.example` to your **existing** `.env`, notably `RSS_FEED_URLS`, `WALMART_STORES_CSV`, `ZIP_LOOKUP_ENABLED`.
7. `python bot.py`. Test `/dealstatus`, `/setzip`, `/findstores`, `/mystores`.

## Free data feeds

Add comma-separated HTTPS RSS URLs to `RSS_FEED_URLS=` only when you have permission to use them. The bot polls each feed, checks deal-related words, deduplicates links, and posts **unverified community leads** to `DEALS_CHANNEL_ID`. Feed availability, rate limits and terms vary; this bot does not include any guaranteed live feeds. An empty feed list means no automatic discovery.

## Walmart ZIP-based store discovery

Populate `walmart_stores.csv` with `store_id,name,address,zip,latitude,longitude` rows obtained from a permitted/authorized directory. This ZIP includes only a blank CSV template; it does not ship with a current national Walmart store directory. `/setzip 32934` saves a user's ZIP. `/findstores` uses the free Zippopotam.us ZIP geocoding endpoint and computes approximate distance to stores in the CSV. `/watchstore` enables store-specific alerts **only if** an authorized structured provider supplies fresh verified-at price/stock observations. ZIP lookup sends the requested ZIP to Zippopotam.us; disable with `ZIP_LOOKUP_ENABLED=false`.

## Scope and limits

- RSS discovery is not actual price verification; avoid calling RSS alerts confirmed errors or verified coupons.
- The structured `DEAL_FEED_URL` is the same authorized JSON feed format as v2 and can report retailer-specific prices, coupons, inventory and verification timestamps.
- `/watchstore` is currently a server-level watchlist, not an individual per-user DM subscription. `/setzip` is per-user. Nationwide RSS alerts are server-channel-wide.
- No Amazon Keepa API or paid subscription is required to run the bot, but coverage depends entirely on your configured feeds.
- Don't share Discord tokens or other API credentials. Rotate any previously exposed token.
- Use a Discord bot account, not a user account/self-bot.

## Security

Do not commit `.env`, `*.sqlite3` or access tokens. RSS URLs should be trusted HTTPS sources; bot does not follow redirects. Test provider permissions and terms.

## v4: category routing
Create five Discord text channels and add their numeric IDs to `.env` as `AMAZON_DEALS_CHANNEL_ID`, `WALMART_DEALS_CHANNEL_ID`, `PRICE_ERRORS_CHANNEL_ID`, `PENNY_DEALS_CHANNEL_ID`, and `COUPON_DEALS_CHANNEL_ID`. Leave `DEALS_CHANNEL_ID` configured as the fallback. Give the bot View Channel, Send Messages and Embed Links in each. Restart the bot and run `/dealstatus` and `/dealscan`.

RSS items are classified using explicit keywords in their titles/descriptions. A deal mentioning coupons or penny deals is routed to that category first. Ambiguous/unrelated items are skipped. **Keyword categories do not verify prices, inventory, retailer identity, coupon eligibility or actual pricing mistakes.** A store-specific penny deal still needs verification at the particular Walmart location. Already-posted RSS URLs remain in `rss_seen` and will not be re-posted solely because routing changed. New qualifying items will go to their new channels. The original database and watchlists are retained.

## v5: Free nationwide Walmart store lookup

`/findstores zip_code:32934 radius_miles:25` uses a configured authorized store CSV if present. Otherwise, it queries the public OpenStreetMap Overpass service for Walmart locations near the ZIP. ZIP geocoding uses Zippopotam.us. Public services can be unavailable or rate-limited; coverage and store metadata are not guaranteed. The lookup is on demand only, not continuous scraping. To disable OSM lookup set `OSM_STORE_DISCOVERY=false`.

For OSM results, use `/watchlocation location_id:node:12345` (or a `way:` / `relation:` identifier), `/mywalmartlocations`, and `/unwatchlocation`. These are **personal saved locations**, not Walmart store numbers and do **not** enable verified store pricing or inventory alerts. Existing `/watchstore` remains a guild-wide numeric Walmart store-number watchlist for authorized structured feeds. Do not confuse the two. No paid API is needed for the public store-location lookup.

Install: back up your existing `bot.py`, `.env`, and SQLite database; stop the bot; copy only this ZIP's `dealhunter/bot.py` to the existing install; keep `.env` and database untouched; restart with the existing virtual environment. Test `/findstores` and `/watchlocation`.

## 🌸 Gardener integrated voice rooms

Gardener runs inside the **same Python process and Discord application** as DealHunter. No second token or Node.js runtime is needed. It uses a separate `gardener.sqlite3` database (configurable via `GARDENER_DATABASE_PATH`). Existing DealHunter database, RSS feed settings, and deal commands remain unchanged.

Enable **Server Members Intent** in the Discord Developer Portal and ensure the bot has **Manage Channels, Move Members, View Channels, Connect, Send Messages, Embed Links** permissions. Voice States is enabled by `discord.Intents.default()`.

Run `pip install -r requirements.txt`, `python bot.py`, and configure these slash commands as a server administrator:

- `/gardener-setup lobby` — select a join-to-create voice channel
- `/gardener-setup logs` — select an audit-log text channel
- `/gardener-setup panel` — post or replace the persistent control panel
- `/garden` — open your private room control menu
- `/8ball question:` — Magic 8 Ball

The panel's persistent **Manage My Room** and **How It Works** buttons survive restarts. Room settings support rename, user limit, public/private, allow, block, unblock, disconnect, and delete. Room ownership and config persist across restarts. Empty rooms are automatically removed when members leave. Gardener logs room creation, deletion, privacy and member-management actions to the configured channel; it is **not** a comprehensive Discord server audit-log mirror.

**Deployment:** Back up `.env` and `deals.sqlite3` before updating. Keep your existing `.env` values; add `GARDENER_DATABASE_PATH` only if you want a custom path. The `gardener.py` file must be in the same directory as `bot.py`. Restart the service after replacing files. Python syntax has been checked, but live Discord permissions and interactions still require testing.
