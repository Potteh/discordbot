"""Self-assign roles and opt-in Twitch/Kick live announcements for DealHunter/Gardener."""
import asyncio
import logging
import os
import re
import sqlite3
from datetime import datetime, timezone

import discord
from discord import app_commands
from discord.ext import commands, tasks
import httpx

log = logging.getLogger('gardener.roles_streams')
ROLE_NAMES = {'streamer': 'Streamer', 'gamer': 'Gamer', 'deal_watcher': 'Deal Watcher'}


def utc_now():
    return datetime.now(timezone.utc).isoformat()


class RoleSelect(discord.ui.Select):
    def __init__(self):
        super().__init__(placeholder='🌸 Select your community roles', min_values=0, max_values=3,
                         options=[discord.SelectOption(label='Streamer', value='streamer', emoji='🎥'),
                                  discord.SelectOption(label='Gamer', value='gamer', emoji='🎮'),
                                  discord.SelectOption(label='Deal Watcher', value='deal_watcher', emoji='🏷️')],
                         custom_id='gardener:roles:choose')

    async def callback(self, interaction: discord.Interaction):
        cog = interaction.client.get_cog('CommunityRoles')
        if not cog or not interaction.guild or not isinstance(interaction.user, discord.Member):
            return await interaction.response.send_message('Role selector unavailable here.', ephemeral=True)
        await interaction.response.defer(ephemeral=True)
        settings = cog.settings(interaction.guild.id)
        mapping = {'streamer': settings[0], 'gamer': settings[1], 'deal_watcher': settings[2]}
        if not all(mapping.values()):
            return await interaction.followup.send('An administrator must configure the three roles first.', ephemeral=True)
        roles = {key: interaction.guild.get_role(role_id) for key, role_id in mapping.items()}
        if not all(roles.values()):
            return await interaction.followup.send('A configured role was deleted. Ask an administrator to reconfigure the panel.', ephemeral=True)
        me = interaction.guild.me
        if not me or not me.guild_permissions.manage_roles or any(role >= me.top_role or role.managed for role in roles.values()):
            return await interaction.followup.send('I cannot assign these roles. Place my role above them and grant Manage Roles.', ephemeral=True)
        chosen = set(self.values)
        add = [role for key, role in roles.items() if key in chosen and role not in interaction.user.roles]
        remove = [role for key, role in roles.items() if key not in chosen and role in interaction.user.roles]
        try:
            if add:
                await interaction.user.add_roles(*add, reason='Gardener self-selected roles')
            if remove:
                await interaction.user.remove_roles(*remove, reason='Gardener self-selected roles')
        except discord.HTTPException as exc:
            log.warning('Role change failed: %s', exc)
            return await interaction.followup.send('Discord refused the role change. Check my role hierarchy.', ephemeral=True)
        await interaction.followup.send('🌸 Your roles have been updated: ' + (', '.join(ROLE_NAMES[k] for k in ROLE_NAMES if k in chosen) or 'none'), ephemeral=True)


class RolePanel(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)
        self.add_item(RoleSelect())


class StreamModal(discord.ui.Modal, title='🌸 Register your stream'):
    platform = discord.ui.TextInput(label='Platform (twitch or kick)', placeholder='twitch', max_length=10)
    username = discord.ui.TextInput(label='Channel username', placeholder='yourchannel', max_length=50)

    async def on_submit(self, interaction: discord.Interaction):
        cog = interaction.client.get_cog('CommunityRoles')
        if not cog:
            return await interaction.response.send_message('Stream service unavailable.', ephemeral=True)
        platform = self.platform.value.strip().lower()
        username = self.username.value.strip().lower()
        if platform not in ('twitch', 'kick') or not re.fullmatch(r'[a-z0-9_]{2,30}', username):
            return await interaction.response.send_message('Choose twitch or kick and enter a valid channel username (letters, numbers, underscores).', ephemeral=True)
        if not interaction.guild or not isinstance(interaction.user, discord.Member):
            return await interaction.response.send_message('Use this in a server.', ephemeral=True)
        cfg = cog.settings(interaction.guild.id)
        role = interaction.guild.get_role(cfg[0]) if cfg[0] else None
        if not role or role not in interaction.user.roles:
            return await interaction.response.send_message('Select the Streamer role first.', ephemeral=True)
        cog.db.execute('INSERT INTO stream_accounts(guild_id,user_id,platform,username,last_live,last_stream_id) VALUES(?,?,?,?,0,\'\') ON CONFLICT(guild_id,user_id,platform) DO UPDATE SET username=excluded.username,last_live=0,last_stream_id=\'\'',
                       (interaction.guild.id, interaction.user.id, platform, username))
        cog.db.commit()
        await interaction.response.send_message(f'🌸 Registered **{platform.title()}**: `{username}`. Gardener checks approximately every 2 minutes. Stream announcements require API configuration.', ephemeral=True)


