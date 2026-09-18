import os
import sqlite3
import asyncio
import logging
from datetime import datetime
from typing import Optional, List, Dict, Any

logger = logging.getLogger('sargam.database')

DB_DIR = os.getenv('DATA_DIR', os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'data'))
DB_PATH = os.path.join(DB_DIR, 'sargam.db')
SOUNDS_DIR = os.path.join(DB_DIR, 'joinsounds')


class Database:
    def __init__(self, db_path: str = DB_PATH, dsn: Optional[str] = None):
        self.db_path = db_path
        self.dsn = dsn or os.getenv('DATABASE_URL')
        if self.dsn and self.dsn.startswith('postgres://'):
            self.dsn = 'postgresql://' + self.dsn[11:]
        self.is_postgres = bool(self.dsn)
        self.pool = None
        self._ensure_dirs()

    def _ensure_dirs(self):
        os.makedirs(os.path.dirname(self.db_path), exist_ok=True)
        os.makedirs(SOUNDS_DIR, exist_ok=True)

    # ==================== INITIALIZATION & MIGRATIONS ====================

    async def init_db(self):
        self._ensure_dirs()
        if self.is_postgres:
            try:
                import asyncpg
                self.pool = await asyncpg.create_pool(self.dsn, min_size=1, max_size=10)
                async with self.pool.acquire() as conn:
                    await conn.execute("""
                        CREATE TABLE IF NOT EXISTS join_sounds (
                            id SERIAL PRIMARY KEY,
                            guild_id BIGINT NOT NULL,
                            user_id BIGINT NOT NULL,
                            sound_name TEXT NOT NULL,
                            audio_data BYTEA NOT NULL,
                            volume INTEGER NOT NULL DEFAULT 50,
                            enabled INTEGER NOT NULL DEFAULT 1,
                            created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
                            updated_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
                            UNIQUE(guild_id, user_id)
                        );
                        CREATE INDEX IF NOT EXISTS idx_join_sounds_guild_user 
                        ON join_sounds(guild_id, user_id);

                        CREATE TABLE IF NOT EXISTS guild_settings (
                            guild_id BIGINT PRIMARY KEY,
                            cooldown_seconds INTEGER NOT NULL DEFAULT 30,
                            duck_volume REAL NOT NULL DEFAULT 0.25,
                            auto_connect INTEGER NOT NULL DEFAULT 1,
                            enabled INTEGER NOT NULL DEFAULT 1
                        );
                    """)
                logger.info("Connected to Neon / PostgreSQL and verified schema.")
                return
            except Exception as e:
                logger.error(f"Failed to connect to PostgreSQL ({e}). Falling back to local SQLite.")
                self.is_postgres = False

        # SQLite Fallback
        await asyncio.to_thread(self._init_sqlite_sync)
        logger.info(f"Initialized local SQLite database at {self.db_path}.")

    def _get_sqlite_connection(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        return conn

    def _init_sqlite_sync(self):
        with self._get_sqlite_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS join_sounds (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    guild_id INTEGER NOT NULL,
                    user_id INTEGER NOT NULL,
                    sound_name TEXT NOT NULL,
                    audio_data BLOB,
                    sound_path TEXT,
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

    # ==================== AUDIO CACHE HELPER ====================

    def _ensure_local_audio_file(self, guild_id: int, user_id: int, sound_name: str, audio_data: bytes) -> str:
        """
        Ensures the audio bytes are written to a local file in SOUNDS_DIR
        so FFmpeg can stream it reliably. Survives ephemeral restarts by recreating on demand.
        """
        guild_dir = os.path.join(SOUNDS_DIR, str(guild_id))
        os.makedirs(guild_dir, exist_ok=True)
        ext = os.path.splitext(sound_name)[1].lower()
        if not ext:
            ext = ".mp3"
        cache_path = os.path.join(guild_dir, f"{user_id}_{sound_name}")
        
        # Write only if file doesn't exist or is empty
        if not os.path.exists(cache_path) or os.path.getsize(cache_path) == 0:
            with open(cache_path, 'wb') as f:
                f.write(audio_data)
        return cache_path

    # ==================== JOIN SOUNDS CRUD ====================

    async def get_join_sound(self, guild_id: int, user_id: int) -> Optional[Dict[str, Any]]:
        """
        Retrieves join sound config for a user and ensures audio file exists on disk.
        """
        if self.is_postgres and self.pool:
            async with self.pool.acquire() as conn:
                row = await conn.fetchrow(
                    "SELECT guild_id, user_id, sound_name, audio_data, volume, enabled FROM join_sounds WHERE guild_id = $1 AND user_id = $2",
                    int(guild_id), int(user_id)
                )
                if not row:
                    return None
                data = dict(row)
                sound_path = self._ensure_local_audio_file(guild_id, user_id, data['sound_name'], data['audio_data'])
                data['sound_path'] = sound_path
                return data

        # SQLite
        def _get():
            with self._get_sqlite_connection() as conn:
                cursor = conn.cursor()
                cursor.execute(
                    "SELECT * FROM join_sounds WHERE guild_id = ? AND user_id = ?",
                    (guild_id, user_id)
                )
                row = cursor.fetchone()
                if not row:
                    return None
                data = dict(row)
                if data.get('audio_data'):
                    data['sound_path'] = self._ensure_local_audio_file(guild_id, user_id, data['sound_name'], data['audio_data'])
                return data

        return await asyncio.to_thread(_get)

    async def set_join_sound(
        self,
        guild_id: int,
        user_id: int,
        sound_name: str,
        audio_data: bytes,
        volume: int = 50,
        enabled: bool = True
    ) -> str:
        """
        Saves or updates join sound directly in the database (BYTEA/BLOB) and local cache.
        Returns the local path to the cached audio file.
        """
        local_path = self._ensure_local_audio_file(guild_id, user_id, sound_name, audio_data)

        if self.is_postgres and self.pool:
            now = datetime.utcnow()
            async with self.pool.acquire() as conn:
                await conn.execute("""
                    INSERT INTO join_sounds (guild_id, user_id, sound_name, audio_data, volume, enabled, created_at, updated_at)
                    VALUES ($1, $2, $3, $4, $5, $6, $7, $7)
                    ON CONFLICT(guild_id, user_id) DO UPDATE SET
                        sound_name = EXCLUDED.sound_name,
                        audio_data = EXCLUDED.audio_data,
                        volume = EXCLUDED.volume,
                        enabled = EXCLUDED.enabled,
                        updated_at = EXCLUDED.updated_at
                """, int(guild_id), int(user_id), sound_name, audio_data, volume, 1 if enabled else 0, now)
            return local_path

        # SQLite
        def _set():
            now = datetime.utcnow().isoformat()
            with self._get_sqlite_connection() as conn:
                cursor = conn.cursor()
                cursor.execute("""
                    INSERT INTO join_sounds (guild_id, user_id, sound_name, audio_data, sound_path, volume, enabled, created_at, updated_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                    ON CONFLICT(guild_id, user_id) DO UPDATE SET
                        sound_name = excluded.sound_name,
                        audio_data = excluded.audio_data,
                        sound_path = excluded.sound_path,
                        volume = excluded.volume,
                        enabled = excluded.enabled,
                        updated_at = excluded.updated_at
                """, (guild_id, user_id, sound_name, audio_data, local_path, volume, 1 if enabled else 0, now, now))
                conn.commit()

        await asyncio.to_thread(_set)
        return local_path

    async def remove_join_sound(self, guild_id: int, user_id: int) -> bool:
        """
        Deletes join sound from database and deletes local cached audio file.
        """
        sound = await self.get_join_sound(guild_id, user_id)
        if not sound:
            return False

        if sound.get('sound_path') and os.path.exists(sound['sound_path']):
            try:
                os.remove(sound['sound_path'])
            except Exception:
                pass

        if self.is_postgres and self.pool:
            async with self.pool.acquire() as conn:
                await conn.execute(
                    "DELETE FROM join_sounds WHERE guild_id = $1 AND user_id = $2",
                    int(guild_id), int(user_id)
                )
            return True

        def _remove():
            with self._get_sqlite_connection() as conn:
                cursor = conn.cursor()
                cursor.execute("DELETE FROM join_sounds WHERE guild_id = ? AND user_id = ?", (guild_id, user_id))
                conn.commit()

        await asyncio.to_thread(_remove)
        return True

    async def list_guild_join_sounds(self, guild_id: int) -> List[Dict[str, Any]]:
        """
        Lists all join sound configs for a guild.
        """
        if self.is_postgres and self.pool:
            async with self.pool.acquire() as conn:
                rows = await conn.fetch(
                    "SELECT guild_id, user_id, sound_name, volume, enabled FROM join_sounds WHERE guild_id = $1 ORDER BY user_id ASC",
                    int(guild_id)
                )
                return [dict(r) for r in rows]

        def _list():
            with self._get_sqlite_connection() as conn:
                cursor = conn.cursor()
                cursor.execute(
                    "SELECT guild_id, user_id, sound_name, volume, enabled FROM join_sounds WHERE guild_id = ? ORDER BY user_id ASC",
                    (guild_id,)
                )
                return [dict(row) for row in cursor.fetchall()]

        return await asyncio.to_thread(_list)

    # ==================== GUILD SETTINGS ====================

    async def get_guild_settings(self, guild_id: int) -> Dict[str, Any]:
        defaults = {
            'guild_id': guild_id,
            'cooldown_seconds': 30,
            'duck_volume': 0.25,
            'auto_connect': 1,
            'enabled': 1
        }

        if self.is_postgres and self.pool:
            async with self.pool.acquire() as conn:
                row = await conn.fetchrow(
                    "SELECT * FROM guild_settings WHERE guild_id = $1",
                    int(guild_id)
                )
                if row:
                    return dict(row)
                return defaults

        def _get():
            with self._get_sqlite_connection() as conn:
                cursor = conn.cursor()
                cursor.execute("SELECT * FROM guild_settings WHERE guild_id = ?", (guild_id,))
                row = cursor.fetchone()
                if row:
                    return dict(row)
                return defaults

        return await asyncio.to_thread(_get)

    async def set_guild_settings(
        self,
        guild_id: int,
        cooldown_seconds: Optional[int] = None,
        duck_volume: Optional[float] = None,
        auto_connect: Optional[bool] = None,
        enabled: Optional[bool] = None
    ) -> Dict[str, Any]:
        current = await self.get_guild_settings(guild_id)
        new_cooldown = cooldown_seconds if cooldown_seconds is not None else current['cooldown_seconds']
        new_duck = duck_volume if duck_volume is not None else current['duck_volume']
        new_auto = (1 if auto_connect else 0) if auto_connect is not None else current['auto_connect']
        new_enabled = (1 if enabled else 0) if enabled is not None else current['enabled']

        if self.is_postgres and self.pool:
            async with self.pool.acquire() as conn:
                await conn.execute("""
                    INSERT INTO guild_settings (guild_id, cooldown_seconds, duck_volume, auto_connect, enabled)
                    VALUES ($1, $2, $3, $4, $5)
                    ON CONFLICT(guild_id) DO UPDATE SET
                        cooldown_seconds = EXCLUDED.cooldown_seconds,
                        duck_volume = EXCLUDED.duck_volume,
                        auto_connect = EXCLUDED.auto_connect,
                        enabled = EXCLUDED.enabled
                """, int(guild_id), new_cooldown, new_duck, new_auto, new_enabled)
            return {
                'guild_id': guild_id,
                'cooldown_seconds': new_cooldown,
                'duck_volume': new_duck,
                'auto_connect': new_auto,
                'enabled': new_enabled
            }

        def _set():
            with self._get_sqlite_connection() as conn:
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

        await asyncio.to_thread(_set)
        return {
            'guild_id': guild_id,
            'cooldown_seconds': new_cooldown,
            'duck_volume': new_duck,
            'auto_connect': new_auto,
            'enabled': new_enabled
        }


# Global singleton instance
db = Database()
