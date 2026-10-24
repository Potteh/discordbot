import asyncio
import json
import logging
import os
import sqlite3
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from urllib.parse import urlparse
import csv
import re
import math
import xml.etree.ElementTree as ET
from pathlib import Path

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
CATEGORY_CHANNELS = {
    'amazon': int(os.getenv('AMAZON_DEALS_CHANNEL_ID', '0')),
    'walmart': int(os.getenv('WALMART_DEALS_CHANNEL_ID', '0')),
    'price_error': int(os.getenv('PRICE_ERRORS_CHANNEL_ID', '0')),
    'penny': int(os.getenv('PENNY_DEALS_CHANNEL_ID', '0')),
    'coupon': int(os.getenv('COUPON_DEALS_CHANNEL_ID', '0')),
}

INTERVAL = max(5, int(os.getenv('CHECK_MINUTES', '30')))
THRESHOLD = Decimal(os.getenv('MIN_DISCOUNT_PERCENT', '70'))
PENNY = Decimal(os.getenv('MAX_PENNY_PRICE', '1'))
DB = os.getenv('DATABASE_PATH', 'deals.sqlite3')
FEED = os.getenv('DEAL_FEED_URL', '')
BEARER = os.getenv('DEAL_FEED_BEARER_TOKEN', '')
MAX_AGE = max(1, int(os.getenv('MAX_OBSERVATION_AGE_MINUTES', '120')))
RSS_URLS = [x.strip() for x in os.getenv('RSS_FEED_URLS','').split(',') if x.strip()]
STORE_DIRECTORY = os.getenv('WALMART_STORES_CSV', 'walmart_stores.csv')
ZIP_LOOKUP_ENABLED = os.getenv('ZIP_LOOKUP_ENABLED','true').lower() == 'true'
conn = sqlite3.connect(DB)
conn.execute('CREATE TABLE IF NOT EXISTS observations (retailer TEXT, product_id TEXT, title TEXT, price TEXT, regular TEXT, coupon TEXT, url TEXT, observed_at TEXT)')
conn.execute('CREATE TABLE IF NOT EXISTS alerts (retailer TEXT, product_id TEXT, price TEXT, coupon TEXT, PRIMARY KEY (retailer, product_id, price, coupon))')
conn.execute('CREATE TABLE IF NOT EXISTS store_watches (guild_id INTEGER, store_id TEXT, store_name TEXT, PRIMARY KEY(guild_id,store_id))')
conn.execute('CREATE TABLE IF NOT EXISTS store_observations (retailer TEXT, product_id TEXT, store_id TEXT, title TEXT, price TEXT, regular TEXT, coupon TEXT, availability TEXT, quantity INTEGER, verified_at TEXT, observed_at TEXT, source TEXT, PRIMARY KEY(retailer,product_id,store_id,observed_at))')
conn.execute('CREATE TABLE IF NOT EXISTS user_zips (guild_id INTEGER, user_id INTEGER, zip_code TEXT, PRIMARY KEY(guild_id,user_id))')
conn.execute('CREATE TABLE IF NOT EXISTS rss_seen (url TEXT PRIMARY KEY, first_seen TEXT)')
conn.execute('CREATE TABLE IF NOT EXISTS alert_events (scope TEXT, retailer TEXT, product_id TEXT, store_id TEXT, price TEXT, coupon TEXT, availability TEXT, PRIMARY KEY(scope,retailer,product_id,store_id,price,coupon,availability))')
conn.execute('CREATE TABLE IF NOT EXISTS osm_store_watches (guild_id INTEGER, user_id INTEGER, osm_key TEXT, label TEXT, address TEXT, PRIMARY KEY(guild_id,user_id,osm_key))')
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

def load_store_directory():
    path = Path(STORE_DIRECTORY)
    if not path.is_file(): return []
    with path.open(newline='',encoding='utf-8-sig') as f:
        return [row for row in csv.DictReader(f) if row.get('store_id','').isdigit() and row.get('latitude') and row.get('longitude')]