class StreamPanel(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.button(label='Register Twitch / Kick', emoji='📺', style=discord.ButtonStyle.primary, custom_id='gardener:stream:register')
    async def register(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_modal(StreamModal())

    @discord.ui.button(label='My Stream Accounts', emoji='🌸', style=discord.ButtonStyle.secondary, custom_id='gardener:stream:list')
    async def accounts(self, interaction: discord.Interaction, button: discord.ui.Button):
        cog = interaction.client.get_cog('CommunityRoles')
        rows = cog.db.execute('SELECT platform,username FROM stream_accounts WHERE guild_id=? AND user_id=?', (interaction.guild_id, interaction.user.id)).fetchall()
        await interaction.response.send_message('\n'.join(f'{p}: `{u}`' for p, u in rows) if rows else 'No stream accounts registered.', ephemeral=True)


class CommunityRoles(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        path = os.getenv('GARDENER_COMMUNITY_DATABASE_PATH', 'gardener_community.sqlite3')
        os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
        self.db = sqlite3.connect(path, timeout=20)
        self.db.execute('CREATE TABLE IF NOT EXISTS community_config(guild_id INTEGER PRIMARY KEY, streamer_role INTEGER, gamer_role INTEGER, deal_role INTEGER, shout_channel INTEGER)')
        self.db.execute('CREATE TABLE IF NOT EXISTS stream_accounts(guild_id INTEGER NOT NULL,user_id INTEGER NOT NULL,platform TEXT NOT NULL,username TEXT NOT NULL,last_live INTEGER NOT NULL DEFAULT 0,last_stream_id TEXT NOT NULL DEFAULT \'\',PRIMARY KEY(guild_id,user_id,platform))')
        self.db.commit()
        self.client = httpx.AsyncClient(timeout=12, headers={'User-Agent':'GardenerDiscordBot/1.0'})
        bot.add_view(RolePanel())
        bot.add_view(StreamPanel())
        self.check_streams.start()

    async def cog_unload(self):
        self.check_streams.cancel()
        await self.client.aclose()
        self.db.close()

    def settings(self, guild_id):
        return self.db.execute('SELECT streamer_role,gamer_role,deal_role,shout_channel FROM community_config WHERE guild_id=?',(guild_id,)).fetchone() or (None,None,None,None)

    @app_commands.command(name='community-setup', description='Configure the Gardener role selector and live stream shoutouts')
    @app_commands.describe(streamer='Streamer role', gamer='Gamer role', deal_watcher='Deal Watcher role', shoutouts='Channel for live notifications', panel='Channel to post the selector')
    @app_commands.checks.has_permissions(manage_guild=True)
    async def setup_panel(self, interaction: discord.Interaction, streamer: discord.Role, gamer: discord.Role, deal_watcher: discord.Role, shoutouts: discord.TextChannel, panel: discord.TextChannel):
        if len({streamer.id,gamer.id,deal_watcher.id}) != 3:
            return await interaction.response.send_message('Choose three distinct roles.', ephemeral=True)
        me = interaction.guild.me
        if not me or not me.guild_permissions.manage_roles or any(role >= me.top_role or role.managed for role in (streamer,gamer,deal_watcher)):
            return await interaction.response.send_message('Give me Manage Roles and place my role above all three selectable roles.', ephemeral=True)
        self.db.execute('INSERT INTO community_config VALUES(?,?,?,?,?) ON CONFLICT(guild_id) DO UPDATE SET streamer_role=excluded.streamer_role,gamer_role=excluded.gamer_role,deal_role=excluded.deal_role,shout_channel=excluded.shout_channel',
                        (interaction.guild_id,streamer.id,gamer.id,deal_watcher.id,shoutouts.id))
        self.db.commit()
        try:
            await panel.send(embed=discord.Embed(title='🌸 Choose your Garden roles',description='Select any combination of **🎥 Streamer**, **🎮 Gamer**, and **🏷️ Deal Watcher**. Reopen the menu to change your roles.',color=0xDA97BB),view=RolePanel())
            await panel.send(embed=discord.Embed(title='📺 Share your stream',description='Streamers can register their Twitch or Kick channel here. Live streams will be announced in the configured shoutouts channel.',color=0xDA97BB),view=StreamPanel())
        except discord.HTTPException as exc:
            return await interaction.response.send_message(f'Configuration saved, but posting failed: {exc}',ephemeral=True)
        await interaction.response.send_message(f'🌸 Panels posted in {panel.mention}. Live shoutouts go to {shoutouts.mention}.',ephemeral=True)

    @setup_panel.error
    async def setup_error(self, interaction: discord.Interaction, error: app_commands.AppCommandError):
        if isinstance(error, app_commands.MissingPermissions):
            await interaction.response.send_message('Only members with Manage Server can configure this panel.', ephemeral=True)
        else:
            log.exception('Community setup failed', exc_info=error)
            if not interaction.response.is_done():
                await interaction.response.send_message('Unable to configure the panel. Check bot permissions.', ephemeral=True)

    @app_commands.command(name='stream-remove',description='Remove one of your stream shoutout accounts')
    @app_commands.choices(platform=[app_commands.Choice(name='Twitch',value='twitch'),app_commands.Choice(name='Kick',value='kick')])
    async def remove_stream(self, interaction: discord.Interaction, platform: app_commands.Choice[str]):
        self.db.execute('DELETE FROM stream_accounts WHERE guild_id=? AND user_id=? AND platform=?',(interaction.guild_id,interaction.user.id,platform.value))
        self.db.commit()
        await interaction.response.send_message(f'Removed your {platform.name} stream registration.',ephemeral=True)

    async def twitch_live(self, username):
        cid, secret = os.getenv('TWITCH_CLIENT_ID'), os.getenv('TWITCH_CLIENT_SECRET')
        if not cid or not secret:
            return None
        if not hasattr(self, '_twitch_token') or datetime.now(timezone.utc).timestamp() >= getattr(self,'_twitch_expiry',0):
            response = await self.client.post('https://id.twitch.tv/oauth2/token',data={'client_id':cid,'client_secret':secret,'grant_type':'client_credentials'})
            response.raise_for_status()
            data=response.json()
            self._twitch_token=data['access_token']
            self._twitch_expiry=datetime.now(timezone.utc).timestamp()+data.get('expires_in',3600)-60
        response=await self.client.get('https://api.twitch.tv/helix/streams',params={'user_login':username},headers={'Client-ID':cid,'Authorization':'Bearer '+self._twitch_token})
        response.raise_for_status()
        streams=response.json().get('data',[])
        if not streams:return (False,'','')
        item=streams[0]
        return (True,str(item.get('id','')),item.get('title','Live on Twitch'))

    async def kick_live(self, username):
        # Kick public API requires an app access token; supply it using KICK_ACCESS_TOKEN.
        token=os.getenv('KICK_ACCESS_TOKEN')
        if not token:return None
        response=await self.client.get('https://api.kick.com/public/v1/channels',params={'slug':username},headers={'Authorization':'Bearer '+token,'Accept':'application/json'})
        response.raise_for_status()
        data=response.json().get('data',[])
        if isinstance(data,dict):data=[data]
        item=next((x for x in data if x.get('slug','').lower()==username.lower()),None)
        if not item:return (False,'','')
        stream=item.get('stream') or {}
        live=bool(item.get('stream',{}).get('is_live',False)) if isinstance(stream,dict) else bool(item.get('is_live'))
        return (live,str(stream.get('id') or item.get('livestream_id') or '') if isinstance(stream,dict) else '',item.get('stream_title') or 'Live on Kick')

    @tasks.loop(minutes=2)
    async def check_streams(self):
        rows=self.db.execute('SELECT guild_id,user_id,platform,username,last_live,last_stream_id FROM stream_accounts').fetchall()
        for guild_id,user_id,platform,username,last_live,last_id in rows:
            guild=self.bot.get_guild(guild_id)
            if not guild:continue
            cfg=self.settings(guild_id)
            channel=guild.get_channel(cfg[3]) if cfg[3] else None
            if not channel:continue
            try:
                state=await (self.twitch_live(username) if platform=='twitch' else self.kick_live(username))
                if state is None:continue  # Not configured: do not mark offline or claim alerts work
                live,stream_id,title=state
                if live and not last_live:
                    url=f'https://www.twitch.tv/{username}' if platform=='twitch' else f'https://kick.com/{username}'
                    embed=discord.Embed(title='🔴 Live now: '+discord.utils.escape_markdown(title[:200]),url=url,description=f'**{username}** is streaming on **{platform.title()}**!\n{url}',color=0xDA97BB,timestamp=datetime.now(timezone.utc))
                    await channel.send(content=f'🌸 <@{user_id}> is live!',embed=embed,allowed_mentions=discord.AllowedMentions(users=[discord.Object(id=user_id)],roles=False,everyone=False))
                self.db.execute('UPDATE stream_accounts SET last_live=?,last_stream_id=? WHERE guild_id=? AND user_id=? AND platform=?',(int(live),stream_id if live else '',guild_id,user_id,platform))
                self.db.commit()
            except (httpx.HTTPError,discord.HTTPException,ValueError,KeyError,TypeError) as exc:
                log.warning('Stream check failed for %s/%s: %s',platform,username,exc)
            await asyncio.sleep(1)

    @check_streams.before_loop
    async def before_streams(self):
        await self.bot.wait_until_ready()


async def setup(bot):
    await bot.add_cog(CommunityRoles(bot))
