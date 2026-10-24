"""Gardener voice room management for DealHunter (discord.py 2.4+)."""
import random
import sqlite3
import discord
from discord import app_commands
from discord.ext import commands

ANSWERS=['It is certain 🌸','Signs point to yes 🌷','Without a doubt','Ask again later 🍃','Better not tell you now','Cannot predict now','My reply is no','Very doubtful','Outlook good','Concentrate and ask again']

class RoomModal(discord.ui.Modal):
    def __init__(self, cog, mode):
        super().__init__(title='🌸 Garden room settings')
        self.cog, self.mode=cog,mode
        self.field=discord.ui.TextInput(label='Room name' if mode=='rename' else 'User limit (0–99)',max_length=80 if mode=='rename' else 2)
        self.add_item(self.field)
    async def on_submit(self, i):
        room=await self.cog.owned_room(i)
        if not room:return
        try:
            if self.mode=='rename':await room.edit(name=str(self.field.value).strip()[:80],reason=f'Gardener owner {i.user.id}')
            else:
                n=int(self.field.value)
                if not 0<=n<=99:raise ValueError()
                await room.edit(user_limit=n,reason=f'Gardener owner {i.user.id}')
            await i.response.send_message('🌸 Room updated.',ephemeral=True)
            await self.cog.log(i.guild,f'🌸 {i.user.mention} changed room settings for {room.mention}')
        except (ValueError,discord.HTTPException):await i.response.send_message('Could not update room. Check value and permissions.',ephemeral=True)

class UserPicker(discord.ui.UserSelect):
    def __init__(self,cog,mode):
        super().__init__(placeholder='Select a member',min_values=1,max_values=1)
        self.cog,self.mode=cog,mode
    async def callback(self,i):
        room=await self.cog.owned_room(i)
        if not room:return
        member=self.values[0]
        if not isinstance(member,discord.Member):
            member=i.guild.get_member(member.id)
        if not member:
            await i.response.send_message('Member not found.',ephemeral=True);return
        try:
            if self.mode=='block':
                await room.set_permissions(member,view_channel=False,connect=False,reason=f'Blocked by owner {i.user.id}')
                if member.voice and member.voice.channel==room:await member.move_to(None)
            elif self.mode=='allow':await room.set_permissions(member,view_channel=True,connect=True,reason=f'Allowed by owner {i.user.id}')
            elif self.mode=='unblock':await room.set_permissions(member,overwrite=None,reason=f'Unblocked by owner {i.user.id}')
            elif self.mode=='kick':
                if not member.voice or member.voice.channel!=room:
                    await i.response.send_message('That member is not in your room.',ephemeral=True);return
                await member.move_to(None,reason=f'Removed by owner {i.user.id}')
            await i.response.send_message(f'🌸 {self.mode.title()} applied to {member.mention}.',ephemeral=True)
            await self.cog.log(i.guild,f'🌸 {i.user.mention} used {self.mode} on {member.mention} in {room.name}')
        except discord.HTTPException:await i.response.send_message('Action failed. Check my permissions and role hierarchy.',ephemeral=True)

class UserPickerView(discord.ui.View):
    def __init__(self,cog,mode):
        super().__init__(timeout=120)
        self.add_item(UserPicker(cog,mode))