def distance_miles(a,b,c,d):
    a,b,c,d=map(math.radians,(a,b,c,d))
    x=math.sin((c-a)/2)**2+math.cos(a)*math.cos(c)*math.sin((d-b)/2)**2
    return 3958.8*2*math.asin(min(1,math.sqrt(x)))

async def zip_coordinates(zip_code):
    if not re.fullmatch(r'\d{5}',zip_code): return None
    if not ZIP_LOOKUP_ENABLED: return None
    async with httpx.AsyncClient(timeout=12,follow_redirects=False) as client:
        res=await client.get(f'https://api.zippopotam.us/us/{zip_code}')
        if res.status_code != 200: return None
        obj=res.json(); places=obj.get('places') or []
        if not places: return None
        return float(places[0]['latitude']),float(places[0]['longitude'])

# Public OpenStreetMap POI discovery, not an official Walmart directory.
# Do not treat OSM element identifiers as Walmart store numbers.
OSM_DISCOVERY = os.getenv('OSM_STORE_DISCOVERY', 'true').lower() == 'true'
OSM_ENDPOINT = 'https://overpass.kumi.systems/api/interpreter'

async def discover_osm_walmarts(lat, lon, radius_miles):
    if not OSM_DISCOVERY: return [], 'disabled'
    radius_m = min(100, max(1, radius_miles)) * 1609.344
    query = f'[out:json][timeout:20];(nwr(around:{radius_m:.0f},{lat:.6f},{lon:.6f})[shop=supermarket][name~"Walmart",i];nwr(around:{radius_m:.0f},{lat:.6f},{lon:.6f})[brand~"Walmart",i];);out center 100;'
    async with httpx.AsyncClient(timeout=28,follow_redirects=False,headers={'User-Agent':'DealHunter/5.0 (Discord store finder; contact your server administrator)'}) as client:
        res = await client.post(OSM_ENDPOINT, data={'data':query})
        res.raise_for_status()
        elements = res.json().get('elements',[])
    found=[]
    for e in elements:
        tags=e.get('tags') or {}
        if 'walmart' not in (tags.get('name','')+' '+tags.get('brand','')).lower(): continue
        pt=e.get('center') or e
        if not isinstance(pt.get('lat'),(int,float)) or not isinstance(pt.get('lon'),(int,float)): continue
        key=f"{e.get('type','')}:{e.get('id','')}"
        if not re.fullmatch(r'(node|way|relation):\d+',key): continue
        addr=' '.join(filter(None,[tags.get('addr:housenumber',''),tags.get('addr:street','')])).strip()
        if tags.get('addr:city'): addr += (', ' if addr else '')+tags['addr:city']
        dist=distance_miles(lat,lon,float(pt['lat']),float(pt['lon']))
        if dist<=radius_miles:found.append((dist,key,tags.get('name','Walmart')[:80],addr[:120]))
    return sorted(found), 'openstreetmap'

def categorize_lead(title, description, link):
    """Conservative, text-based categories; never claim price verification."""
    text = re.sub(r'<[^>]*>', ' ', title + ' ' + description).lower()
    host = (urlparse(link).hostname or '').lower()
    # Link destination is often a deal community URL; use explicit merchant mentions.
    amazon = bool(re.search(r'\bamazon\b', text)) or host in ('amazon.com','www.amazon.com')
    walmart = bool(re.search(r'\bwalmart\b', text)) or host in ('walmart.com','www.walmart.com')
    penny = bool(re.search(r'\bpenny\s+deal(s)?\b|\b(?:\$0\.01|1[ -]?cent)\b', text))
    price_error = bool(re.search(r'\bprice\s+(?:error|mistake|glitch)\b|\bmisprice(?:d)?\b', text))
    coupon = bool(re.search(r'\bcoupon(s)?\b|\bpromo\s*code\b|\bclip(?:pable)?\s+coupon\b', text))
    if penny: return 'penny'
    if price_error: return 'price_error'
    if coupon: return 'coupon'
    if amazon and not walmart: return 'amazon'
    if walmart and not amazon: return 'walmart'
    return None

