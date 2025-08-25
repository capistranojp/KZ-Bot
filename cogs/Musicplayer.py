import discord
from discord.ext import commands, tasks
import asyncio
from async_timeout import timeout
import yt_dlp as youtube_dl
import lyricsgenius
import os
import re
import spotipy
from spotipy.oauth2 import SpotifyClientCredentials
import random

# ==========================
# CONFIG
# ==========================
FFMPEG_PATH = r"C:\Users\Administrator\AppData\Local\Microsoft\WinGet\Links\ffmpeg.exe"
DEFAULT_COLOR = 0x4c00b0

GENIUS_TOKEN = os.getenv("GENIUS_TOKEN")
genius = lyricsgenius.Genius(GENIUS_TOKEN) if GENIUS_TOKEN else None

SPOTIFY_CLIENT_ID = os.getenv("SPOTIFY_CLIENT_ID")
SPOTIFY_CLIENT_SECRET = os.getenv("SPOTIFY_CLIENT_SECRET")
spotify = spotipy.Spotify(auth_manager=SpotifyClientCredentials(client_id=SPOTIFY_CLIENT_ID, client_secret=SPOTIFY_CLIENT_SECRET))

SPOTIFY_TRACK_RE = re.compile(r"https?://open\.spotify\.com/track/([a-zA-Z0-9]+)")
SPOTIFY_PLAYLIST_RE = re.compile(r"https?://open\.spotify\.com/playlist/([a-zA-Z0-9]+)")

ytdlopts = {
    "format": "bestaudio/best",
    "quiet": True,
    "nocheckcertificate": True,
    "ignoreerrors": False,
    "logtostderr": False,
    "default_search": "ytsearch",
    "source_address": "0.0.0.0"
}
ytdl = youtube_dl.YoutubeDL(ytdlopts)

ffmpeg_opts = {
    "before_options": "-reconnect 1 -reconnect_streamed 1 -reconnect_delay_max 5",
    "options": "-vn",
    "executable": FFMPEG_PATH,
}

# ==========================
# Helper Functions
# ==========================
def is_spotify_link(url: str) -> bool:
    return "open.spotify.com" in url

async def fetch_youtube_links_from_spotify(spotify_url: str):
    """
    Converts Spotify playlist/track to a list of YouTube search strings.
    """
    urls = []

    if SPOTIFY_TRACK_RE.match(spotify_url):
        track_id = SPOTIFY_TRACK_RE.match(spotify_url).group(1)
        track = spotify.track(track_id)
        urls.append(f"{track['name']} {track['artists'][0]['name']}")
    elif SPOTIFY_PLAYLIST_RE.match(spotify_url):
        playlist_id = SPOTIFY_PLAYLIST_RE.match(spotify_url).group(1)
        playlist = spotify.playlist_tracks(playlist_id)
        for item in playlist['items']:
            track = item['track']
            urls.append(f"{track['name']} {track['artists'][0]['name']}")
    return urls

# ==========================
# YTDL Source
# ==========================
class YTDLSource(discord.PCMVolumeTransformer):
    def __init__(self, source, *, data, volume=0.5):
        super().__init__(source, volume)
        self.data = data
        self.title = data.get("title")
        self.url = data.get("webpage_url")
        self.thumbnail = data.get("thumbnail") or ""
        self.duration = data.get("duration") or 0
        self.uploader = data.get("uploader") or ""

    @classmethod
    async def create_source(cls, search: str, *, loop, volume=0.5):
        loop = loop or asyncio.get_event_loop()
        data = await loop.run_in_executor(None, lambda: ytdl.extract_info(search, download=False))
        if "entries" in data:
            data = data["entries"][0]
        return cls(discord.FFmpegPCMAudio(data["url"], **ffmpeg_opts), data=data, volume=volume)

