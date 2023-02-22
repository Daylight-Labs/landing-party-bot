import discord
from discord.commands import SlashCommandGroup
from commands_guided_flows import OnboardingInvitationButton
from commands_guided_flows import ActionButton
import api_util
import requests
import io
from community import initialize_all_supported_communities, SUPPORTED_COMMUNITIES

def get_embed_files(embed_file_db_objects):
    files = []

    for row in embed_file_db_objects:
        name = row['name']
        file = row['file']

        # TODO Replace with your S3 url (needs to the same as on back-end)
        url = f'https://yours3url.s3.amazonaws.com/{file}'

        response = requests.get(url)
        if response.status_code != 200:
            print('file fetch error', url)
            continue
        data = io.BytesIO(response.content)
        files.append(discord.File(data, name))

    return files

class FlowCommands(discord.Cog):

    def __init__(self, bot):
        self.bot = bot

    @discord.slash_command(name="create_button_for_flowentry")
    async def select_menu_single_choice(self, ctx, title: discord.commands.Option(str, "title"), description: discord.commands.Option(str, "description")):
        initialize_all_supported_communities()
        guild_id = ctx.interaction.guild_id
        community = SUPPORTED_COMMUNITIES[guild_id]
        is_admin = community.user_has_admin_access(ctx.interaction.user)

        if not is_admin:
            await ctx.respond(f'Sorry, you don\'t have permissions to do this!', ephemeral=True)
            return

        channel_id = ctx.interaction.channel.id

        embed_obj = await api_util.get_permanent_embed_by_channel_id(channel_id)

        embed = discord.Embed(
            title=title,
            description=description,
            color=discord.Colour.blurple()
        )

        view = discord.ui.View()

        unfulfilled_row = 0
        count_by_row = {}

        for button in embed_obj['buttons']:
            row = button.get('button_row')

            if row is None:
                row = unfulfilled_row
            else:
                row -= 1

            new_callback_set = []
            for new_callback in button['handler_callbacks']:
                new_callback_set.append(new_callback['event_handler_id'])
            view.add_item(ActionButton(button['button_label'],
                                       button['event_id'],
                                       [new_callback_set],
                                       button['button_style'],
                                       row=row))

            count_by_row[row] = count_by_row.get(row, 0) + 1

            while count_by_row.get(unfulfilled_row, 0) >= 5:
                unfulfilled_row += 1

        file_db_objects = None
        if 'attached_files' in embed_obj: 
            file_db_objects = embed_obj['attached_files']

        if file_db_objects and len(file_db_objects) > 0:
            await ctx.interaction.channel.send(embed=embed, view=view)
            interaction = ctx.interaction
            await interaction.response.send_message("Loading attachments...")

            files = get_embed_files(file_db_objects)
            await interaction.edit_original_message(content="", files=files)
        else:
            await ctx.interaction.channel.send(embed=embed, view=view)
            await ctx.respond("Success", ephemeral=True)

    @discord.slash_command(name="edit_button_for_flowentry")
    async def edit_button_for_flowentry(self, ctx, title: discord.commands.Option(str, "title"),
                                        description: discord.commands.Option(str, "description"),
                                        message_id: discord.commands.Option(str, "message id")):
        initialize_all_supported_communities()
        guild_id = ctx.interaction.guild_id
        community = SUPPORTED_COMMUNITIES[guild_id]
        is_admin = community.user_has_admin_access(ctx.interaction.user)

        if not is_admin:
            await ctx.respond(f'Sorry, you don\'t have permissions to do this!', ephemeral=True)
            return

        async def get_message():
            try:
                message = await ctx.interaction.channel.fetch_message(message_id)
                if message.author.id != self.bot.user.id:
                    await ctx.respond("Embed not found within this message id",
                                      ephemeral=True)
                return message
            except Exception as e:
                await ctx.respond("Embed not found. It should be the very last message in this channel",
                                  ephemeral=True)
                raise e

        message = await get_message()

        channel_id = ctx.interaction.channel.id

        embed_obj = await api_util.get_permanent_embed_by_channel_id(channel_id)

        embed = discord.Embed(
            title=title,
            description=description,
            color=discord.Colour.blurple()
        )

        view = discord.ui.View()

        unfulfilled_row = 0
        count_by_row = {}

        for button in embed_obj['buttons']:
            row = button.get('button_row')

            if row is None:
                row = unfulfilled_row
            else:
                row -= 1

            new_callback_set = []
            for new_callback in button['handler_callbacks']:
                new_callback_set.append(new_callback['event_handler_id'])
            view.add_item(ActionButton(button['button_label'],
                                       button['event_id'],
                                       [new_callback_set],
                                       button['button_style'],
                                       row=row))

            count_by_row[row] = count_by_row.get(row, 0) + 1

            while count_by_row.get(unfulfilled_row, 0) >= 5:
                unfulfilled_row += 1

        file_db_objects = None
        if 'attached_files' in embed_obj:
            file_db_objects = embed_obj['attached_files']

        await ctx.respond("Message will be updated soon", ephemeral=True)
        await message.edit(content="Loading...", attachments=[])

        if file_db_objects and len(file_db_objects) > 0:
            files = get_embed_files(file_db_objects)
            # For some reason does not work without refresh
            message = await get_message()
            await message.edit(content="", embed=embed, view=view, files=files)
        else:
            await message.edit(content="", embed=embed, view=view)
            await ctx.respond("Success", ephemeral=True)