async def destination(category):
    target_id = CATEGORY_CHANNELS.get(category, 0) or CHANNEL_ID
    if not target_id: return None
    try:
        return bot.get_channel(target_id) or await bot.fetch_channel(target_id)
    except (discord.Forbidden, discord.NotFound):
        logging.warning('Cannot access channel for %s (%s); trying fallback', category, target_id)
        if CHANNEL_ID and target_id != CHANNEL_ID:
            try: return bot.get_channel(CHANNEL_ID) or await bot.fetch_channel(CHANNEL_ID)
            except (discord.Forbidden, discord.NotFound): pass
        return None

async def scan_rss():
    # RSS is discovery of third-party deal *leads*, not verified price or inventory.
    # Only configured HTTPS URLs are read; no retailer scraping.
    if not RSS_URLS or not (CHANNEL_ID or any(CATEGORY_CHANNELS.values())): return (0,0)
    inspected=posted=0
    async with httpx.AsyncClient(timeout=20,follow_redirects=False,headers={'User-Agent':'DealHunter/3.0 (RSS reader)'}) as client:
        for url in RSS_URLS:
            parsed=urlparse(url)
            if parsed.scheme!='https' or not parsed.hostname: continue
            try:
                response=await client.get(url);response.raise_for_status()
                if len(response.content)>2_000_000: continue
                root=ET.fromstring(response.content)
                entries=root.findall('.//item')
                if not entries:
                    entries=root.findall('{http://www.w3.org/2005/Atom}entry')
                for entry in entries[:75]:
                    def val(tag):
                        node=entry.find(tag)
                        return (node.text or '').strip() if node is not None else ''
                    title=val('title') or val('{http://www.w3.org/2005/Atom}title')
                    link=val('link')
                    if not link:
                        el=entry.find('{http://www.w3.org/2005/Atom}link')
                        link=el.get('href','') if el is not None else ''
                    if not title or not link or urlparse(link).scheme!='https': continue
                    inspected+=1
                    category=categorize_lead(title,val('description'),link)
                    if category is None: continue
                    if conn.execute('SELECT 1 FROM rss_seen WHERE url=?',(link,)).fetchone():continue
                    channel = await destination(category)
                    if channel is None: continue
                    label={'amazon':'Amazon','walmart':'Walmart','price_error':'Possible price error','penny':'Potential penny deal','coupon':'Coupon lead'}[category]
                    embed=discord.Embed(title=title[:240],url=link,description=f'**{label} (keyword classification)**\nCommunity deal lead — price, stock, coupons, and store availability are **unverified**.',color=discord.Color.orange())
                    embed.set_footer(text='Third-party RSS lead; verify on retailer site before purchasing. Not a confirmed price error.')
                    await channel.send(embed=embed)
                    conn.execute('INSERT OR IGNORE INTO rss_seen VALUES (?,?)',(link,datetime.now(timezone.utc).isoformat()))
                    posted+=1
                conn.commit()
            except Exception: logging.exception('RSS source failed: %s',urlparse(url).hostname)
    return inspected,posted

intents=discord.Intents.default()
bot=commands.Bot(command_prefix='!',intents=intents)

async def scan():
    async with lock:
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
            category = ('penny' if effective <= PENNY else 'price_error' if discount >= THRESHOLD else 'coupon')
            if category == 'price_error' and discount < THRESHOLD: category = r
            channel = await destination(category)
            if channel is None: continue
            await channel.send(embed=embed)
            conn.execute('INSERT INTO alert_events VALUES (?,?,?,?,?,?,?)',key)
            if scope=='online': conn.execute('INSERT OR IGNORE INTO alerts VALUES (?,?,?,?)',(r,pid,str(price),str(coupon)))
            sent+=1
        conn.commit()
        return len(deals),sent

@tasks.loop(minutes=INTERVAL)
async def periodic_scan():
    if not (CHANNEL_ID or any(CATEGORY_CHANNELS.values())) or not (FEED or RSS_URLS): return
    try:
        n=s=0
        if FEED: n,s=await scan()
        rn,rs=await scan_rss()
        logging.info('Scanned %d structured observations and %d RSS leads; posted %d alerts',n,rn,s+rs)
    except Exception: logging.exception('Periodic scan failed')

@periodic_scan.before_loop
async def before_scan(): await bot.wait_until_ready()