# ==========================
# Music Player
# ==========================
class MusicPlayer:
    def __init__(self, ctx):
        self.bot = ctx.bot
        self._guild = ctx.guild
        self._channel = ctx.channel
        self.queue = asyncio.Queue()
        self.next = asyncio.Event()
        self.volume = 0.5
        self.current = None
        self.loop_mode = "off"  # off | one | all
        self.np_msg = None

        self.bot.loop.create_task(self.player_loop())

    async def player_loop(self):
        await self.bot.wait_until_ready()
        while not self.bot.is_closed():
            self.next.clear()
            try:
                async with timeout(300):
                    source = await self.queue.get()
            except asyncio.TimeoutError:
                if self._guild.voice_client:
                    await self._guild.voice_client.disconnect()
                return

            self.current = source
            self._guild.voice_client.play(
                source,
                after=lambda e: self.bot.loop.call_soon_threadsafe(self.next.set)
            )

            # Now playing embed
            embed = discord.Embed(
                title=f"🎶 Now Playing - {source.title}",
                description=f"[{source.title}]({source.url})",
                color=DEFAULT_COLOR
            )
            embed.set_author(name=self.bot.user.name, icon_url=self.bot.user.display_avatar.url)
            embed.set_thumbnail(url=source.thumbnail)
            embed.add_field(name="Uploader", value=source.uploader)
            embed.add_field(name="Duration", value=f"{source.duration // 60}:{source.duration % 60:02}")
            embed.set_footer(text="Made by Isho")

            view = NowPlayingButtons(self)
            if self.np_msg:
                try: await self.np_msg.delete()
                except: pass
            self.np_msg = await self._channel.send(embed=embed, view=view)

            await self.next.wait()
            finished = self.current
            self.current = None

            if self.loop_mode == "one":
                repeat_src = await YTDLSource.create_source(finished.url, loop=self.bot.loop, volume=self.volume)
                self.queue._queue.appendleft(repeat_src)
            elif self.loop_mode == "all":
                repeat_src = await YTDLSource.create_source(finished.url, loop=self.bot.loop, volume=self.volume)
                await self.queue.put(repeat_src)

            finished.cleanup()

# ==========================
# Buttons
# ==========================
class NowPlayingButtons(discord.ui.View):
    def __init__(self, player):
        super().__init__(timeout=None)
        self.player = player

    @discord.ui.button(label="⏭ Skip", style=discord.ButtonStyle.green)
    async def skip(self, interaction: discord.Interaction, button: discord.ui.Button):
        vc = self.player._guild.voice_client
        if not vc or not vc.is_playing():
            return await interaction.response.send_message("⚠️ Nothing is playing.", ephemeral=True)
        vc.stop()
        await interaction.response.send_message("⏭ Skipped!", ephemeral=True)

    @discord.ui.button(label="⏸ Pause/▶ Resume", style=discord.ButtonStyle.blurple)
    async def pause_resume(self, interaction: discord.Interaction, button: discord.ui.Button):
        vc = self.player._guild.voice_client
        if not vc:
            return await interaction.response.send_message("⚠️ Not connected.", ephemeral=True)
        if vc.is_playing():
            vc.pause()
            await interaction.response.send_message("⏸ Paused!", ephemeral=True)
        elif vc.is_paused():
            vc.resume()
            await interaction.response.send_message("▶ Resumed!", ephemeral=True)

    @discord.ui.button(label="🔁 Loop", style=discord.ButtonStyle.grey)
    async def loop(self, interaction: discord.Interaction, button: discord.ui.Button):
        modes = ["off", "one", "all"]
        idx = modes.index(self.player.loop_mode)
        self.player.loop_mode = modes[(idx + 1) % len(modes)]
        await interaction.response.send_message(f"Loop mode: {self.player.loop_mode}", ephemeral=True)

