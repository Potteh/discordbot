"""Gardener voice room management for DealHunter (discord.py 2.4+)."""
import asyncio
import random
import logging
import os
import sqlite3
import discord
from discord import app_commands
from discord.ext import commands

logger=logging.getLogger("gardener")

ANSWERS=['It is certain 🌸','Signs point to yes 🌷','Without a doubt','Ask again later 🍃','Better not tell you now','Cannot predict now','My reply is no','Very doubtful','Outlook good','Concentrate and ask again']


# Offline 20 Questions: a curated knowledge base; no external Akinator service.
TRAITS = [
 ('alive','Is it alive?'),('animal','Is it an animal?'),('person','Is it a person?'),
 ('fictional','Is it fictional?'),('pet','Is it commonly kept as a pet?'),
 ('wild','Is it usually found in the wild?'),('water','Is it associated with water?'),
 ('fly','Can it fly?'),('large','Is it typically larger than a person?'),
 ('technology','Is it a piece of technology?'),('food','Is it something you eat?'),
 ('vehicle','Is it used for transportation?'),('nature','Is it found in nature?'),
 ('home','Would you commonly find it in a home?'),('game','Is it associated with games?'),
 ('famous','Is it a well-known character or public figure?'),
 ('plant','Is it a plant?'),('electric','Does it usually use electricity?'),
 ('round','Is it usually round?'),('sport','Is it associated with sports?'),
 ('music','Is it associated with music?'),('space','Is it associated with outer space?'),
 ('fantasy','Is it associated with fantasy or magic?'),('wear','Can someone wear it?'),
 ('cold','Is it normally cold?'),('metal','Is it typically made of metal?'),
]
# Each candidate's positive traits. Missing traits are treated as no.
CANDIDATES = {
 'cat':'alive animal pet home', 'dog':'alive animal pet home',
 'goldfish':'alive animal pet water home', 'dolphin':'alive animal wild water large',
 'shark':'alive animal wild water large', 'eagle':'alive animal wild fly',
 'penguin':'alive animal wild water cold', 'elephant':'alive animal wild large',
 'butterfly':'alive animal wild fly', 'horse':'alive animal pet large sport',
 'dragon':'alive animal fictional fly large fantasy famous',
 'unicorn':'alive animal fictional large fantasy famous',
 'tree':'alive nature plant large', 'rose':'alive nature plant',
 'mushroom':'alive nature food', 'cactus':'alive nature plant',
 'pizza':'food round home', 'sushi':'food cold home', 'ice cream':'food cold home',
 'apple':'food nature round home', 'watermelon':'food nature round large',
 'car':'vehicle technology metal', 'bicycle':'vehicle sport metal',
 'airplane':'vehicle technology fly large metal', 'boat':'vehicle water large',
 'rocket':'vehicle technology fly space metal large',
 'smartphone':'technology electric home metal', 'computer':'technology electric home game metal',
 'television':'technology electric home', 'headphones':'technology electric home wear music',
 'guitar':'music home', 'piano':'music home large', 'soccer ball':'sport game round',
 'basketball':'sport game round', 'chessboard':'game home',
 'moon':'nature space round', 'sun':'nature space round large',
 'snowman':'fictional nature cold', 'snowflake':'nature cold',
 'robot':'fictional technology electric metal',
 'wizard':'fictional person famous fantasy', 'vampire':'fictional person famous fantasy',
 'mermaid':'fictional person famous water fantasy',
 'astronaut':'person space wear', 'singer':'person music famous',
 'chef':'person food', 'soccer player':'person sport famous',
 'crown':'wear metal fantasy', 'watch':'technology wear metal',
 'ring':'wear round metal', 'book':'home', 'flower':'alive plant nature',
}
CANDIDATES.update({
 'Mario': 'fictional person famous game',
 'Luigi': 'fictional person famous game',
 'Princess Peach': 'fictional person famous game fantasy',
 'Bowser': 'fictional animal famous game fantasy large',
 'Sonic the Hedgehog': 'fictional animal famous game',
 'Pikachu': 'fictional animal famous game electric pet',
 'Charizard': 'fictional animal famous game fantasy fly large',
 'Kirby': 'fictional famous game round',
 'Link': 'fictional person famous game fantasy',
 'Zelda': 'fictional person famous game fantasy',
 'Master Chief': 'fictional person famous game technology wear',
 'Steve (Minecraft)': 'fictional person famous game',
 'Creeper': 'fictional famous game',
 'Ender Dragon': 'fictional animal famous game fantasy fly large',
 'Lara Croft': 'fictional person famous game',
 'Kratos': 'fictional person famous game fantasy',
 'Pac-Man': 'fictional famous game round food',
 'Donkey Kong': 'fictional animal famous game large',
 'Samus Aran': 'fictional person famous game space technology wear',
 'Cloud Strife': 'fictional person famous game fantasy',
 'Batman': 'fictional person famous wear technology',
 'Superman': 'fictional person famous fly wear space',
 'Spider-Man': 'fictional person famous wear',
 'Wonder Woman': 'fictional person famous fantasy wear',
 'Iron Man': 'fictional person famous technology electric wear fly metal',
 'Hulk': 'fictional person famous large',
 'Thor': 'fictional person famous fantasy',
 'Joker': 'fictional person famous',
 'Harley Quinn': 'fictional person famous',
 'Deadpool': 'fictional person famous wear',
 'Wolverine': 'fictional person famous metal',
 'Darth Vader': 'fictional person famous space fantasy wear technology',
 'Yoda': 'fictional person famous space fantasy',
 'Grogu': 'fictional person famous space fantasy',
 'Chewbacca': 'fictional person famous space',
 'R2-D2': 'fictional famous space technology electric metal',
 'C-3PO': 'fictional famous space technology electric metal',
 'Harry Potter': 'fictional person famous fantasy',
 'Hermione Granger': 'fictional person famous fantasy',
 'Gandalf': 'fictional person famous fantasy',
 'Frodo Baggins': 'fictional person famous fantasy',
 'Gollum': 'fictional person famous fantasy',
 'Elsa (Frozen)': 'fictional person famous fantasy cold',
 'Olaf (Frozen)': 'fictional famous cold',
 'Shrek': 'fictional person famous fantasy large',
 'SpongeBob SquarePants': 'fictional famous water',
 'Patrick Star': 'fictional famous water',
 'Mickey Mouse': 'fictional animal famous',
 'Donald Duck': 'fictional animal famous water',
 'Winnie the Pooh': 'fictional animal famous',
 'Totoro': 'fictional animal famous fantasy large nature',
 'No-Face': 'fictional famous fantasy',
 'Ponyo': 'fictional famous fantasy water',
 'Hello Kitty': 'fictional animal famous',
 'Keroppi': 'fictional animal famous water',
 'Doraemon': 'fictional animal famous technology',
 'Sailor Moon': 'fictional person famous fantasy space wear',
 'Naruto': 'fictional person famous fantasy',
 'Goku': 'fictional person famous fantasy fly',
 'Vegeta': 'fictional person famous fantasy fly',
 'Luffy': 'fictional person famous fantasy water',
 'Pikmin': 'fictional game nature plant',
 'hamster': 'alive animal pet home',
 'rabbit': 'alive animal pet home',
 'parrot': 'alive animal pet fly home',
 'turtle': 'alive animal pet water',
 'frog': 'alive animal wild water',
 'lion': 'alive animal wild large',
 'tiger': 'alive animal wild large',
 'bear': 'alive animal wild large',
 'wolf': 'alive animal wild',
 'fox': 'alive animal wild',
 'giraffe': 'alive animal wild large',
 'zebra': 'alive animal wild large',
 'kangaroo': 'alive animal wild large',
 'koala': 'alive animal wild',
 'octopus': 'alive animal wild water',
 'jellyfish': 'alive animal wild water',
 'whale': 'alive animal wild water large',
 'seal': 'alive animal wild water',
 'owl': 'alive animal wild fly',
 'bee': 'alive animal wild fly',
 'ant': 'alive animal wild',
 'spider': 'alive animal wild',
 'snake': 'alive animal wild',
 'crocodile': 'alive animal wild water large',
 'panda': 'alive animal wild large',
 'deer': 'alive animal wild',
 'cow': 'alive animal large',
 'pig': 'alive animal',
 'chicken': 'alive animal',
 'duck': 'alive animal fly water',
 'banana': 'food nature home',
 'strawberry': 'food nature home',
 'pineapple': 'food nature home',
 'hamburger': 'food home round',
 'hot dog': 'food home',
 'taco': 'food home',
 'ramen': 'food home',
 'kimchi': 'food cold home',
 'bibimbap': 'food home',
 'mochi': 'food round home',
 'donut': 'food round home',
 'cake': 'food home',
 'cookie': 'food round home',
 'chocolate': 'food home',
 'coffee': 'food home',
 'tea': 'food home',
 'milk': 'food cold home',
 'cheese': 'food cold home',
 'egg': 'food round home',
 'popcorn': 'food home',
 'keyboard': 'technology electric home',
 'mouse (computer)': 'technology electric home',
 'laptop': 'technology electric home game',
 'tablet': 'technology electric home',
 'camera': 'technology electric home',
 'printer': 'technology electric home',
 'drone': 'technology electric fly',
 'video game console': 'technology electric game home',
 'smartwatch': 'technology electric wear',
 'refrigerator': 'technology electric home cold large',
 'microwave': 'technology electric home',
 'washing machine': 'technology electric home large',
 'vacuum cleaner': 'technology electric home',
 'light bulb': 'technology electric home',
 'fan': 'technology electric home',
 'electric guitar': 'technology electric music home',
 'microphone': 'technology electric music home',
 'radio': 'technology electric music home',
 'motorcycle': 'vehicle technology metal',
 'bus': 'vehicle technology large metal',
 'train': 'vehicle technology large metal',
 'submarine': 'vehicle water technology metal large',
 'helicopter': 'vehicle fly technology metal',
 'skateboard': 'vehicle sport',
 'scooter': 'vehicle sport',
 'spaceship': 'vehicle technology space fly metal large',
 'hot air balloon': 'vehicle fly large',
 'tractor': 'vehicle technology large metal',
 'sunflower': 'alive nature plant',
 'bamboo': 'alive nature plant',
 'cherry blossom': 'alive nature plant',
 'bonsai tree': 'alive nature plant',
 'oak tree': 'alive nature plant large',
 'palm tree': 'alive nature plant large',
 'seaweed': 'alive nature plant water',
 'grass': 'alive nature plant',
 'venus flytrap': 'alive nature plant',
 'tulip': 'alive nature plant',
 'football': 'sport game round',
 'tennis ball': 'sport game round',
 'baseball': 'sport game round',
 'golf ball': 'sport game round',
 'skis': 'sport cold',
 'snowboard': 'sport cold',
 'surfboard': 'sport water',
 'bicycle helmet': 'sport wear',
 'medal': 'sport wear metal',
 'trophy': 'sport metal',
 'umbrella': 'home',
 'pillow': 'home',
 'blanket': 'home',
 'chair': 'home',
 'table': 'home',
 'bed': 'home large',
 'lamp': 'home electric',
 'mirror': 'home',
 'toothbrush': 'home',
 'backpack': 'wear home',
 'shoes': 'wear home',
 'hat': 'wear home',
 'glasses': 'wear home',
 'jacket': 'wear home',
 'necklace': 'wear metal',
 'earrings': 'wear metal',
 'scissors': 'home metal',
 'spoon': 'home metal',
 'clock': 'home round',
 'key': 'home metal',
 'Mars': 'nature space round',
 'Earth': 'nature space round large',
 'Saturn': 'nature space round large',
 'Jupiter': 'nature space round large',
 'comet': 'nature space cold',
 'asteroid': 'nature space',
 'star': 'nature space',
 'galaxy': 'nature space large',
 'black hole': 'nature space round',
 'spacesuit': 'space wear technology',
})
CANDIDATES={name:set(tags.split()) for name,tags in CANDIDATES.items()}

