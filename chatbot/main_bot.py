import os
import logging
import discord
from community import SUPPORTED_COMMUNITIES, initialize_all_supported_communities
from qa_view import QAView
from dotenv import load_dotenv
import time

from database import execute_sql

from bot_reaction_commands import REACTION_COMMANDS
from bot_message_commands import MESSAGE_COMMANDS
from commands import Commands, send_all_notifications
from flow_commands import FlowCommands
from commands_guided_flows import parse_custom_id, \
    contact_mod_callback, invitation_callback, need_help_callback, action_button_callback, \
    generate_all_guided_flow_cogs, approve_role_callback, ticket_modal_callback, custom_modal_callback, \
    submit_select_menu_callback, \
    EVENT_TYPE_EVENT, EVENT_TYPE_HELP_FOR_STEP_WITH_EVENT_ID, EVENT_TYPE_CONTACT_MOD_FOR_STEP_WITH_EVENT_ID, \
    EVENT_TYPE_INVITATION_TO_FLOW_WITH_EVENT_ID, EVENT_TYPE_APPROVE_ROLE_FOR_STEP_WITH_EVENT_ID, \
    EVENT_TYPE_EVENT_HANDLER, EVENT_TYPE_SUBMIT_TICKET_MODAL_WITH_EVENT_ID, \
    EVENT_TYPE_SUBMIT_CUSTOM_MODAL_WITH_EVENT_ID, EVENT_TYPE_SUBMIT_SELECT_MENU_WITH_EVENT_ID, \
    respond_for_triggered_handlers, EVENT_TYPE_QA_DOCUMENT_COMPLETION_BUTTON_FLOW_ID, \
    qa_document_completion_button_callback, EVENT_TYPE_CAPTCHA_START, verify_captcha

from commands import create_qa_modal_callback, EVENT_TYPE_CREATE_QA_DOC, EVENT_TYPE_UPDATE_QA_DOC, \
    EVENT_TYPE_DELETE_QA_DOC, update_qa_modal_callback, delete_qa_modal_callback, \
    EVENT_TYPE_ADD_ADMIN_RIGHTS, EVENT_TYPE_REMOVE_ADMIN_RIGHTS, toggle_admin_rights_callback

from discord.ext.tasks import loop
from interaction_wrapper import InteractionWrapper

import logging
import sys
import traceback

import sentry_sdk
from event_logger import EventLogger

from api_util import get_first_message_mapping_in_message_id_list, add_user_file_upload, sync_all_channels

import datetime

from event_logger import EventLogger

# Uncomment to log ALL pycord logs to stdout
#logging.basicConfig(stream=sys.stdout, level=logging.DEBUG)

