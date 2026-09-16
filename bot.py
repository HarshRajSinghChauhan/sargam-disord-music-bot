import discord
from discord.ext import commands
import os
from dotenv import load_dotenv
import asyncio

load_dotenv()

TOKEN = os.getenv('DISCORD_TOKEN')
TEST_GUILD_ID = os.getenv('TEST_GUILD_ID')

class MusicBot(commands.Bot):
    def __init__(self):
        intents = discord.Intents.default()
        intents.message_content = True
        intents.members = True
        
        super().__init__(
            command_prefix=commands.when_mentioned_or('!'), 
            intents=intents,
            help_command=None # Using slash commands instead
        )

    async def setup_hook(self):
        # Load extensions
        await self.load_extension('cogs.music')
        print("Loaded extension: cogs.music")

        # Sync slash commands
        if TEST_GUILD_ID:
            guild = discord.Object(id=int(TEST_GUILD_ID))
            self.tree.copy_global_to(guild=guild)
            await self.tree.sync(guild=guild)
            print(f"Synced slash commands to test guild {TEST_GUILD_ID}")
        else:
            await self.tree.sync()
            print("Synced slash commands globally (this may take up to an hour to propagate in Discord)")

    async def on_ready(self):
        print(f'Logged in as {self.user} (ID: {self.user.id})')
        print('------')

bot = MusicBot()

if __name__ == '__main__':
    if not TOKEN or TOKEN == "your_bot_token_here":
        print("Error: DISCORD_TOKEN is not set. Please configure your .env file.")
    else:
        bot.run(TOKEN)
