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