class NowPlayingView(discord.ui.View):
    def __init__(self, bot, ctx):
        super().__init__(timeout=None)
        self.bot = bot
        self.ctx = ctx

    @discord.ui.button(label="⏯️ Pause/Resume", style=discord.ButtonStyle.primary)
    async def pause_resume(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self.ctx.invoke(self.bot.get_command("pause"))

    @discord.ui.button(label="⏭️ Skip", style=discord.ButtonStyle.danger)
    async def skip(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self.ctx.invoke(self.bot.get_command("skip"))

    @discord.ui.button(label="📜 Queue", style=discord.ButtonStyle.secondary)
    async def show_queue(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self.ctx.invoke(self.bot.get_command("queue"))

class QueueView(discord.ui.View):
    def __init__(self, bot, ctx):
        super().__init__(timeout=None)
        self.bot = bot
        self.ctx = ctx

    @discord.ui.button(label="🔀 Shuffle", style=discord.ButtonStyle.success)
    async def shuffle_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self.ctx.invoke(self.bot.get_command("shuffle"))

    @discord.ui.button(label="🗑️ Clear Queue", style=discord.ButtonStyle.danger)
    async def clear_queue(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self.ctx.invoke(self.bot.get_command("clearqueue"))

# ==========================
# Music Cog
# ==========================
class Music(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.players = {}

    def get_player(self, ctx):
        return self.players.setdefault(ctx.guild.id, MusicPlayer(ctx))

    # ----------------- JOIN / CONNECT -----------------
    @commands.command(name="join", aliases=["connect", "joinvc"])
    async def join_command(self, ctx):
        if ctx.author.voice is None:
            return await ctx.send(embed=discord.Embed(description="⚠️ You must be in a voice channel.", color=DEFAULT_COLOR))
        if ctx.voice_client is not None:
            return await ctx.send(embed=discord.Embed(description="✅ Already connected.", color=DEFAULT_COLOR))
        await ctx.author.voice.channel.connect()
        await ctx.send(embed=discord.Embed(description=f"✅ Connected to {ctx.author.voice.channel.name}", color=DEFAULT_COLOR))

    # ----------------- DISCONNECT / LEAVE -----------------
    @commands.command(name="disconnect", aliases=["leave"])
    async def disconnect(self, ctx):
        if ctx.voice_client is None:
            return await ctx.send(embed=discord.Embed(description="⚠️ Not connected.", color=DEFAULT_COLOR))
        await ctx.voice_client.disconnect()
        await ctx.send(embed=discord.Embed(description="✅ Disconnected.", color=DEFAULT_COLOR))

    # ----------------- PLAY -----------------
    @commands.command(name="play", aliases=["p"])
    async def play_command(self, ctx, *, query: str):
        if ctx.author.voice is None:
            return await ctx.send(embed=discord.Embed(description="⚠️ You must be in a voice channel.", color=DEFAULT_COLOR))
        if ctx.voice_client is None:
            await ctx.author.voice.channel.connect()
        player = self.get_player(ctx)
        loading_msg = await ctx.send(embed=discord.Embed(description=f"🔍 Searching for **{query}** ...", color=DEFAULT_COLOR))
        try:
            if is_spotify_link(query):
                urls = await fetch_youtube_links_from_spotify(query)
                added_tracks = []
                for track in urls:
                    source = await YTDLSource.create_source(track, loop=self.bot.loop)
                    await player.queue.put(source)
                    added_tracks.append(f"[{source.title}]({source.url})")
                await loading_msg.edit(embed=discord.Embed(
                    description=f"✅ Added {len(added_tracks)} track(s) from Spotify to queue:\n" + "\n".join(added_tracks),
                    color=DEFAULT_COLOR
                ))
            else:
                source = await YTDLSource.create_source(query, loop=self.bot.loop)
                await player.queue.put(source)
                await loading_msg.edit(embed=discord.Embed(
                    description=f"✅ Added to queue: **[{source.title}]({source.url})**",
                    color=DEFAULT_COLOR
                ))
        except Exception as e:
            await loading_msg.edit(embed=discord.Embed(description=f"❌ Error while processing: {e}", color=DEFAULT_COLOR))

    # ----------------- PAUSE / RESUME -----------------
    @commands.command(name="pause")
    async def pause(self, ctx):
        vc = ctx.voice_client
        if not vc or not vc.is_playing():
            return await ctx.send(embed=discord.Embed(description="⚠️ Nothing is playing.", color=DEFAULT_COLOR))
        vc.pause()
        await ctx.send(embed=discord.Embed(description="⏸ Paused!", color=DEFAULT_COLOR))

    @commands.command(name="resume")
    async def resume(self, ctx):
        vc = ctx.voice_client
        if not vc or not vc.is_paused():
            return await ctx.send(embed=discord.Embed(description="⚠️ Nothing is paused.", color=DEFAULT_COLOR))
        vc.resume()
        await ctx.send(embed=discord.Embed(description="▶ Resumed!", color=DEFAULT_COLOR))

    # ----------------- SKIP -----------------
    @commands.command(name="skip")
    async def skip(self, ctx):
        vc = ctx.voice_client
        if not vc or not vc.is_playing():
            return await ctx.send(embed=discord.Embed(description="⚠️ Nothing is playing.", color=DEFAULT_COLOR))
        vc.stop()
        await ctx.send(embed=discord.Embed(description="⏭ Skipped!", color=DEFAULT_COLOR))

    # ----------------- QUEUE -----------------
    @commands.command(name="queue")
    async def queue_command(self, ctx):
        player = self.get_player(ctx)
        if player.queue.empty():
            return await ctx.send(embed=discord.Embed(description="⚠️ Queue is empty.", color=DEFAULT_COLOR))
        qlist = list(player.queue._queue)
        desc = ""
        view = QueueView(self.bot, ctx)
        await ctx.send(embed=embed, view=view)
        for i, s in enumerate(qlist, 1):
            desc += f"{i}. [{s.title}]({s.url})\n"
        embed = discord.Embed(title="🎶 Queue", description=desc, color=DEFAULT_COLOR)
        embed.set_author(name=self.bot.user.name, icon_url=self.bot.user.display_avatar.url)
        embed.set_thumbnail(url=player.current.thumbnail if player.current else "")
        embed.set_footer(text="Made by Isho")
        await ctx.send(embed=embed)

    # ----------------- REMOVE -----------------
    @commands.command(name="remove")
    async def remove(self, ctx, position: int):
        player = self.get_player(ctx)
        qlist = list(player.queue._queue)
        if position < 1 or position > len(qlist):
            return await ctx.send(embed=discord.Embed(description="⚠️ Invalid position.", color=DEFAULT_COLOR))
        removed = qlist.pop(position - 1)
        player.queue._queue = asyncio.Queue()
        for item in qlist:
            await player.queue.put(item)
        await ctx.send(embed=discord.Embed(description=f"❌ Removed **{removed.title}** from the queue.", color=DEFAULT_COLOR))

    # ----------------- MOVE -----------------
    @commands.command(name="move")
    async def move(self, ctx, old_pos: int, new_pos: int):
        player = self.get_player(ctx)
        qlist = list(player.queue._queue)
        if old_pos < 1 or old_pos > len(qlist) or new_pos < 1 or new_pos > len(qlist):
            return await ctx.send(embed=discord.Embed(description="⚠️ Invalid positions.", color=DEFAULT_COLOR))
        item = qlist.pop(old_pos - 1)
        qlist.insert(new_pos - 1, item)
        player.queue._queue = asyncio.Queue()
        for s in qlist:
            await player.queue.put(s)
        await ctx.send(embed=discord.Embed(description=f"✅ Moved **{item.title}** to position {new_pos}.", color=DEFAULT_COLOR))

    # ----------------- CLEARQUEUE -----------------
    @commands.command(name="clearqueue")
    async def clearqueue(self, ctx):
        player = self.get_player(ctx)
        while not player.queue.empty():
            await player.queue.get()
        await ctx.send(embed=discord.Embed(description="🗑 Cleared the queue.", color=DEFAULT_COLOR))

    # ----------------- NOW PLAYING -----------------
    @commands.command(name="nowplaying", aliases=["np"])
    async def nowplaying(self, ctx):
        player = self.get_player(ctx)
        if not player.current:
            return await ctx.send(embed=discord.Embed(description="⚠️ Nothing is playing.", color=DEFAULT_COLOR))
        src = player.current
        embed = discord.Embed(
            title=f"🎶 Now Playing - {src.title}",
            description=f"[{src.title}]({src.url})",
            color=DEFAULT_COLOR
        )
        view = NowPlayingView(self.bot, ctx)
        await ctx.send(embed=embed, view=view)
        embed.set_author(name=self.bot.user.name, icon_url=self.bot.user.display_avatar.url)
        embed.set_thumbnail(url=src.thumbnail)
        embed.add_field(name="Uploader", value=src.uploader)
        embed.add_field(name="Duration", value=f"{src.duration // 60}:{src.duration % 60:02}")
        embed.set_footer(text="Made by Isho")
        await ctx.send(embed=embed)
    # ----------------- LOOP -----------------
    @commands.command(name="loop")
    async def loop(self, ctx, mode: str = None):
        player = self.get_player(ctx)
        modes = ["off", "one", "all"]
        if mode is None:
            return await ctx.send(embed=discord.Embed(description=f"Current loop mode: `{player.loop_mode}`", color=DEFAULT_COLOR))
        if mode.lower() not in modes:
            return await ctx.send(embed=discord.Embed(description="⚠️ Invalid mode. Choose `off`, `one`, or `all`.", color=DEFAULT_COLOR))
        player.loop_mode = mode.lower()
        await ctx.send(embed=discord.Embed(description=f"🔁 Loop mode set to `{player.loop_mode}`", color=DEFAULT_COLOR))

    # ----------------- SHUFFLE -----------------
    @commands.command(name="shuffle")
    async def shuffle(self, ctx):
        import random
        player = self.get_player(ctx)
        qlist = list(player.queue._queue)
        random.shuffle(qlist)
        player.queue._queue = asyncio.Queue()
        for s in qlist:
            await player.queue.put(s)
        await ctx.send(embed=discord.Embed(description="🔀 Queue shuffled.", color=DEFAULT_COLOR))

    # ----------------- LYRICS -----------------
    @commands.command(name="lyrics")
    async def lyrics(self, ctx, *, query: str = None):
        if genius is None:
            return await ctx.send(embed=discord.Embed(description="⚠️ Genius API not configured.", color=DEFAULT_COLOR))
        player = self.get_player(ctx)
        if query is None:
            if not player.current:
                return await ctx.send(embed=discord.Embed(description="⚠️ Nothing is playing.", color=DEFAULT_COLOR))
            query = player.current.title
        await ctx.send(embed=discord.Embed(description=f"🔍 Searching lyrics for **{query}** ...", color=DEFAULT_COLOR))
        try:
            song = genius.search_song(query)
        except Exception as e:
            return await ctx.send(embed=discord.Embed(description=f"❌ Failed to fetch lyrics: {e}", color=DEFAULT_COLOR))
        if not song:
            return await ctx.send(embed=discord.Embed(description=f"⚠️ No lyrics found for **{query}**", color=DEFAULT_COLOR))
        embed = discord.Embed(title=f"🎤 Lyrics - {song.title}", description=song.lyrics, color=DEFAULT_COLOR)
        embed.set_author(name=self.bot.user.name, icon_url=self.bot.user.display_avatar.url)
        embed.set_footer(text="Made by Isho")
        await ctx.send(embed=embed)

    # ----------------- PITCH / SPEED -----------------
    @commands.command(name="pitch")
    async def pitch(self, ctx, value: float):
        await ctx.send(embed=discord.Embed(description=f"⚠️ Pitch adjustment currently not implemented.", color=DEFAULT_COLOR))

    @commands.command(name="speed")
    async def speed(self, ctx, value: float):
        await ctx.send(embed=discord.Embed(description=f"⚠️ Speed adjustment currently not implemented.", color=DEFAULT_COLOR))

    # ----------------- REMOVEDUPES -----------------
    @commands.command(name="removedupes")
    async def removedupes(self, ctx):
        player = self.get_player(ctx)
        qlist = list(player.queue._queue)
        seen = set()
        new_queue = []
        for s in qlist:
            if s.title not in seen:
                seen.add(s.title)
                new_queue.append(s)
        player.queue._queue = asyncio.Queue()
        for s in new_queue:
            await player.queue.put(s)
        await ctx.send(embed=discord.Embed(description="🗑 Removed duplicate songs from queue.", color=DEFAULT_COLOR))

# ==========================
# Cog Setup
# ==========================
async def setup(bot):
    await bot.add_cog(Music(bot))