class BackgroundBot(discord.Bot):

    def __init__(self):
        intents = discord.Intents.default()
        intents.members = True
        intents.message_content = True
        super().__init__(intents=intents)

        #Iterate through all communities and create a QAView for each one
        self.__qa_views_dict = dict()
        initialize_all_supported_communities()
        self.initialize_qa_views()
        self.persistent_views_added = False
        sentry_sdk.init(
            dsn="", # Fill you Sentry DSN here

            # Set traces_sample_rate to 1.0 to capture 100%
            # of transactions for performance monitoring.
            # We recommend adjusting this value in production.
            traces_sample_rate=1.0,
            attach_stacktrace=True,
            environment=os.getenv('ENVIRONMENT')
        )
    
    async def on_ready(self):
        if not self.persistent_views_added:
            # Register the persistent view for listening here.
            # Note that this does not send the view to any message.
            # In order to do this you need to first send a message with the View, which is shown below.
            # If you have the message_id you can also pass it as a keyword argument, but for this example
            # we don't have one.
            # self.add_view(TicketButton())
            self.persistent_views_added = True

        print(f"Logged in as {self.user} (ID: {self.user.id})")
        print("------")
    
    async def on_error(self, event_method: str, *args, **kwargs) -> None:
        sentry_sdk.capture_exception()
        print(f"Ignoring exception in {event_method}", file=sys.stderr)
        traceback.print_exc()

    def initialize_qa_views(self):
        for k in list(self.__qa_views_dict.keys()):
            del self.__qa_views_dict[k]

        for c in SUPPORTED_COMMUNITIES.values():
            self.__qa_views_dict[c.guild_id] = QAView(c)
    
    def get_qa_view(self, _community):
        return self.__qa_views_dict[_community.guild_id]

    # Get message.reference full Message object (either return cached one, or fetch from discord API)
    async def get_reference_message(self, message):
        if message.reference.cached_message is None:
            # Fetching the message
            channel = self.get_channel(message.reference.channel_id)
            msg = await channel.fetch_message(message.reference.message_id)
        else:
            # Using cached message
            msg = message.reference.cached_message
        return msg
    
    # Returns a list of Message-s of current conversation in reverse chronological order
    # Conversation is defined by replies chain
    async def get_conversation(self, message, max_depth=None):
        messages = [message]
        current_message = message
        depth = 0
        while current_message.reference is not None:
            current_message = await self.get_reference_message(current_message)
            messages.append(current_message)
            depth += 1
            if depth == max_depth:
                break
        return messages

    async def on_guild_join(self, guild):
        print("on_guild_join")
        embed = discord.Embed(
            title="Thanks for adding our Landing Party bot to your server!",
            description="""To contine setting up your FAQs and your Admin Portal dashboard go [here](https://app.landing.party)

:sos: Need help?
[How to Install](https://www.landing.party/scout-install) | [Join our Discord](https://discord.com/invite/4BpXwS6JSq)""",
            color=discord.Colour.blurple()
        )
        for channel in guild.text_channels:
            if channel.permissions_for(guild.me).send_messages:
                await channel.send('',
                                   embed=embed)
                break
    
    async def on_message(self, message):
        # Exit if the bot is the message sender
        if message.author.id == self.user.id:
            return

        # Exit if the message is not a regular message
        # Everything other than a default message is a system message 
        # https://docs.pycord.dev/en/master/api.html?highlight=on_message#discord.MessageType
        if not message.type == discord.MessageType.default:
            return
        
        try:
            _community = SUPPORTED_COMMUNITIES.get(message.guild.id)
        except:
            return

        if len(message.attachments) == 1:
            try:
                messages_by_id = {}
                async for msg in message.channel.history(limit=30):
                    messages_by_id[str(msg.id)] = msg
                message_mapping = await get_first_message_mapping_in_message_id_list(list(messages_by_id.keys()))
                flow_step = message_mapping["flow_step"]
            except:
                return

            if len(flow_step["file_upload_triggered_handlers"]) > 0:
                callback_ids_sets = message_mapping["callback_ids_sets"]

                supported_files_formats_csv = flow_step['supported_files_formats_csv']
                file_upload_triggered_handlers = flow_step['file_upload_triggered_handlers']

                supported_files_formats = list(map(lambda x: x.strip(), supported_files_formats_csv.split(',')))

                format = message.attachments[0].filename.split('.')[-1]

                if supported_files_formats is None or len(supported_files_formats_csv.strip()) == 0 or \
                        format in supported_files_formats:
                    interaction_wrapper = InteractionWrapper(message=message)
                    await respond_for_triggered_handlers(interaction_wrapper,
                                                         file_upload_triggered_handlers,
                                                         callback_ids_sets)
                    await add_user_file_upload(
                        filename=message.attachments[0].filename,
                        file_url=message.attachments[0].url,
                        discord_user_id=message.author.id,
                        discord_username=message.author.name,
                        flow_step_id=flow_step['guided_flow_step_id']
                    )
                else:
                    await message.reply('Invalid file format. Supported formats: ' + supported_files_formats_csv)


        if not _community or not _community.is_active:
            return
        if message.channel.id not in _community.active_channels:
            return

        is_admin = _community.user_has_admin_access(message.author)

        conversation = await self.get_conversation(message)

        for command in MESSAGE_COMMANDS:
            condition = command["condition"]
            handler = command["handler"]
            admin_only = command.get("admin_only", False)

            if admin_only and not is_admin:
                continue

            if await condition(self, message, _community, conversation):
                await handler(self, message, _community, conversation)
                break

    async def handle_reaction(self, payload):
        sentry_sdk.add_breadcrumb(
            category='bot',
            message='handle_reaction',
            level='info'
        )
        # Get the current guild
        _community = SUPPORTED_COMMUNITIES.get(payload.guild_id)
        if not _community or not _community.is_active:
            return

        # Make sure the person reacting is allow listed for adding new QA pairs
        # to the database
        if not payload.member:
            return
        
        if payload.channel_id not in _community.active_channels:
            return
        
        # Get the current channel and answer message
        try:
            channel = self.get_channel(payload.channel_id)
            message = await channel.fetch_message(payload.message_id)
            user = await message.guild.fetch_member(payload.user_id)
        except:
            return

        emoji = payload.emoji.name

        is_admin = _community.user_has_admin_access(user)

        conversation = await self.get_conversation(message)

        for command in REACTION_COMMANDS:
            condition = command["condition"]
            handler = command["handler"]
            admin_only = command.get("admin_only", False)

            if admin_only and not is_admin:
                continue
            
            if await condition(self, emoji, message, _community, conversation):
                await handler(self, message, _community, conversation)
                break

    async def on_raw_reaction_add(self, payload):
        sentry_sdk.add_breadcrumb(
            category='bot',
            message='on_raw_reaction_add',
            level='info'
        )

        _community = SUPPORTED_COMMUNITIES.get(payload.guild_id)
        if _community:
            await self.handle_reaction(payload)

    async def on_interaction(self, interaction):
        if interaction.type == discord.InteractionType.component:
            custom_id = interaction.custom_id
            (event_type, _, _) = parse_custom_id(custom_id)

            sentry_sdk.add_breadcrumb(
                category='bot',
                message='on_interaction',
                level='info',
                data={
                    "latency":'{0}'.format(interaction.client.latency),
                    "id": interaction.id,
                    "type": interaction.type,
                    "custom_id": interaction.custom_id,
                    "event_type": event_type,
                    "is_done": interaction.response.is_done(),
                    "current_time":'{0}'.format(datetime.datetime.now())
                }
            )
        
            if event_type == EVENT_TYPE_HELP_FOR_STEP_WITH_EVENT_ID:
                await need_help_callback(custom_id, interaction)
            if event_type == EVENT_TYPE_INVITATION_TO_FLOW_WITH_EVENT_ID:
                await invitation_callback(custom_id, interaction)
            if event_type == EVENT_TYPE_QA_DOCUMENT_COMPLETION_BUTTON_FLOW_ID:
                await qa_document_completion_button_callback(custom_id, interaction)
            if event_type == EVENT_TYPE_EVENT or event_type == EVENT_TYPE_EVENT_HANDLER:
                await action_button_callback(custom_id, interaction)
            if event_type == EVENT_TYPE_CONTACT_MOD_FOR_STEP_WITH_EVENT_ID:
                await contact_mod_callback(custom_id, interaction)
            if event_type == EVENT_TYPE_APPROVE_ROLE_FOR_STEP_WITH_EVENT_ID:
                await approve_role_callback(custom_id, interaction)
            if event_type == EVENT_TYPE_SUBMIT_SELECT_MENU_WITH_EVENT_ID:
                await submit_select_menu_callback(custom_id, interaction)
            if event_type == EVENT_TYPE_CAPTCHA_START:
                await verify_captcha(custom_id, interaction)
            if event_type in [EVENT_TYPE_ADD_ADMIN_RIGHTS, EVENT_TYPE_REMOVE_ADMIN_RIGHTS]:
                await toggle_admin_rights_callback(custom_id, interaction)
        elif interaction.type == discord.InteractionType.modal_submit:
            custom_id = interaction.custom_id
            (event_type, _, _) = parse_custom_id(custom_id)
            if event_type == EVENT_TYPE_SUBMIT_TICKET_MODAL_WITH_EVENT_ID:
                await ticket_modal_callback(custom_id, interaction)
            if event_type == EVENT_TYPE_SUBMIT_CUSTOM_MODAL_WITH_EVENT_ID:
                await custom_modal_callback(custom_id, interaction)
            if event_type == EVENT_TYPE_CREATE_QA_DOC:
                await create_qa_modal_callback(custom_id, interaction, self)
            if event_type == EVENT_TYPE_UPDATE_QA_DOC:
                await update_qa_modal_callback(custom_id, interaction, self)
            if event_type == EVENT_TYPE_DELETE_QA_DOC:
                await delete_qa_modal_callback(custom_id, interaction, self)
        else:
            await super().on_interaction(interaction)

