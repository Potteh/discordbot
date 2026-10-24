import asyncio
import json
import logging
import os
import sqlite3
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from urllib.parse import urlparse

import discord
import httpx
from discord import app_commands
from discord.ext import commands, tasks
from dotenv import load_dotenv

load_dotenv()
logging.basicConfig(level=logging.INFO)
TOKEN = os.getenv('DISCORD_TOKEN', '')
GUILD_ID = int(os.getenv('DISCORD_GUILD_ID', '0'))
CHANNEL_ID = int(os.getenv('DEALS_CHANNEL_ID', '0'))
INTERVAL = max(5, int(os.getenv('CHECK_MINUTES', '30')))
THRESHOLD = Decimal(os.getenv('MIN_DISCOUNT_PERCENT', '70'))
PENNY = Decimal(os.getenv('MAX_PENNY_PRICE', '1'))
DB = os.getenv('DATABASE_PATH', 'deals.sqlite3')
FEED = os.getenv('DEAL_FEED_URL', '')
BEARER = os.getenv('DEAL_FEED_BEARER_TOKEN', '')
MAX_AGE = max(1, int(os.getenv('MAX_OBSERVATION_AGE_MINUTES', '120')))
conn = sqlite3.connect(DB)
conn.execute('CREATE TABLE IF NOT EXISTS observations (retailer TEXT, product_id TEXT, title TEXT, price TEXT, regular TEXT, coupon TEXT, url TEXT, observed_at TEXT)')
conn.execute('CREATE TABLE IF NOT EXISTS alerts (retailer TEXT, product_id TEXT, price TEXT, coupon TEXT, PRIMARY KEY (retailer, product_id, price, coupon))')
conn.execute('CREATE TABLE IF NOT EXISTS store_watches (guild_id INTEGER, store_id TEXT, store_name TEXT, PRIMARY KEY(guild_id,store_id))')
conn.execute('CREATE TABLE IF NOT EXISTS store_observations (retailer TEXT, product_id TEXT, store_id TEXT, title TEXT, price TEXT, regular TEXT, coupon TEXT, availability TEXT, quantity INTEGER, verified_at TEXT, observed_at TEXT, source TEXT, PRIMARY KEY(retailer,product_id,store_id,observed_at))')
conn.execute('CREATE TABLE IF NOT EXISTS alert_events (scope TEXT, retailer TEXT, product_id TEXT, store_id TEXT, price TEXT, coupon TEXT, availability TEXT, PRIMARY KEY(scope,retailer,product_id,store_id,price,coupon,availability))')
conn.commit()
lock = asyncio.Lock()

def money(v):
    try:
        d = Decimal(str(v))
        return d.quantize(Decimal('0.01')) if d.is_finite() and d >= 0 else None
    except (InvalidOperation, ValueError, TypeError):
        return None

def parse_time(v):
    if not isinstance(v,str): return None
    try:
        dt = datetime.fromisoformat(v.replace('Z','+00:00'))
        return dt.astimezone(timezone.utc) if dt.tzinfo else None
    except ValueError: return None

def normalize(raw):
    if not isinstance(raw,dict): return None
    retailer = str(raw.get('retailer','')).lower().strip()
    if retailer not in ('amazon','walmart'): return None
    url = str(raw.get('url','')).strip()
    p = urlparse(url)
    if p.scheme != 'https' or not p.hostname: return None
    host = p.hostname.lower()
    if host not in ('amazon.com','www.amazon.com','walmart.com','www.walmart.com') and not (host.endswith('.amazon.com') or host.endswith('.walmart.com')): return None
    if retailer not in host: return None
    pid = str(raw.get('product_id','')).strip()[:100]
    title = str(raw.get('title','')).strip()[:200]
    price, regular, coupon = money(raw.get('price')), money(raw.get('regular_price')), money(raw.get('coupon_amount',0))
    if not pid or not title or price is None or coupon is None: return None
    scope = str(raw.get('scope','online')).lower().strip()
    if scope not in ('online','store'): return None
    store_id = str(raw.get('store_id','')).strip()[:30] if scope == 'store' else ''
    if scope == 'store' and (retailer != 'walmart' or not store_id.isdigit()): return None
    availability = str(raw.get('availability','unknown')).lower().strip()
    if availability not in ('in_stock','limited','out_of_stock','unknown'): availability = 'unknown'
    qty = raw.get('quantity')
    if isinstance(qty,bool) or not isinstance(qty,int) or qty < 0: qty = None
    verified = parse_time(raw.get('verified_at'))
    source = str(raw.get('source','authorized feed')).strip()[:100]
    return dict(retailer=retailer,product_id=pid,title=title,url=url,price=price,regular_price=regular,coupon_amount=coupon,scope=scope,store_id=store_id,store_name=str(raw.get('store_name','')).strip()[:100],availability=availability,quantity=qty,verified_at=verified,source=source)

