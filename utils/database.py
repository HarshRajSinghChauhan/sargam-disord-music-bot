import os
import sqlite3
import asyncio
from datetime import datetime
from typing import Optional, List, Dict, Any

DB_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'data')
DB_PATH = os.path.join(DB_DIR, 'sargam.db')
SOUNDS_DIR = os.path.join(DB_DIR, 'joinsounds')


class Database:
    def __init__(self, db_path: str = DB_PATH):
        self.db_path = db_path
        self._ensure_dirs()

    def _ensure_dirs(self):
        os.makedirs(os.path.dirname(self.db_path), exist_ok=True)
        os.makedirs(SOUNDS_DIR, exist_ok=True)

    def _get_connection(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        return conn

    def _init_db_sync(self):
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS join_sounds (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    guild_id INTEGER NOT NULL,
                    user_id INTEGER NOT NULL,
                    sound_path TEXT NOT NULL,
                    sound_name TEXT NOT NULL,
                    volume INTEGER NOT NULL DEFAULT 50,
                    enabled INTEGER NOT NULL DEFAULT 1,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    UNIQUE(guild_id, user_id)
                )
            """)
            cursor.execute("""
                CREATE INDEX IF NOT EXISTS idx_join_sounds_guild_user 
                ON join_sounds(guild_id, user_id)
            """)
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS guild_settings (
                    guild_id INTEGER PRIMARY KEY,
                    cooldown_seconds INTEGER NOT NULL DEFAULT 30,
                    duck_volume REAL NOT NULL DEFAULT 0.25,
                    auto_connect INTEGER NOT NULL DEFAULT 1,
                    enabled INTEGER NOT NULL DEFAULT 1
                )
            """)
            conn.commit()

    async def init_db(self):
        await asyncio.to_thread(self._init_db_sync)

    def _get_join_sound_sync(self, guild_id: int, user_id: int) -> Optional[Dict[str, Any]]:
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                "SELECT * FROM join_sounds WHERE guild_id = ? AND user_id = ?",
                (guild_id, user_id)
            )
            row = cursor.fetchone()
            if row:
                return dict(row)
            return None

    async def get_join_sound(self, guild_id: int, user_id: int) -> Optional[Dict[str, Any]]:
        return await asyncio.to_thread(self._get_join_sound_sync, guild_id, user_id)

    def _set_join_sound_sync(self, guild_id: int, user_id: int, sound_path: str, sound_name: str, volume: int = 50, enabled: bool = True) -> Optional[str]:
        """
        Upserts the join sound for a given user in a guild.
        Returns the previous sound_path if replaced, or None.
        """
        now = datetime.utcnow().isoformat()
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                "SELECT sound_path FROM join_sounds WHERE guild_id = ? AND user_id = ?",
                (guild_id, user_id)
            )
            row = cursor.fetchone()
            old_path = row['sound_path'] if row else None

            cursor.execute("""
                INSERT INTO join_sounds (guild_id, user_id, sound_path, sound_name, volume, enabled, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(guild_id, user_id) DO UPDATE SET
                    sound_path = excluded.sound_path,
                    sound_name = excluded.sound_name,
                    volume = excluded.volume,
                    enabled = excluded.enabled,
                    updated_at = excluded.updated_at
            """, (guild_id, user_id, sound_path, sound_name, volume, 1 if enabled else 0, now, now))
            conn.commit()
            return old_path

    async def set_join_sound(self, guild_id: int, user_id: int, sound_path: str, sound_name: str, volume: int = 50, enabled: bool = True) -> Optional[str]:
        return await asyncio.to_thread(self._set_join_sound_sync, guild_id, user_id, sound_path, sound_name, volume, enabled)

    def _remove_join_sound_sync(self, guild_id: int, user_id: int) -> Optional[str]:
        """
        Deletes the join sound for a user in a guild.
        Returns the removed sound_path if found, or None.
        """
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                "SELECT sound_path FROM join_sounds WHERE guild_id = ? AND user_id = ?",
                (guild_id, user_id)
            )
            row = cursor.fetchone()
            if not row:
                return None
            old_path = row['sound_path']
            cursor.execute(
                "DELETE FROM join_sounds WHERE guild_id = ? AND user_id = ?",
                (guild_id, user_id)
            )
            conn.commit()
            return old_path

    async def remove_join_sound(self, guild_id: int, user_id: int) -> Optional[str]:
        return await asyncio.to_thread(self._remove_join_sound_sync, guild_id, user_id)

    def _list_guild_join_sounds_sync(self, guild_id: int) -> List[Dict[str, Any]]:
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                "SELECT * FROM join_sounds WHERE guild_id = ? ORDER BY user_id ASC",
                (guild_id,)
            )
            return [dict(row) for row in cursor.fetchall()]

    async def list_guild_join_sounds(self, guild_id: int) -> List[Dict[str, Any]]:
        return await asyncio.to_thread(self._list_guild_join_sounds_sync, guild_id)

    def _get_guild_settings_sync(self, guild_id: int) -> Dict[str, Any]:
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM guild_settings WHERE guild_id = ?", (guild_id,))
            row = cursor.fetchone()
            if row:
                return dict(row)
            # Default settings
            return {
                'guild_id': guild_id,
                'cooldown_seconds': 30,
                'duck_volume': 0.25,
                'auto_connect': 1,
                'enabled': 1
            }

    async def get_guild_settings(self, guild_id: int) -> Dict[str, Any]:
        return await asyncio.to_thread(self._get_guild_settings_sync, guild_id)

    def _set_guild_settings_sync(
        self,
        guild_id: int,
        cooldown_seconds: Optional[int] = None,
        duck_volume: Optional[float] = None,
        auto_connect: Optional[bool] = None,
        enabled: Optional[bool] = None
    ) -> Dict[str, Any]:
        current = self._get_guild_settings_sync(guild_id)
        new_cooldown = cooldown_seconds if cooldown_seconds is not None else current['cooldown_seconds']
        new_duck = duck_volume if duck_volume is not None else current['duck_volume']
        new_auto = (1 if auto_connect else 0) if auto_connect is not None else current['auto_connect']
        new_enabled = (1 if enabled else 0) if enabled is not None else current['enabled']

        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                INSERT INTO guild_settings (guild_id, cooldown_seconds, duck_volume, auto_connect, enabled)
                VALUES (?, ?, ?, ?, ?)
                ON CONFLICT(guild_id) DO UPDATE SET
                    cooldown_seconds = excluded.cooldown_seconds,
                    duck_volume = excluded.duck_volume,
                    auto_connect = excluded.auto_connect,
                    enabled = excluded.enabled
            """, (guild_id, new_cooldown, new_duck, new_auto, new_enabled))
            conn.commit()

        return {
            'guild_id': guild_id,
            'cooldown_seconds': new_cooldown,
            'duck_volume': new_duck,
            'auto_connect': new_auto,
            'enabled': new_enabled
        }

    async def set_guild_settings(
        self,
        guild_id: int,
        cooldown_seconds: Optional[int] = None,
        duck_volume: Optional[float] = None,
        auto_connect: Optional[bool] = None,
        enabled: Optional[bool] = None
    ) -> Dict[str, Any]:
        return await asyncio.to_thread(
            self._set_guild_settings_sync,
            guild_id,
            cooldown_seconds,
            duck_volume,
            auto_connect,
            enabled
        )

# Global singleton database instance
db = Database()