async def ephemeral_notice(interaction, message, delay=45):
    await interaction.response.send_message(message, ephemeral=True)
    async def cleanup():
        await asyncio.sleep(delay)
        try: await interaction.delete_original_response()
        except discord.HTTPException: pass
    asyncio.create_task(cleanup())

class GuessKnowledge:
    """Persistent, editable offline knowledge base for 20 Questions."""
    def __init__(self, path):
        os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
        self.db = sqlite3.connect(path, timeout=20)
        self.db.execute('PRAGMA busy_timeout=20000')
        self.db.execute('CREATE TABLE IF NOT EXISTS guess_entities (name TEXT PRIMARY KEY, traits TEXT NOT NULL, plays INTEGER NOT NULL DEFAULT 0, wins INTEGER NOT NULL DEFAULT 0)')
        self.db.execute('CREATE TABLE IF NOT EXISTS guess_feedback (id INTEGER PRIMARY KEY AUTOINCREMENT, entity TEXT, guessed TEXT, correct INTEGER, created_at TEXT DEFAULT CURRENT_TIMESTAMP)')
        self.db.execute('CREATE TABLE IF NOT EXISTS guess_traits (key TEXT PRIMARY KEY, question TEXT NOT NULL)')
        for key, question in TRAITS:
            self.db.execute('INSERT OR IGNORE INTO guess_traits(key,question) VALUES (?,?)',(key,question))
        for name, traits in CANDIDATES.items():
            self.db.execute('INSERT OR IGNORE INTO guess_entities(name,traits) VALUES (?,?)',(name,' '.join(sorted(traits))))
        self.db.commit()
    def candidates(self):
        return {name:set(traits.split()) for name,traits in self.db.execute('SELECT name,traits FROM guess_entities')}
    def questions(self):
        return self.db.execute('SELECT key,question FROM guess_traits ORDER BY rowid').fetchall()
    def feedback(self, guessed, correct, actual=None, answers=None):
        self.db.execute('INSERT INTO guess_feedback(entity,guessed,correct) VALUES(?,?,?)',(actual,guessed,int(correct)))
        self.db.execute('UPDATE guess_entities SET plays=plays+1,wins=wins+? WHERE name=?',(int(correct),guessed))
        if actual and not correct and answers:
            name=actual.strip().lower()[:80]
            if name and not any(c in name for c in '@`\n\r'):
                existing=self.db.execute('SELECT traits FROM guess_entities WHERE name=?',(name,)).fetchone()
                if existing is None:
                    # Answers are only evidence for this one game; uncertain answers remain unknown.
                    traits={key for key,val in answers.items() if val>=0.5}
                    self.db.execute('INSERT INTO guess_entities(name,traits) VALUES(?,?)',(name,' '.join(sorted(traits))))
        self.db.commit()