def classify(item):
    price,regular,coupon=item['price'],item['regular_price'],item['coupon_amount']
    effective=max(Decimal('0'),price-coupon)
    discount=(regular-effective)/regular*100 if regular and regular>effective else Decimal(0)
    if effective<=PENNY: kind='PENNY / ULTRA-LOW PRICE'
    elif discount>=THRESHOLD: kind='POSSIBLE PRICE ERROR / HUGE SAVINGS'
    elif coupon>0 and discount>=40: kind='LARGE COUPON SAVINGS'
    else: return None
    return kind,effective,discount

async def fetch_deals():
    if not FEED: return []
    if not FEED.startswith('https://'): raise ValueError('DEAL_FEED_URL must use HTTPS')
    headers={'Authorization':f'Bearer {BEARER}'} if BEARER else {}
    async with httpx.AsyncClient(timeout=20,follow_redirects=False) as client:
        response=await client.get(FEED,headers=headers)
        response.raise_for_status()
        data=response.json()
    if isinstance(data,dict): data=data.get('deals',[])
    if not isinstance(data,list): raise ValueError('Feed must be a JSON array or {"deals": [...]}')
    return [x for raw in data[:2000] if (x:=normalize(raw))]

intents=discord.Intents.default()
bot=commands.Bot(command_prefix='!',intents=intents)

async def scan():
    async with lock:
        channel=bot.get_channel(CHANNEL_ID) or await bot.fetch_channel(CHANNEL_ID)
        deals=await fetch_deals()
        sent=0
        for item in deals:
            r,pid=item['retailer'],item['product_id']
            now=datetime.now(timezone.utc)
            price,regular,coupon=item['price'],item['regular_price'],item['coupon_amount']
            result=classify(item)
            if item['scope']=='online':
                conn.execute('INSERT INTO observations VALUES (?,?,?,?,?,?,?,?)',(r,pid,item['title'],str(price),str(regular) if regular is not None else '',str(coupon),item['url'],now.isoformat()))
            else:
                conn.execute('INSERT OR IGNORE INTO store_observations VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)',(r,pid,item['store_id'],item['title'],str(price),str(regular) if regular is not None else '',str(coupon),item['availability'],item['quantity'],item['verified_at'].isoformat() if item['verified_at'] else '',now.isoformat(),item['source']))
            if not result: continue
            if item['scope']=='store':
                watches=conn.execute('SELECT 1 FROM store_watches WHERE store_id=? LIMIT 1',(item['store_id'],)).fetchone()
                if not watches: continue
                if item['availability']=='out_of_stock': continue
                if not item['verified_at'] or (now-item['verified_at']).total_seconds()>MAX_AGE*60 or item['verified_at']>now: continue
            kind,effective,discount=result
            scope=item['scope']; sid=item['store_id']; avail=item['availability'] if scope=='store' else ''
            key=(scope,r,pid,sid,str(price),str(coupon),avail)
            if conn.execute('SELECT 1 FROM alert_events WHERE scope=? AND retailer=? AND product_id=? AND store_id=? AND price=? AND coupon=? AND availability=?',key).fetchone(): continue
            embed=discord.Embed(title=f'{kind}: {item["title"]}',url=item['url'],color=discord.Color.green())
            embed.add_field(name='Retailer',value=r.title())
            embed.add_field(name='Listed price',value=f'${price}')
            embed.add_field(name='Estimated after coupon',value=f'${effective}')
            embed.add_field(name='Reference price',value=f'${regular}' if regular is not None else 'Unknown')
            embed.add_field(name='Potential discount',value=f'{discount:.1f}%')
            embed.add_field(name='Coupon',value=f'${coupon} (eligibility not independently checked)')
            if scope=='store':
                embed.add_field(name='Walmart store',value=f'{item["store_name"] or "Store"} #{sid}')
                embed.add_field(name='Feed-reported inventory',value=item['availability'].replace('_',' ').title()+(f' · {item["quantity"]} units reported' if item['quantity'] is not None else ''))
                embed.add_field(name='Last provider verification',value=item['verified_at'].strftime('%Y-%m-%d %H:%M UTC'))
                embed.add_field(name='Source',value=item['source'])
            embed.set_footer(text='Provider-reported data, not independently checked by bot. In-store prices/stock and coupon eligibility can differ. Tax/shipping excluded.')
            await channel.send(embed=embed)
            conn.execute('INSERT INTO alert_events VALUES (?,?,?,?,?,?,?)',key)
            if scope=='online': conn.execute('INSERT OR IGNORE INTO alerts VALUES (?,?,?,?)',(r,pid,str(price),str(coupon)))
            sent+=1
        conn.commit()
        return len(deals),sent

@tasks.loop(minutes=INTERVAL)
async def periodic_scan():
    if not CHANNEL_ID or not FEED: return
    try:
        n,s=await scan(); logging.info('Scanned %d deals, sent %d alerts',n,s)
    except Exception: logging.exception('Periodic scan failed')

@periodic_scan.before_loop
async def before_scan(): await bot.wait_until_ready()

@bot.event
async def on_ready():
    if not periodic_scan.is_running(): periodic_scan.start()
    logging.info('Logged in as %s; feed configured=%s',bot.user,bool(FEED))

