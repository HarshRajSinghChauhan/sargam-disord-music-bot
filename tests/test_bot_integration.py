import asyncio
import unittest
from unittest.mock import AsyncMock, MagicMock, patch
import discord
from bot import MusicBot
from utils.database import db


class TestBotIntegration(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.bot = MusicBot()
        await db.init_db()

    async def asyncTearDown(self):
        await self.bot.close()

    async def test_extension_loading_and_command_tree(self):
        # Load cogs
        await self.bot.load_extension('cogs.music')
        await self.bot.load_extension('cogs.joinsound')

        # Check cogs are loaded
        self.assertIn('Music', self.bot.cogs)
        self.assertIn('JoinSound', self.bot.cogs)

        # Inspect commands in tree
        commands = [cmd.name for cmd in self.bot.tree.get_commands()]

        expected_music_commands = [
            'play', 'skip', 'pause', 'resume', 'stop',
            'queue', 'nowplaying', 'remove', 'clear',
            'shuffle', 'volume', 'loop'
        ]
        for cmd in expected_music_commands:
            self.assertIn(cmd, commands, f"Music command {cmd} missing from command tree")

        expected_joinsound_commands = [
            'setjoinsound', 'removejoinsound', 'myjoinsound',
            'joinsounds', 'testjoinsound', 'joinsoundconfig'
        ]
        for cmd in expected_joinsound_commands:
            self.assertIn(cmd, commands, f"JoinSound command {cmd} missing from command tree")

    async def test_voice_state_ignore_bots(self):
        await self.bot.load_extension('cogs.music')
        await self.bot.load_extension('cogs.joinsound')
        joinsound_cog = self.bot.get_cog('JoinSound')

        bot_member = MagicMock(spec=discord.Member)
        bot_member.bot = True

        before = MagicMock(spec=discord.VoiceState)
        after = MagicMock(spec=discord.VoiceState)
        after.channel = MagicMock(spec=discord.VoiceChannel)

        # Should return immediately without querying db or connecting
        await joinsound_cog.on_voice_state_update(bot_member, before, after)
        self.assertEqual(len(joinsound_cog.cooldowns), 0)


if __name__ == '__main__':
    unittest.main()