class CogLoader(discord.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.bg_task.start()
        self.sync_channels.start()
        self.send_revision_notifications.start()
        self.update_supported_communities.start()
        self.kick_unverified_users.start()
        self.sync_roles_to_backend.start()
        self.is_first_run = True

    @loop(seconds=30)
    async def bg_task(self):
        sentry_sdk.add_breadcrumb(
            category='bot',
            message='bg_task',
            level='info'
        )
        try:
            bot = self.bot
            guided_flow_cog_pool_by_id = bot.cogs

            cogs_to_add = []
            cogs_to_remove = []
            new_cogs = await generate_all_guided_flow_cogs(self.bot)

            for cog in new_cogs:
                cog_id = cog.__name__
                cog = cog(bot)
                if cog_id not in guided_flow_cog_pool_by_id:
                    cogs_to_add.append(cog)

            for cog in guided_flow_cog_pool_by_id.values():
                if not cog.__cog_name__.startswith('flow-'):
                    continue
                if len(list(filter(lambda x: x.__cog_name__ == cog.__cog_name__, new_cogs))) == 0:
                    cogs_to_remove.append(cog)

            for cog in cogs_to_add:
                print("ADDING COG", cog.__cog_name__)
                bot.add_cog(cog)

            for cog in cogs_to_remove:
                print("REMOVING COG", cog.__cog_name__)
                bot.remove_cog(cog.__cog_name__)
                pending_index = None
                for cmd in bot._pending_application_commands:
                    if cmd.cog is not None and cmd.cog.__cog_name__ == cog.__cog_name__:
                        pending_index = bot._pending_application_commands.index(cmd)
                        break
                if pending_index is not None:
                    # This is required because there is a bug in pycord library that does not automatically
                    # remove removed commands from _pending_application_commands,
                    # and without this line command won't be deleted from guild til bot restart
                    bot._pending_application_commands.pop(pending_index)

            if self.is_first_run or (len(cogs_to_add) > 0 or len(cogs_to_remove) > 0):
                try:
                    await bot.sync_commands()
                except Exception as e:
                    print("ERROR DURING CMD SYNC")
                    traceback.print_exc()
                    self.is_first_run = True

            self.is_first_run = False
        except Exception as e:
            print("Error in bg_task")
            traceback.print_exc()

    @loop(minutes=10)
    async def sync_channels(self):
        sentry_sdk.add_breadcrumb(
            category='bot',
            message='sync_channels',
            level='info'
        )
        start_time = time.time()
        guilds = self.bot.guilds

        for guild in guilds:
            try:
                guild_data = []

                guild_channels_by_id = {}
                for channel in guild.channels:
                    guild_channels_by_id[str(channel.id)] = {
                        'name': channel.name
                    }
                guild_data.append({
                    'id': str(guild.id),
                    'channels_by_id': guild_channels_by_id
                })

                # Make individual HTTP request per each guild due to request overflow
                print("GUILD", guild.id)
                print("SYNCED CHANNEL CNT", len(guild_channels_by_id))

                await sync_all_channels({
                    'guilds': guild_data
                })
            except Exception as e:
                print("Error in sync_channels", guild.id, guild_data)
                traceback.print_exc()

        print("SYNC ALL CHANNELS EXEC TIME --- %s seconds ---" % (time.time() - start_time))

    @loop(minutes=60)
    async def send_revision_notifications(self):
        sentry_sdk.add_breadcrumb(
            category='bot',
            message='send_revision_notifications',
            level='info'
        )
        for guild in self.bot.guilds:
            try:
                await send_all_notifications(guild)
            except:
                traceback.print_exc()
    
    @loop(seconds=60)
    async def update_supported_communities(self):
        sentry_sdk.add_breadcrumb(
            category='bot',
            message='update_supported_communities',
            level='info'
        )
        initialize_all_supported_communities()
        self.bot.initialize_qa_views()

    @loop(minutes=45)
    async def sync_roles_to_backend(self):
        print("ROLE SYNC START")

        existing_users = execute_sql(
            'SELECT id, discord_user_id FROM api_user WHERE discord_user_id IS NOT NULL',
            [])

        user_id_by_discord_id = {}

        for u in existing_users:
            user_id_by_discord_id[u['discord_user_id']] = u['id']

        initialize_all_supported_communities()
        last_error = None
        for community in dict(SUPPORTED_COMMUNITIES).values():
            if community.admin_role_ids:
                try:
                    guild = await self.bot.fetch_guild(community.guild_id * 1)

                    async for member in guild.fetch_members(limit=None):

                        if member.id not in user_id_by_discord_id:
                            continue

                        if member.bot:
                            print("SKIP BOT", member.id)
                            continue

                        role_ids = []

                        for role in member.roles:
                            role_ids.append(role.id)

                        print("UPDATE ROLES", member.id, role_ids)

                        execute_sql("""
                            INSERT INTO api_userroleset (role_ids, community_id, user_id)
                            VALUES (%s, %s, %s)
                            ON CONFLICT (community_id, user_id) 
                            DO 
                               UPDATE SET role_ids = %s
                        """, [
                            role_ids,
                            community.internal_id,
                            user_id_by_discord_id[member.id],
                            role_ids
                        ], fetch=False)

                except Exception as e:
                    print("role sync ERROR")
                    traceback.print_exc()
                    last_error = e

        # if last_error:
        #     raise last_error

    @loop(minutes=60)
    async def kick_unverified_users(self):
        initialize_all_supported_communities()
        last_error = None
        for community in SUPPORTED_COMMUNITIES.values():
            if community.verified_role_id:
                try:
                    guild = await self.bot.fetch_guild(community.guild_id * 1)

                    all_roles = await guild.fetch_roles()
                    role_exists = False

                    for role in all_roles:
                        if role.id == community.verified_role_id:
                            role_exists = True
                            break

                    if not role_exists:
                        print("ROLE DOES NOT EXIST IN COMMUNITY")
                        print(community)
                        continue

                    async for member in guild.fetch_members(limit=None):

                        if member.bot:
                            continue

                        if member.joined_at is None:
                            # Discord API edge case (unknown how to reproduce)
                            continue

                        days = datetime.timedelta(days=community.kick_users_who_joined_but_did_not_verify_after_days,
                                                  hours=community.kick_users_who_joined_but_did_not_verify_after_hours)
                        utcnow = datetime.datetime.utcnow()
                        joined_at = member.joined_at.replace(tzinfo=None)

                        kick_users_ignore_datetime_before_utc = \
                            (community.kick_users_ignore_datetime_before_utc - \
                                community.kick_users_ignore_datetime_before_utc.utcoffset()
                             ).replace(tzinfo=None) \
                                if community.kick_users_ignore_datetime_before_utc is not None \
                                else None

                        if kick_users_ignore_datetime_before_utc is not None \
                                and joined_at < kick_users_ignore_datetime_before_utc:
                            continue

                        if joined_at + days > utcnow:
                            continue

                        has_verified_role = False
                        is_moderator = False
                        for role in member.roles:
                            if role.id == community.verified_role_id:
                                has_verified_role = True
                                break
                        permissions = member.guild_permissions
                        if permissions.manage_guild or permissions.administrator:
                            is_moderator = True

                        if has_verified_role or is_moderator:
                            continue
                        else:
                            print("KICKING " + str(member))
                            await member.kick()
                            EventLogger().track_user_kick(member, community)
                except Exception as e:
                    print("kick ERROR")
                    traceback.print_exc()
                    last_error = e

        # if last_error is not None:
        #     raise last_error

def main():
    print("Starting bot")
    load_dotenv()
    logging.basicConfig()

    # Run discord client
    discord.http.API_VERSION = 9
    bot = BackgroundBot()

    bot.add_cog(Commands(bot))

    bot.add_cog(CogLoader(bot))

    bot.add_cog(FlowCommands(bot))

    bot.run(os.getenv('DISCORD_BOT_TOKEN'))

if __name__ == '__main__':
    main()