@bot.event
async def on_ready():
    if not periodic_scan.is_running(): periodic_scan.start()
    logging.info('Logged in as %s; structured feed=%s; RSS sources=%d',bot.user,bool(FEED),len(RSS_URLS))

@bot.tree.command(name='dealstatus',description='Show DealHunter monitoring status')
async def dealstatus(interaction:discord.Interaction):
    n=conn.execute('SELECT COUNT(*) FROM observations').fetchone()[0]
    sn=conn.execute('SELECT COUNT(*) FROM store_observations').fetchone()[0]
    watches=conn.execute('SELECT COUNT(*) FROM store_watches WHERE guild_id=?',(interaction.guild_id or 0,)).fetchone()[0]
    await interaction.response.send_message(f'Structured feed: {bool(FEED)} | RSS sources: {len(RSS_URLS)} | Routed channels: {sum(bool(x) for x in CATEGORY_CHANNELS.values())} | Scan interval: {INTERVAL} min | Online observations: {n} | Store observations: {sn} | Watched stores: {watches} | Discount threshold: {THRESHOLD}%',ephemeral=True)

@bot.tree.command(name='dealscan',description='Run an immediate deal scan (Manage Server permission)')
@app_commands.default_permissions(manage_guild=True)
@app_commands.checks.has_permissions(manage_guild=True)
async def dealscan(interaction:discord.Interaction):
    if not (FEED or RSS_URLS) or not (CHANNEL_ID or any(CATEGORY_CHANNELS.values())):
        await interaction.response.send_message('Configure RSS_FEED_URLS or DEAL_FEED_URL and at least one alert channel first.',ephemeral=True);return
    await interaction.response.defer(ephemeral=True)
    try:
        n=s=0
        if FEED: n,s=await scan()
        rn,rs=await scan_rss()
        await interaction.followup.send(f'Scanned {n} structured observations and {rn} RSS leads; posted {s+rs} alerts.',ephemeral=True)
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

@bot.tree.command(name='setzip',description='Save your ZIP code for Walmart store lookup')
@app_commands.describe(zip_code='Five-digit US ZIP code')
async def setzip(interaction:discord.Interaction,zip_code:str):
    if not re.fullmatch(r'\d{5}',zip_code):
        await interaction.response.send_message('Enter a five-digit US ZIP code.',ephemeral=True);return
    conn.execute('INSERT OR REPLACE INTO user_zips VALUES (?,?,?)',(interaction.guild_id or 0,interaction.user.id,zip_code));conn.commit()
    await interaction.response.send_message(f'ZIP set to {zip_code}. Use /findstores to look for stores in the configured directory.',ephemeral=True)

@bot.tree.command(name='findstores',description='Find Walmart stores near a ZIP from the configured store directory')
@app_commands.describe(zip_code='Optional ZIP (defaults to your saved ZIP)',radius_miles='Search radius in miles (1–100)')
async def findstores(interaction:discord.Interaction,zip_code:str='',radius_miles:int=25):
    if not 1<=radius_miles<=100:
        await interaction.response.send_message('Radius must be 1–100 miles.',ephemeral=True);return
    if not zip_code:
        row=conn.execute('SELECT zip_code FROM user_zips WHERE guild_id=? AND user_id=?',(interaction.guild_id or 0,interaction.user.id)).fetchone()
        zip_code=row[0] if row else ''
    if not re.fullmatch(r'\d{5}',zip_code):
        await interaction.response.send_message('Use /setzip first, or supply a five-digit ZIP.',ephemeral=True);return
    await interaction.response.defer(ephemeral=True)
    try: loc=await zip_coordinates(zip_code)
    except Exception: loc=None
    if not loc:
        await interaction.followup.send('ZIP lookup unavailable. Try again later or check ZIP_LOOKUP_ENABLED.',ephemeral=True);return
    stores=load_store_directory()
    results=[]
    for store in stores:
        try: dist=distance_miles(*loc,float(store['latitude']),float(store['longitude']))
        except (ValueError,KeyError):continue
        if dist<=radius_miles: results.append((dist,store))
    results.sort(key=lambda x:x[0])
    if results:
        lines=[f"#{r['store_id']} — {r.get('name','Walmart')} · {dist:.1f} mi · {r.get('address','')}" for dist,r in results[:15]]
        await interaction.followup.send('Nearby stores from configured CSV (not live inventory):\n'+'\n'.join(lines)[:1700]+'\nUse /watchstore for provider-reported store prices.',ephemeral=True)
        return
    try:
        found, source = await discover_osm_walmarts(*loc,radius_miles)
    except Exception:
        logging.exception('OpenStreetMap lookup failed')
        await interaction.followup.send('Store lookup temporarily unavailable. OpenStreetMap may be rate-limiting requests. Try again later or supply an authorized store CSV.',ephemeral=True)
        return
    if not found:
        await interaction.followup.send('No Walmart locations found in available OpenStreetMap data within that radius. Results may be incomplete.',ephemeral=True)
        return
    lines=[f'{key} — {name} · {dist:.1f} mi · {address}' for dist,key,name,address in found[:12]]
    await interaction.followup.send(('Nearby Walmart locations (community OpenStreetMap data; NOT store numbers, prices or stock):\n'+'\n'.join(lines)+'\nUse /watchlocation with the node:/way:/relation: ID.').strip()[:1900],ephemeral=True)