@bot.tree.command(name='dealstatus',description='Show DealHunter monitoring status')
async def dealstatus(interaction:discord.Interaction):
    n=conn.execute('SELECT COUNT(*) FROM observations').fetchone()[0]
    sn=conn.execute('SELECT COUNT(*) FROM store_observations').fetchone()[0]
    watches=conn.execute('SELECT COUNT(*) FROM store_watches WHERE guild_id=?',(interaction.guild_id or 0,)).fetchone()[0]
    await interaction.response.send_message(f'Feed configured: {bool(FEED)} | Scan interval: {INTERVAL} min | Online observations: {n} | Store observations: {sn} | Watched stores: {watches} | Discount threshold: {THRESHOLD}%',ephemeral=True)

@bot.tree.command(name='dealscan',description='Run an immediate deal scan (Manage Server permission)')
@app_commands.default_permissions(manage_guild=True)
@app_commands.checks.has_permissions(manage_guild=True)
async def dealscan(interaction:discord.Interaction):
    if not FEED or not CHANNEL_ID:
        await interaction.response.send_message('Set DEAL_FEED_URL and DEALS_CHANNEL_ID first.',ephemeral=True);return
    await interaction.response.defer(ephemeral=True)
    try:
        n,s=await scan(); await interaction.followup.send(f'Scanned {n} observations; posted {s} alerts.',ephemeral=True)
    except Exception as e:
        logging.exception('Manual scan failed');await interaction.followup.send(f'Scan failed: {type(e).__name__}. See logs.',ephemeral=True)

@bot.tree.command(name='watchstore',description='Watch a Walmart store number (Manage Server permission)')
@app_commands.default_permissions(manage_guild=True)
@app_commands.checks.has_permissions(manage_guild=True)
@app_commands.describe(store_id='Walmart numeric store number',store_name='Optional label for your store')
async def watchstore(interaction:discord.Interaction,store_id:str,store_name:str=''):
    if not interaction.guild_id or not store_id.isdigit() or len(store_id)>10:
        await interaction.response.send_message('Provide a numeric Walmart store number in a server.',ephemeral=True);return
    conn.execute('INSERT OR REPLACE INTO store_watches VALUES (?,?,?)',(interaction.guild_id,store_id,store_name[:100]));conn.commit()
    await interaction.response.send_message(f'Watching Walmart store #{store_id}. Alerts require a fresh store-specific authorized feed observation.',ephemeral=True)

@bot.tree.command(name='unwatchstore',description='Stop watching a Walmart store (Manage Server permission)')
@app_commands.default_permissions(manage_guild=True)
@app_commands.checks.has_permissions(manage_guild=True)
async def unwatchstore(interaction:discord.Interaction,store_id:str):
    conn.execute('DELETE FROM store_watches WHERE guild_id=? AND store_id=?',(interaction.guild_id or 0,store_id));conn.commit()
    await interaction.response.send_message(f'Removed Walmart store #{store_id} from watchlist.',ephemeral=True)

@bot.tree.command(name='stores',description='List Walmart stores watched by this server')
async def stores(interaction:discord.Interaction):
    rows=conn.execute('SELECT store_id,store_name FROM store_watches WHERE guild_id=? ORDER BY store_id LIMIT 50',(interaction.guild_id or 0,)).fetchall()
    await interaction.response.send_message('\n'.join(f'#{sid} {name}' for sid,name in rows) if rows else 'No watched stores. An admin can use /watchstore.',ephemeral=True)

@bot.tree.command(name='pricehistory',description='Show recently observed online or Walmart store prices')
@app_commands.describe(retailer='amazon or walmart',product_id='Product identifier',store_id='Optional Walmart store number')
async def pricehistory(interaction:discord.Interaction,retailer:str,product_id:str,store_id:str=''):
    retailer=retailer.lower().strip()
    if retailer not in ('amazon','walmart') or not product_id.strip():
        await interaction.response.send_message('Retailer must be amazon or walmart; provide a product ID.',ephemeral=True);return
    if store_id:
        rows=conn.execute('SELECT price,availability,verified_at FROM store_observations WHERE retailer=? AND product_id=? AND store_id=? ORDER BY observed_at DESC LIMIT 10',(retailer,product_id,store_id)).fetchall()
        lines=[f'${p} · {a} · verified {t or "unknown"}' for p,a,t in rows]
    else:
        rows=conn.execute('SELECT price,observed_at FROM observations WHERE retailer=? AND product_id=? ORDER BY observed_at DESC LIMIT 10',(retailer,product_id)).fetchall()
        lines=[f'${p} · observed {t}' for p,t in rows]
    await interaction.response.send_message('\n'.join(lines)[:1900] if lines else 'No observations found.',ephemeral=True)

async def main():
    if not TOKEN: raise RuntimeError('Set DISCORD_TOKEN in .env')
    async with bot:
        if GUILD_ID:
            guild=discord.Object(id=GUILD_ID);bot.tree.copy_global_to(guild=guild);await bot.tree.sync(guild=guild)
        else: await bot.tree.sync()
        await bot.start(TOKEN)

if __name__=='__main__': asyncio.run(main())
