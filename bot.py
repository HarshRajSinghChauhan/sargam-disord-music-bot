import discord
from discord.ext import commands
import os
from dotenv import load_dotenv
import asyncio
from aiohttp import web

load_dotenv()

TOKEN = os.getenv('DISCORD_TOKEN')
TEST_GUILD_ID = os.getenv('TEST_GUILD_ID')
PORT = int(os.getenv('PORT', 8080))

async def handle_healthcheck(request):
    return web.Response(text="Discord Music Bot is online and running!")

async def start_web_server():
    app = web.Application()
    app.router.add_get('/', handle_healthcheck)
    app.router.add_get('/health', handle_healthcheck)
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, '0.0.0.0', PORT)
    await site.start()
    print(f"Health check web server running on port {PORT}")

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
        # Start health check web server in background
        asyncio.create_task(start_web_server())

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

