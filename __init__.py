import asyncio
import datetime
import random
import time
from collections import Counter
from dataclasses import dataclass

import discord
from discord.ext import commands

import breadcord


@dataclass
class Vote:
    user: discord.User
    for_muting: bool
    duration_seconds: int | None = None


class MuteDurationDropdown(discord.ui.Select):
    def __init__(self) -> None:
        options = [
            discord.SelectOption(label="1 minute", value=str(60)),
            discord.SelectOption(label="5 minutes", value=str(60 * 5)),
            discord.SelectOption(label="10 minutes", value=str(60 * 10)),
            discord.SelectOption(label="30 minutes", value=str(60 * 30)),
            discord.SelectOption(label="1 hour", value=str(60 * 60)),
            discord.SelectOption(label="2 hours", value=str(60 * 60 * 2)),
            discord.SelectOption(label="6 hours", value=str(60 * 60 * 6)),
            discord.SelectOption(label="12 hours", value=str(60 * 60 * 12)),
            discord.SelectOption(label="1 day", value=str(60 * 60 * 24)),
            discord.SelectOption(label="3 days", value=str(60 * 60 * 24 * 3)),
            discord.SelectOption(label="1 week", value=str(60 * 60 * 24 * 7)),
        ]

        super().__init__(placeholder="Select a mute duration", options=options)

    async def callback(self, interaction: discord.Interaction) -> None:
        selected_option = self.values[0]

        self.view.selected_duration = int(selected_option)
        await interaction.response.edit_message(
            content=f"Selected duration.",
            view=None,
        )
        self.view.stop()


class MoteDurationView(discord.ui.View):
    def __init__(self) -> None:
        super().__init__()
        self.selected_duration: int | None = None

        self.add_item(MuteDurationDropdown())


class MuteVoteView(discord.ui.View):
    def __init__(self, *, timeout: float) -> None:
        super().__init__(timeout=timeout)
        self.votes: dict[int, Vote] = {}

    async def handle(self, interaction: discord.Interaction, vote: Vote) -> None:
        positive_votes = sum(vote.for_muting for vote in self.votes.values())
        negative_votes = len(self.votes) - positive_votes

        self.button_mute.label = f"Mute ({positive_votes})"
        self.button_no_mute.label = f"Don't mute ({negative_votes})"

        await interaction.message.edit(view=self)

    @discord.ui.button(label="Mute (0)", style=discord.ButtonStyle.green, emoji='\N{THUMBS UP SIGN}')
    async def button_mute(self, interaction: discord.Interaction, _) -> None:
        vote = Vote(
            user=interaction.user,
            for_muting=True,
        )

        duration_view = MoteDurationView()
        await interaction.response.send_message(
            "For how long?",
            view=duration_view,
            ephemeral=True,
        )
        await duration_view.wait()
        vote.duration_seconds = duration_view.selected_duration
        self.votes[interaction.user.id] = vote

        await self.handle(interaction, vote)

    @discord.ui.button(label="Don't mute (0)", style=discord.ButtonStyle.red)
    async def button_no_mute(self, interaction: discord.Interaction, _) -> None:
        vote = Vote(
            user=interaction.user,
            for_muting=False,
        )
        self.votes[interaction.user.id] = vote

        await interaction.response.defer()
        await self.handle(interaction, vote)


class MDSPSpecials(breadcord.module.ModuleCog):
    def __init__(self, module_id: str):
        super().__init__(module_id)

    @commands.command()
    async def mute_aman(self, ctx: commands.Context):
        run_by_owner = await self.bot.is_owner(ctx.author)
        if ctx.guild != self.settings.mdsp_guild_id.value and not run_by_owner:
            return

        aman = ctx.guild.get_member(int(self.settings.aman_id.value))
        if aman is None:
            return

        timeout_seconds = 60 * 10
        timeout_timestamp = int(time.time()) + timeout_seconds
        needed_votes = int(self.settings.votes_needed.value)

        view = MuteVoteView(timeout=timeout_seconds)
        response = await ctx.send(
            f"Mute {aman.display_name}? Voting ends <t:{timeout_timestamp}:R>\n"
            f"Votes needed: {needed_votes}",
            view=view
        )
        await view.wait()

        for child in view.children:
            child.disabled = True
        await response.edit(
            content=f"Voting has ended!",
            view=view,
        )

        positive_votes = sum(vote.for_muting for vote in view.votes.values())
        negative_votes = len(view.votes) - positive_votes
        votes = positive_votes - negative_votes

        if not (votes >= needed_votes):
            await response.reply(f"Not enough votes! {positive_votes} votes for, {negative_votes} votes against.")
            return

        timeout_votes = Counter(
            vote.duration_seconds
            for vote in view.votes.values()
            if vote.duration_seconds is not None
        )
        timeout_votes = timeout_votes.most_common()
        timeout_seconds = timeout_votes[0][0]

        if all(
            timeout_votes[0][1] == timeout_vote[1]
            for timeout_vote in timeout_votes
        ):
            # Smallest out of all chosen durations
            timeout_seconds = min(timeout_vote for timeout_vote, _ in timeout_votes)

        mute_until = discord.utils.utcnow() + datetime.timedelta(seconds=timeout_seconds)

        await response.reply(f"Muting {aman.display_name} until <t:{int(mute_until.timestamp())}:R>")
        await aman.timeout(
            mute_until,
            reason=f"Muted by a vote. {positive_votes} votes for, {negative_votes} votes against.",
        )

    @commands.Cog.listener()
    async def on_message(self, message: discord.Message):
        content = message.content.lower().removeprefix("f!")
        if message.content.lower() == content:
            return
        if await self.bot.is_owner(message.author):
            return
        if random.random() < 1/3:
            return

        def command_names(command: commands.Command) -> list[str]:
            return [
                f"{command.full_parent_name} {alias}".lstrip()
                for alias in [*command.aliases, command.name]
            ]

        if not any(
            content.startswith(command_name)
            for command in self.bot.commands
            for command_name in command_names(command)
        ):
            return

        # Give fripe.py some time to reply in case the command is heavier, won't always work though
        await asyncio.sleep(2.0)

        if not any([
            msg.author.id == 818919767784161293
            async for msg in message.channel.history(limit=5)
            if msg.created_at > message.created_at
        ]):
            return

        choices: list[str] = self.settings.fripe_py_disendorcements.value
        await message.reply(random.choice(choices))


async def setup(bot: breadcord.Bot):
    await bot.add_cog(MDSPSpecials("mdsp_specials"))
