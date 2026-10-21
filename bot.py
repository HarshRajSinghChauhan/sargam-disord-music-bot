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
NODE_NAME = os.getenv('BOT_NODE', 'cloud').strip().lower()

_web_server_started = False

async def handle_healthcheck(request):
    node_info = "Laptop (Local Home Wi-Fi)" if NODE_NAME == 'laptop' else "Cloud (Render)"
    return web.Response(text=f"Discord Music Bot is online and running! Node: {node_info}")

async def start_web_server():
    app = web.Application()
    app.router.add_get('/', handle_healthcheck)
    app.router.add_get('/health', handle_healthcheck)
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, '0.0.0.0', PORT)
    await site.start()
    print(f"Health check web server running on port {PORT}")

async def ensure_web_server_started():
    global _web_server_started
    if not _web_server_started:
        try:
            await start_web_server()
            _web_server_started = True
        except Exception as e:
            print(f"[Web Server Notice] Port {PORT} status: {e}")

class MusicBot(commands.Bot):
    def __init__(self):
        intents = discord.Intents.default()
        intents.message_content = True
        intents.members = True
        
        super().__init__(
            command_prefix=commands.when_mentioned_or('!'), 
            intents=intents,
            help_command=None
        )

    async def setup_hook(self):
        # Initialize database
        from utils.database import db
        await db.init_db()

        # Load extensions
        await self.load_extension('cogs.music')
        print("Loaded extension: cogs.music")
        await self.load_extension('cogs.joinsound')
        print("Loaded extension: cogs.joinsound")
        await self.load_extension('cogs.soundboard')
        print("Loaded extension: cogs.soundboard")

        # Sync slash commands
        if TEST_GUILD_ID:
            guild = discord.Object(id=int(TEST_GUILD_ID))
            self.tree.copy_global_to(guild=guild)
            await self.tree.sync(guild=guild)
            print(f"Synced slash commands to test guild {TEST_GUILD_ID}")
        else:
            await self.tree.sync()
            print("Synced slash commands globally")

    async def on_ready(self):
        node_display = "LAPTOP (Direct Wi-Fi - No Proxies)" if NODE_NAME == 'laptop' else "CLOUD (Render 24/7)"
        print(f'Logged in as {self.user} (ID: {self.user.id}) [{node_display}]')
        print('------')


async def run_laptop_node():
    from utils.database import db
    await db.init_db()
    
    print("[Cluster] Announcing Laptop node to database...", flush=True)
    await db.update_heartbeat('laptop')
    
    print("[Cluster] Waiting 3 seconds for Cloud (Render) instance to yield connection...", flush=True)
    await asyncio.sleep(3)
    
    bot = MusicBot()
    heartbeat_running = True
    
    async def heartbeat_loop():
        while heartbeat_running:
            try:
                await db.update_heartbeat('laptop')
            except Exception as e:
                print(f"[Cluster Heartbeat Warning] {e}", flush=True)
            await asyncio.sleep(5)
            
    hb_task = asyncio.create_task(heartbeat_loop())
    
    try:
        await bot.start(TOKEN)
    finally:
        heartbeat_running = False
        hb_task.cancel()
        print("[Cluster] Clearing Laptop heartbeat from database...", flush=True)
        try:
            await db.clear_heartbeat('laptop')
        except Exception:
            pass
        if not bot.is_closed():
            await bot.close()
        print("[Cluster] Laptop shut down cleanly. Cloud (Render) will take over.", flush=True)


async def run_cloud_node():
    from utils.database import db
    
    # 1. Start web server for Render health checks (runs continuously)
    await ensure_web_server_started()
    
    # 2. Init DB
    await db.init_db()
    print("[Cluster] Cloud (Render) supervisor active.", flush=True)
    
    while True:
        # Check if laptop is currently active
        laptop_active = await db.is_node_active('laptop', timeout_seconds=45)
        if laptop_active:
            print("[Cluster] Laptop is currently ACTIVE. Render entering STANDBY mode...", flush=True)
            inactive_count = 0
            while True:
                await asyncio.sleep(5)
                active = await db.is_node_active('laptop', timeout_seconds=45)
                if not active:
                    inactive_count += 1
                    # Require 3 consecutive inactive checks (15s buffer after 45s timeout = 60s total)
                    if inactive_count >= 3:
                        print("[Cluster] Laptop confirmed OFFLINE. Render taking over Discord bot...", flush=True)
                        break
                else:
                    inactive_count = 0
            
        bot = MusicBot()
        bot_task = asyncio.create_task(bot.start(TOKEN))
        
        while not bot.is_closed():
            await asyncio.sleep(5)
            if await db.is_node_active('laptop', timeout_seconds=45):
                print("[Cluster] Laptop became ACTIVE! Render yielding Discord connection...", flush=True)
                await bot.close()
                break
                
        try:
            await bot_task
        except asyncio.CancelledError:
            pass
        except Exception as e:
            print(f"[Cluster Supervisor] Bot session ended: {e}", flush=True)
            
        await asyncio.sleep(2)


async def main():
    if not TOKEN or TOKEN == "your_bot_token_here":
        print("Error: DISCORD_TOKEN is not set. Please configure your .env file.")
        return

    if NODE_NAME == 'laptop':
        await run_laptop_node()
    else:
        await run_cloud_node()

if __name__ == '__main__':
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\nBot process terminated by user.")


