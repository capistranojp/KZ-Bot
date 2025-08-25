import discord
from discord.ext import commands, tasks
import logging
from dotenv import load_dotenv
import os
import random
from itertools import cycle
import asyncio

# =======================
# Logging Setup
# =======================
logging.basicConfig(
    handlers=[logging.FileHandler(filename="discord.log", encoding="utf-8", mode="w")],
    format="%(asctime)s:%(levelname)s:%(name)s: %(message)s",
    level=logging.DEBUG
)

# =======================
# Load Environment
# =======================
load_dotenv()
token = os.getenv("DISCORD_TOKEN")

DEFAULT_COLOR = 0x4c00b0

# =======================
# Custom Help Command
# =======================
class EmbedHelp(commands.MinimalHelpCommand):
    async def send_pages(self):
        embed = discord.Embed(title="📖 Help", color=DEFAULT_COLOR)
        for page in self.paginator.pages:
            embed.add_field(name="\u200b", value=page, inline=False)
        await self.get_destination().send(embed=embed)

# =======================
# Bot Init
# =======================
kz = commands.Bot(
    command_prefix='?',
    intents=discord.Intents.all(),
    help_command=EmbedHelp()
)

bot_status = cycle([
    "? | Babysitting Kurozaya",
    "? | Made by Isho",
    "? | Kurozaya #1!",
    "? | .gg/kzaya"
])

# =======================
# Remove Duplicate Music Commands (Before Loading Cog)
# =======================
for cmd_name in [
    "join","connect","joinvc","play","p","pause","resume","skip","queue","remove",
    "move","disconnect","leave","lyrics","loop","shuffle","clearqueue","nowplaying",
    "pitch","speed","removedupes"
]:
    if kz.get_command(cmd_name):
        kz.remove_command(cmd_name)

# =======================
# Events
# =======================
@tasks.loop(seconds=30)
async def change_status():
    await kz.change_presence(activity=discord.Game(next(bot_status)))

@kz.event
async def on_ready():
    print(f"✅ Logged in as {kz.user} (ID: {kz.user.id})")
    print("Loaded commands:")
    for cmd in kz.commands:
        print(f"- {cmd.name} (aliases: {getattr(cmd, 'aliases', [])})")
    change_status.start()

@kz.event
async def on_command_error(ctx, error):
    embed = discord.Embed(description=f"❌ Error: {str(error)}", color=DEFAULT_COLOR)
    await ctx.send(embed=embed)

@kz.event
async def on_message(message):
    if message.author == kz.user:
        return
    await kz.process_commands(message)

# =======================
# General Commands
# =======================
@kz.command()
async def hello(ctx):
    embed = discord.Embed(description=f"Hello, {ctx.author.mention}!", color=DEFAULT_COLOR)
    await ctx.send(embed=embed)

# Other utility commands like ping, purge, assign, removerole, etc. remain here

# =======================
# Cog Loader
# =======================
async def load():
    for filename in os.listdir("./cogs"):
        if filename.endswith(".py"):
            try:
                await kz.load_extension(f"cogs.{filename[:-3]}")
                print(f"✅ Loaded cog: {filename}")
            except Exception as e:
                print(f"❌ Failed to load cog {filename}: {e}")

# =======================
# Main Entrypoint
# =======================
async def main():
    async with kz:
        await load()
        await kz.start(token)

if __name__ == "__main__":
    asyncio.run(main())