@bot.tree.command(name='watchlocation',description='Follow a Walmart location found using /findstores (personal watchlist)')
@app_commands.describe(location_id='OpenStreetMap ID such as node:12345',label='Optional short label')
async def watchlocation(interaction:discord.Interaction,location_id:str,label:str=''):
    if not re.fullmatch(r'(node|way|relation):\d{1,20}',location_id):
        await interaction.response.send_message('Enter an OpenStreetMap location ID from /findstores, e.g. node:12345.',ephemeral=True);return
    conn.execute('INSERT OR REPLACE INTO osm_store_watches VALUES (?,?,?,?,?)',(interaction.guild_id or 0,interaction.user.id,location_id,label[:80] or 'Walmart location',''))
    conn.commit()
    await interaction.response.send_message('Saved location '+location_id+'. This follows the location only; live price/inventory alerts require a separately verified provider store number.',ephemeral=True)

@bot.tree.command(name='mywalmartlocations',description='List your selected Walmart locations')
async def mywalmartlocations(interaction:discord.Interaction):
    rows=conn.execute('SELECT osm_key,label FROM osm_store_watches WHERE guild_id=? AND user_id=? ORDER BY osm_key LIMIT 30',(interaction.guild_id or 0,interaction.user.id)).fetchall()
    await interaction.response.send_message('\n'.join(f'{key} — {label}' for key,label in rows) if rows else 'No personal locations saved. Use /findstores then /watchlocation.',ephemeral=True)

@bot.tree.command(name='unwatchlocation',description='Remove a location from your personal watchlist')
async def unwatchlocation(interaction:discord.Interaction,location_id:str):
    conn.execute('DELETE FROM osm_store_watches WHERE guild_id=? AND user_id=? AND osm_key=?',(interaction.guild_id or 0,interaction.user.id,location_id))
    conn.commit()
    await interaction.response.send_message('Removed '+location_id+' from your personal location watchlist.',ephemeral=True)

@bot.tree.command(name='mystores',description='List the Walmart stores watched by this server')
async def mystores(interaction:discord.Interaction):
    rows=conn.execute('SELECT store_id,store_name FROM store_watches WHERE guild_id=? ORDER BY store_id LIMIT 50',(interaction.guild_id or 0,)).fetchall()
    await interaction.response.send_message('\n'.join(f'#{sid} {name}' for sid,name in rows) if rows else 'No watched stores.',ephemeral=True)

async def main():
    await bot.load_extension('gardener')
    if not TOKEN: raise RuntimeError('Set DISCORD_TOKEN in .env')
    async with bot:
        if GUILD_ID:
            guild=discord.Object(id=GUILD_ID);bot.tree.copy_global_to(guild=guild);await bot.login(TOKEN);await bot.tree.sync(guild=guild)
        else:
            await bot.login(TOKEN)
            await bot.tree.sync()
        await bot.connect(reconnect=True)

if __name__=='__main__': asyncio.run(main())
