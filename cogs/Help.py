import discord
from discord.ext import commands

DEFAULT_COLOR = 0x4c00b0  # Brand color

class Help(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.bot.remove_command("help")  # Remove default help

    @commands.command(name="help")
    async def prefix_help(self, ctx, *, category: str = None):
        embed = self.build_help_embed(ctx.author, category)
        await ctx.send(embed=embed)

    def build_help_embed(self, user, category=None):
        embed = discord.Embed(
            title="📖 Help Menu",
            description="Here are the commands you can use:",
            color=DEFAULT_COLOR
        )
        embed.set_footer(
            text=f"Requested by {user}",
            icon_url=user.display_avatar.url
        )

        if category is None:
            embed.add_field(
                name="🎵 Music",
                value=(
                    "`play`, `join`, `connect`, `pause`, `resume`, `skip`, `queue`, `remove`, "
                    "`move`, `disconnect`, `leave`, `lyrics`, `loop`, `shuffle`, `clearqueue`, "
                    "`nowplaying`, `pitch`, `speed`, `removedupes`"
                ),
                inline=False
            )
            embed.add_field(
                name="⚙️ Utility",
                value="`ping`, `purge`, `assign`, `removerole`, `dm`, `reply`",
                inline=False
            )
            embed.add_field(
                name="🎲 Fun",
                value="`hello`, `8ball`, `poll`",
                inline=False
            )
            embed.add_field(
                name="ℹ️ More",
                value="Use `?help <category>` for details.",
                inline=False
            )
        else:
            category = category.lower()
            if category == "music":
                embed.description = "🎵 **Music Commands**"
                embed.add_field(
                    name="Commands",
                    value=(
                        "`play <song>` - Play music\n"
                        "`join/connect` - Join your VC\n"
                        "`pause` - Pause current track\n"
                        "`resume` - Resume paused track\n"
                        "`skip` - Skip current track\n"
                        "`queue` - Show queue\n"
                        "`remove <pos>` - Remove track from queue\n"
                        "`move <from> <to>` - Move track in queue\n"
                        "`disconnect/leave` - Leave VC\n"
                        "`lyrics [song]` - Fetch lyrics\n"
                        "`loop [off|one|all]` - Looping mode\n"
                        "`shuffle` - Shuffle queue\n"
                        "`clearqueue` - Clear all queued songs\n"
                        "`nowplaying` - Show now playing info\n"
                        "`pitch <value>` - Change pitch\n"
                        "`speed <value>` - Change speed\n"
                        "`removedupes` - Remove duplicate songs in queue"
                    ),
                    inline=False
                )
            # Optionally add utility/fun category details here
            else:
                embed.description = f"⚠️ Unknown category: `{category}`"
        return embed

async def setup(bot):
    await bot.add_cog(Help(bot))