class ControlView(discord.ui.View):
    def __init__(self,cog):
        super().__init__(timeout=180)
        self.cog=cog
    @discord.ui.button(label='Rename',emoji='✏️',style=discord.ButtonStyle.secondary,row=0)
    async def rename(self,i,b):
        if await self.cog.owned_room(i):await i.response.send_modal(RoomModal(self.cog,'rename'))
    @discord.ui.button(label='User Limit',emoji='👥',style=discord.ButtonStyle.secondary,row=0)
    async def limit(self,i,b):
        if await self.cog.owned_room(i):await i.response.send_modal(RoomModal(self.cog,'limit'))
    @discord.ui.button(label='Private / Public',emoji='🔒',style=discord.ButtonStyle.primary,row=0)
    async def privacy(self,i,b):
        room=await self.cog.owned_room(i)
        if not room:return
        role=i.guild.default_role
        current=room.overwrites_for(role)
        private=current.connect is False
        await room.set_permissions(role,view_channel=None if private else False,connect=None if private else False,reason=f'Gardener privacy by {i.user.id}')
        await i.response.send_message('🌸 Room is now public.' if private else '🔒 Room is now private.',ephemeral=True)
        await self.cog.log(i.guild,f'🌸 {i.user.mention} set {room.name} to {"public" if private else "private"}')
    @discord.ui.button(label='Allow',emoji='✅',style=discord.ButtonStyle.success,row=1)
    async def allow(self,i,b):await self.picker(i,'allow')
    @discord.ui.button(label='Block',emoji='⛔',style=discord.ButtonStyle.danger,row=1)
    async def block(self,i,b):await self.picker(i,'block')
    @discord.ui.button(label='Unblock',emoji='🔓',style=discord.ButtonStyle.secondary,row=1)
    async def unblock(self,i,b):await self.picker(i,'unblock')
    @discord.ui.button(label='Disconnect',emoji='👢',style=discord.ButtonStyle.secondary,row=2)
    async def kick(self,i,b):await self.picker(i,'kick')
    @discord.ui.button(label='Delete Room',emoji='🗑️',style=discord.ButtonStyle.danger,row=2)
    async def delete(self,i,b):
        room=await self.cog.owned_room(i)
        if not room:return
        if len(room.members)>1:
            await i.response.send_message('Room must be empty except for you before deletion.',ephemeral=True);return
        await i.response.defer(ephemeral=True)
        await self.cog.log(i.guild,f'🗑️ {i.user.mention} deleted {room.name}')
        await room.delete(reason='Gardener owner deletion')
        self.cog.db.execute('DELETE FROM gardener_rooms WHERE channel_id=?',(room.id,));self.cog.db.commit()
        await i.followup.send('Room deleted.',ephemeral=True)
    async def picker(self,i,mode):
        if await self.cog.owned_room(i):await i.response.send_message(f'Select member to {mode}:',view=UserPickerView(self.cog,mode),ephemeral=True)

class PanelView(discord.ui.View):
    def __init__(self,cog):
        super().__init__(timeout=None)
        self.cog=cog
    @discord.ui.button(label='Manage My Room',emoji='🌸',style=discord.ButtonStyle.primary,custom_id='gardener:manage')
    async def manage(self,i,b):
        room=await self.cog.owned_room(i)
        if room:await i.response.send_message(f'🌸 Controls for {room.mention}',view=ControlView(self.cog),ephemeral=True)
    @discord.ui.button(label='How It Works',emoji='🌱',style=discord.ButtonStyle.secondary,custom_id='gardener:help')
    async def help(self,i,b):
        await i.response.send_message('Join the configured **Create a Garden** voice lobby. Gardener creates a temporary room for you. Use **Manage My Room** to customize it. Empty rooms disappear automatically.',ephemeral=True)