class TeachGuessModal(discord.ui.Modal, title='🌸 Teach Gardener'):
    answer=discord.ui.TextInput(label='What were you thinking of?',placeholder='e.g. Totoro',min_length=2,max_length=80)
    def __init__(self, game):
        super().__init__(); self.game=game
    async def on_submit(self,i):
        self.game.knowledge.feedback(self.game.guess,False,str(self.answer.value),self.game.answers)
        await i.response.send_message('🌱 Thanks! I added that answer to my knowledge base for future games.',ephemeral=True)
        self.game.stop()

class TwentyQuestionsView(discord.ui.View):
    def __init__(self, owner_id, knowledge):
        super().__init__(timeout=600)
        self.owner_id=owner_id; self.knowledge=knowledge
        self.candidates=knowledge.candidates(); self.traits=knowledge.questions()
        self.answers={}; self.asked=[]; self.guess=None
        self.question=self.next_question()
    def scores(self):
        results=[]
        for name,tags in self.candidates.items():
            score=sum((1 if trait in tags else -1)*value for trait,value in self.answers.items())
            results.append((score,name))
        return sorted(results,key=lambda x:(-x[0],x[1]))
    def next_question(self):
        if len(self.asked)>=20 or not self.candidates:
            self.guess=self.scores()[0][1] if self.candidates else 'something new';return None
        ranked=[name for _,name in self.scores()[:min(24,len(self.candidates))]]
        available=[(trait,q) for trait,q in self.traits if trait not in self.asked]
        if not available:
            self.guess=self.scores()[0][1];return None
        trait,q=min(available,key=lambda x:abs(sum(x[0] in self.candidates[n] for n in ranked)-len(ranked)/2))
        self.asked.append(trait)
        return trait,q
    def embed(self):
        desc=(f'Is it **{discord.utils.escape_markdown(self.guess)}**? 🌸\n\nDid I get it right?' if self.guess else f'**Question {len(self.asked)} of 20**\n{self.question[1]}')
        return discord.Embed(title='🌸 Gardener • 20 Questions',description=desc,color=discord.Color.from_rgb(219,151,187))
    async def interaction_check(self,i):
        if i.user.id!=self.owner_id:
            await i.response.send_message('🌸 Start your own game with `/20questions`.',ephemeral=True);return False
        return True
    async def respond(self,i,value):
        if self.guess:
            if value>0:
                self.knowledge.feedback(self.guess,True)
                await i.response.edit_message(content='🌸 I guessed it! Thanks for playing!',embed=None,view=None)
                self.stop()
            else:
                await i.response.send_modal(TeachGuessModal(self))
            return
        self.answers[self.question[0]]=value
        self.question=self.next_question()
        await i.response.edit_message(embed=self.embed(),view=self)
    @discord.ui.button(label='Yes',style=discord.ButtonStyle.success,row=0)
    async def yes(self,i,b):await self.respond(i,1)
    @discord.ui.button(label='Probably',style=discord.ButtonStyle.primary,row=0)
    async def probably(self,i,b):await self.respond(i,.5)
    @discord.ui.button(label='Not sure',style=discord.ButtonStyle.secondary,row=0)
    async def unsure(self,i,b):await self.respond(i,0)
    @discord.ui.button(label='Probably not',style=discord.ButtonStyle.secondary,row=1)
    async def probably_not(self,i,b):await self.respond(i,-.5)
    @discord.ui.button(label='No',style=discord.ButtonStyle.danger,row=1)
    async def no(self,i,b):await self.respond(i,-1)

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
        await ephemeral_notice(i,'🌸 Room is now public.' if private else '🔒 Room is now private.')
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
    @discord.ui.button(label='Dismiss',emoji='✖️',style=discord.ButtonStyle.secondary,row=2)
    async def dismiss(self,i,b):
        await i.response.edit_message(content='🌸 Panel dismissed.',view=None)

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
        await ephemeral_notice(i,'Join the configured **Create a Garden** voice lobby. Gardener creates a temporary room for you. Use **Manage My Room** to customize it. Empty rooms disappear automatically.')