class Gardener(commands.Cog):
    def __init__(self,bot,db_path):
        self.bot=bot
        self.db=sqlite3.connect(db_path,timeout=20)
        self.db.execute('CREATE TABLE IF NOT EXISTS gardener_config (guild_id INTEGER PRIMARY KEY,lobby_id INTEGER,logs_id INTEGER,panel_id INTEGER,panel_channel_id INTEGER)')
        self.db.execute('CREATE TABLE IF NOT EXISTS gardener_rooms (channel_id INTEGER PRIMARY KEY,guild_id INTEGER,owner_id INTEGER)')
        self.db.commit()
        bot.add_view(PanelView(self))
    async def log(self,guild,message):
        row=self.db.execute('SELECT logs_id FROM gardener_config WHERE guild_id=?',(guild.id,)).fetchone()
        if row and row[0]:
            ch=guild.get_channel(row[0])
            if ch:
                try:await ch.send(message,allowed_mentions=discord.AllowedMentions.none())
                except discord.HTTPException:pass
    async def owned_room(self,i):
        if not i.guild:
            await i.response.send_message('Use this inside a server.',ephemeral=True);return None
        row=self.db.execute('SELECT channel_id FROM gardener_rooms WHERE guild_id=? AND owner_id=?',(i.guild.id,i.user.id)).fetchone()
        room=i.guild.get_channel(row[0]) if row else None
        if not isinstance(room,discord.VoiceChannel):
            await i.response.send_message('You do not own an active Garden room. Join the Garden lobby first.',ephemeral=True);return None
        return room
    @app_commands.command(name='8ball',description='Ask the Garden a question')
    async def eightball(self,i:discord.Interaction,question:str):
        await i.response.send_message(f'🌸 **{discord.utils.escape_markdown(question[:250])}**\n🍃 {random.choice(ANSWERS)}')
    @app_commands.command(name='garden',description='Open your private voice room controls')
    async def garden(self,i:discord.Interaction):
        room=await self.owned_room(i)
        if room:await i.response.send_message(f'🌸 Controls for {room.mention}',view=ControlView(self),ephemeral=True)
    gardener_setup=app_commands.Group(name='gardener-setup',description='Configure Gardener (Manage Server required)',default_permissions=discord.Permissions(manage_guild=True))
    @gardener_setup.command(name='lobby',description='Set the join-to-create voice lobby')
    @app_commands.checks.has_permissions(manage_guild=True)
    async def lobby(self,i:discord.Interaction,channel:discord.VoiceChannel):
        self.db.execute('INSERT INTO gardener_config(guild_id,lobby_id) VALUES(?,?) ON CONFLICT(guild_id) DO UPDATE SET lobby_id=excluded.lobby_id',(i.guild.id,channel.id));self.db.commit()
        await i.response.send_message(f'🌸 Lobby configured: {channel.mention}',ephemeral=True)
    @gardener_setup.command(name='logs',description='Set the Gardener audit-log channel')
    @app_commands.checks.has_permissions(manage_guild=True)
    async def logs(self,i:discord.Interaction,channel:discord.TextChannel):
        self.db.execute('INSERT INTO gardener_config(guild_id,logs_id) VALUES(?,?) ON CONFLICT(guild_id) DO UPDATE SET logs_id=excluded.logs_id',(i.guild.id,channel.id));self.db.commit()
        await i.response.send_message(f'🌸 Logs configured: {channel.mention}',ephemeral=True)
    @gardener_setup.command(name='panel',description='Post a permanent voice-control panel')
    @app_commands.checks.has_permissions(manage_guild=True)
    async def panel(self,i:discord.Interaction,channel:discord.TextChannel):
        await i.response.defer(ephemeral=True)
        row=self.db.execute('SELECT panel_id,panel_channel_id FROM gardener_config WHERE guild_id=?',(i.guild.id,)).fetchone()
        if row and row[0] and row[1]:
            old=i.guild.get_channel(row[1])
            if old:
                try:await (await old.fetch_message(row[0])).delete()
                except discord.HTTPException:pass
        msg=await channel.send(embed=discord.Embed(title='🌸 Gardener • Voice Garden',description='Join the **Create a Garden** voice lobby to create your room. Use the buttons below to manage your space.',color=discord.Color.from_rgb(219,151,187)),view=PanelView(self))
        self.db.execute('INSERT INTO gardener_config(guild_id,panel_id,panel_channel_id) VALUES(?,?,?) ON CONFLICT(guild_id) DO UPDATE SET panel_id=excluded.panel_id,panel_channel_id=excluded.panel_channel_id',(i.guild.id,msg.id,channel.id));self.db.commit()
        await i.followup.send(f'🌸 Panel posted in {channel.mention}',ephemeral=True)
    @commands.Cog.listener()
    async def on_voice_state_update(self,member,before,after):
        if member.bot:return
        guild=member.guild
        row=self.db.execute('SELECT lobby_id FROM gardener_config WHERE guild_id=?',(guild.id,)).fetchone()
        if row and row[0] and after.channel and after.channel.id==row[0] and before.channel!=after.channel:
            old=self.db.execute('SELECT channel_id FROM gardener_rooms WHERE guild_id=? AND owner_id=?',(guild.id,member.id)).fetchone()
            if old and guild.get_channel(old[0]):
                try:await member.move_to(guild.get_channel(old[0]));return
                except discord.HTTPException:pass
            lobby=after.channel
            try:
                room=await guild.create_voice_channel(f'🌸 {member.display_name[:65]}’s Garden',category=lobby.category,overwrites={guild.default_role:discord.PermissionOverwrite(connect=True),member:discord.PermissionOverwrite(view_channel=True,connect=True,manage_channels=False)},reason='Gardener join-to-create')
                self.db.execute('INSERT OR REPLACE INTO gardener_rooms VALUES (?,?,?)',(room.id,guild.id,member.id));self.db.commit()
                await member.move_to(room)
                await self.log(guild,f'🌸 {member.mention} created {room.name}')
            except discord.HTTPException:pass
        if before.channel and before.channel!=after.channel:
            room=before.channel
            owned=self.db.execute('SELECT owner_id FROM gardener_rooms WHERE channel_id=?',(room.id,)).fetchone()
            if owned and not room.members:
                try:await room.delete(reason='Gardener empty-room cleanup')
                except discord.HTTPException:return
                self.db.execute('DELETE FROM gardener_rooms WHERE channel_id=?',(room.id,));self.db.commit()
                await self.log(guild,f'🍃 Empty room deleted: {room.name}')
    @commands.Cog.listener()
    async def on_guild_channel_delete(self,channel):
        self.db.execute('DELETE FROM gardener_rooms WHERE channel_id=?',(channel.id,));self.db.commit()

async def setup(bot):
    import os
    await bot.add_cog(Gardener(bot,os.getenv('GARDENER_DATABASE_PATH','gardener.sqlite3')))