class Gardener(commands.Cog):
    def __init__(self,bot,db_path):
        self.bot=bot
        self.db=sqlite3.connect(db_path,timeout=20)
        self.guess_knowledge=GuessKnowledge(os.getenv('GARDENER_QUESTIONS_DATABASE_PATH',os.path.join(os.path.dirname(os.path.abspath(db_path)),'gardener_questions.sqlite3')))
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
    @app_commands.command(name='20questions',description='Play an Akinator-style guessing game (up to 20 questions)')
    async def twentyquestions(self,i:discord.Interaction):
        view=TwentyQuestionsView(i.user.id,self.guess_knowledge)
        await i.response.send_message(embed=view.embed(),view=view,ephemeral=True)
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
                try:
                    await room.send(embed=discord.Embed(
                        title='🌸 Welcome to your Garden',
                        description=f'{member.mention}, this is your private voice-room control panel. Use **Manage My Room** to change settings. This message is in the voice channel chat.',
                        color=discord.Color.from_rgb(219,151,187)),
                        view=PanelView(self),
                        allowed_mentions=discord.AllowedMentions(users=True,roles=False,everyone=False))
                except (discord.HTTPException,AttributeError) as exc:
                    logger.warning('Could not post panel in voice chat for room %s: %s',room.id,exc)
            except discord.HTTPException as exc:
                logger.exception('Could not create/move Gardener room: %s',exc)
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
