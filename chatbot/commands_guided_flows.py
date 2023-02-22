import discord
from database import execute_sql
from community import initialize_all_supported_communities, SUPPORTED_COMMUNITIES
import time
import io
import os
import requests
import typing
from discord.ui import InputText, Modal
from api_util import get_entry_point_events, get_event_by_id, API_EVENT_TYPE_GUIDED_FLOW, \
    API_EVENT_HANDLER_TYPE_GUIDED_FLOW_STEP, API_EVENT_TYPE_GUIDED_FLOW_STEP_BUTTON, \
    API_EVENT_HANDLER_TYPE_DELETE_CURRENT_THREAD, get_event_handler_by_id, \
    API_EVENT_HANDLER_TYPE_ARCHIVE_CURRENT_THREAD, API_EVENT_HANDLER_TYPE_INVITE_USERS_TO_CURRENT_THREAD, \
    API_EVENT_HANDLER_TYPE_TRIGGER_CALLBACK, API_EVENT_HANDLER_TYPE_GUIDED_FLOW, \
    API_EVENT_HANDLER_TYPE_SHOW_TICKET_MODAL, API_EVENT_TYPE_PERMANENT_EMBED_BUTTON, \
    API_EVENT_HANDLER_TYPE_INVITE_USERS_WITH_ROLE_TO_CURRENT_THREAD, \
    API_EVENT_HANDLER_TYPE_SHOW_CUSTOM_MODAL, API_EVENT_HANDLER_TYPE_SHOW_SELECT_MENU, \
    add_discord_message_mapping, create_event_record, get_flow_by_id, API_EVENT_HANDLER_TYPE_SHOW_CAPTCHA, \
    create_captcha_challenge, verify_captcha_challenge, API_EVENT_HANDLER_TYPE_GRANT_ROLE
import json
from interaction_wrapper import InteractionWrapper

from event_logger import EventLogger

import traceback

import datetime
import sentry_sdk
import threading

EVENT_TYPE_EVENT = 'EVENT_TYPE_EVENT'
EVENT_TYPE_EVENT_HANDLER = 'EVENT_TYPE_EVENT_HANDLER'
EVENT_TYPE_HELP_FOR_STEP_WITH_EVENT_ID = 'EVENT_TYPE_HELP_FOR_STEP_WITH_EVENT_ID'
EVENT_TYPE_CONTACT_MOD_FOR_STEP_WITH_EVENT_ID = 'EVENT_TYPE_CONTACT_MOD_FOR_STEP_WITH_EVENT_ID'
EVENT_TYPE_INVITATION_TO_FLOW_WITH_EVENT_ID = 'EVENT_TYPE_INVITATION_TO_FLOW_WITH_EVENT_ID'
EVENT_TYPE_APPROVE_ROLE_FOR_STEP_WITH_EVENT_ID = 'EVENT_TYPE_APPROVE_ROLE_FOR_STEP_WITH_EVENT_ID'
EVENT_TYPE_SUBMIT_TICKET_MODAL_WITH_EVENT_ID = 'EVENT_TYPE_SUBMIT_TICKET_MODAL_WITH_EVENT_ID'
EVENT_TYPE_SUBMIT_CUSTOM_MODAL_WITH_EVENT_ID = 'EVENT_TYPE_SUBMIT_CUSTOM_MODAL_WITH_EVENT_ID'
EVENT_TYPE_SUBMIT_SELECT_MENU_WITH_EVENT_ID = 'EVENT_TYPE_SUBMIT_CUSTOM_MODAL_WITH_EVENT_ID'
EVENT_TYPE_CAPTCHA_START = 'EVENT_TYPE_CAPTCHA_START'
EVENT_TYPE_CAPTCHA_VERIFY_ANSWER = 'EVENT_TYPE_CAPTCHA_VERIFY_ANSWER'
EVENT_TYPE_QA_DOCUMENT_COMPLETION_BUTTON_FLOW_ID = 'EVENT_TYPE_QA_DOCUMENT_COMPLETION_BUTTON_FLOW_ID'

def generate_custom_id(event_type: str, extra_data: list[int], callback_ids_sets: list[list[int]]):
    data = [event_type]
    data.extend(extra_data)
    data.append(int(time.time() * 1000))
    data.append(json.dumps(callback_ids_sets).replace(',', ';'))
    print('custom id', data)
    return ','.join(map(str, data))

def parse_custom_id(custom_id: str):
    tokens = custom_id.split(',')
    event_type = tokens[0]
    extra_data = list(map(int, tokens[1:-1]))
    callback_ids_sets = []
    try:
        callback_ids_sets = json.loads(tokens[-1].replace(';', ','))
    except:
        extra_data = list(map(int, tokens[1:]))
        pass
    return (event_type, extra_data, callback_ids_sets)

async def get_all_guided_flows():
    entry_points = await get_entry_point_events()
    flows = list(filter(lambda x: x['event_type'] == API_EVENT_TYPE_GUIDED_FLOW, entry_points))
    return flows

def get_step_files(step_file_db_objects):
    files = []

    for row in step_file_db_objects:
        name = row['name']
        file = row['file']

        url = f'https://bn-bot-storage.s3.amazonaws.com/{file}'

        response = requests.get(url)
        if response.status_code != 200:
            print('file fetch error', url)
            continue
        data = io.BytesIO(response.content)
        files.append(discord.File(data, name))

    return files

async def handle_granted_role(interaction, granted_role_id, granted_role_needs_approval_by):
    guild = interaction.guild

    if granted_role_id is not None:
        print("GRANTING ROLE")
        role = guild.get_role(granted_role_id)
        print("ROLE", role)
        user = interaction.user
        print("USER", user)
        print("ROLE", guild.self_role.permissions.value)
        if len(granted_role_needs_approval_by) == 0:
            if role not in user.roles:
                await user.add_roles(role)
        else:
            view = discord.ui.View()
            view.add_item(ApproveRoleButtonButton(event_handler_id, interaction.user.id))
            for user_id in granted_role_needs_approval_by:
                u = await guild.fetch_member(str(user_id))
                if hasattr(interaction.channel, 'set_permissions'):
                    await interaction.channel.set_permissions(u, read_messages=True)
                else:
                    await interaction.channel.add_user(u)
            await interaction.channel.send(
                ', '.join( map(lambda user_id: f"<@{user_id}>", granted_role_needs_approval_by) ) + \
                f", please approve role <@&{role.id}> being granted to <@{user.id}>",
                view=view)

async def create_view_for_step(interaction, step, callback_ids_sets):
    help_text = step['help_text']
    event_handler_id = step['event_handler_id']
    flow_event_id = step['flow_event_id']
    granted_role_id = step['granted_role_id']
    actions = step['buttons']

    granted_role_needs_approval_by = step['granted_role_needs_approval_by']

    await handle_granted_role(interaction, granted_role_id, granted_role_needs_approval_by)

    view = discord.ui.View()

    unfulfilled_row = 0
    count_by_row = {}

    for action in actions:
        row = action.get('button_row')

        if row is None:
            row = unfulfilled_row
        else:
            row -= 1

        view.add_item(ActionButton(action['button_label'], action['event_id'],
                                   callback_ids_sets,
                                   action['button_style'],
                                   row=row))

        count_by_row[row] = count_by_row.get(row, 0) + 1

        while count_by_row.get(unfulfilled_row, 0) >= 5:
            unfulfilled_row += 1

    if help_text is not None and len(help_text) > 0:
        view.add_item(NeedHelpButton(flow_event_id, event_handler_id))

    return view

def create_view_for_select_menu(select_menu, callback_ids_sets):
    view = discord.ui.View()
    view.add_item(
        CustomSelectMenu(select_menu, callback_ids_sets)
    )
    return view

class CustomSelectMenu(discord.ui.Select):
    def __init__(self, select_menu, callback_ids_sets):
        self.event_id = select_menu['event_id']
        placeholder = select_menu['placeholder']
        min_values = select_menu['min_values']
        max_values = select_menu['max_values']
        options = select_menu['options']

        options = [
                discord.SelectOption(
                    label=opt['label'],
                    description=opt['description']
                )
                for opt
                in options
            ]

        custom_id = generate_custom_id(EVENT_TYPE_SUBMIT_SELECT_MENU_WITH_EVENT_ID, [self.event_id], callback_ids_sets)

        super().__init__(
            custom_id=custom_id,
            placeholder=placeholder,
            min_values=min_values,
            max_values=max_values,
            options=options,
        )

    async def callback(self, interaction: discord.Interaction):
        await create_event_record(
            event_id=self.event_id,
            record_source="select-menu",
            discord_user_id=interaction.user.id,
            discord_user_name=interaction.user.name,
            guild_id=interaction.guild_id,
            channel_id=interaction.channel_id,
            values=self.values)

async def submit_select_menu_callback(custom_id, interaction):
    # Select Menu triggered actions
    await action_button_callback(custom_id, interaction)

    # Select Menu options triggered actions
    (event_type, [id, *_], callback_ids_sets) = parse_custom_id(custom_id)
    event_data = await get_event_by_id(id)

    option_values = interaction.data['values']

    options_data = event_data['options']

    selected_options = list(filter(lambda x: x['label'] in option_values, options_data))

    for opt in selected_options:
        fake_option_id = generate_custom_id(EVENT_TYPE_EVENT, [opt['event_id']], callback_ids_sets)
        await action_button_callback(fake_option_id, interaction)

class CreateTicketModal(Modal):
    def __init__(self, custom_id, title, subject_label, subject_placeholder,
                 describe_label, describe_placeholder, *args, **kwargs) -> None:
        super().__init__(custom_id=custom_id, title=title, *args, **kwargs)
        self.add_item(InputText(label=subject_label, placeholder=subject_placeholder, custom_id='subject'))

        self.add_item(
            InputText(
                label=describe_label,
                placeholder=describe_placeholder,
                style=discord.InputTextStyle.long,
                custom_id='description'
            )
        )

MODAL_FIELD_TYPE_TEXT_INPUT = 'TEXT_INPUT'

MODAL_INPUT_STYLE_SHORT = 'SHORT'
MODAL_INPUT_STYLE_LONG = 'LONG'

class CustomModal(Modal):
    def __init__(self, custom_id, title, fields, event_id, *args, **kwargs) -> None:
        super().__init__(custom_id=custom_id, title=title, *args, **kwargs)

        self.event_id = event_id

        for field in fields:
            self.add_item(
                InputText(
                    label=field['label'],
                    placeholder=field['placeholder'],
                    style=discord.InputTextStyle.long
                        if field['style'] == MODAL_INPUT_STYLE_LONG
                        else discord.InputTextStyle.short,
                    custom_id=f'modal-field-{field["id"]}',
                    min_length=field["min_length"],
                    max_length=field["max_length"],
                    required=field["required"]
                )
            )
    
    async def callback(self, interaction: discord.Interaction):
        answers = {}
        for child in self.children:
            if child.value:
                answers[child.label] = child.value
            else:
                answers[child.label] = None

        await create_event_record(
            event_id=self.event_id,
            record_source="modal",
            discord_user_id=interaction.user.id,
            discord_user_name=interaction.user.name,
            guild_id=interaction.guild_id,
            channel_id=interaction.channel_id,
            values=answers)

TRIGGERED_HANDLER_ORDER_CONFIG = {
    API_EVENT_HANDLER_TYPE_DELETE_CURRENT_THREAD: 999,
    API_EVENT_HANDLER_TYPE_ARCHIVE_CURRENT_THREAD: 999,
}

TRIGGERED_HANDLER_ORDER_OTHER = 0

async def respond_for_triggered_handlers(interaction_wrapper, triggered_handlers, callback_ids_sets, event_data=None):
    channel_prefix = generate_channel_name(interaction_wrapper.user, "")

    is_ephemeral = not interaction_wrapper.channel.name.startswith(channel_prefix)

    triggered_handlers = sorted(triggered_handlers,
                                key=lambda x: TRIGGERED_HANDLER_ORDER_CONFIG.get(x['handler_type'],
                                                                                 TRIGGERED_HANDLER_ORDER_OTHER)
                                )

    for handler in triggered_handlers:
        handler_type = handler['handler_type']

        EventLogger().track_handler_event(handler, interaction_wrapper)

        if handler_type == API_EVENT_HANDLER_TYPE_TRIGGER_CALLBACK:
            if len(callback_ids_sets) > 0:
                callback_set = callback_ids_sets[-1]
                callback_triggered_handlers = []
                for callback_id in callback_set: 
                    callback_triggered_handlers.append(await get_event_handler_by_id(callback_id))
                await respond_for_triggered_handlers(interaction_wrapper, callback_triggered_handlers, callback_ids_sets[:-1])
        if handler_type == API_EVENT_HANDLER_TYPE_GUIDED_FLOW:
            should_create_new_thread = (is_ephemeral and not handler['is_ephemeral']) or \
                                       (event_data is not None and event_data['event_type'] == API_EVENT_TYPE_PERMANENT_EMBED_BUTTON)
            if should_create_new_thread:
                await create_thread_with_flow(ctx=None, user_to_onboard=None, flow=handler,
                                              interaction_wrapper=interaction_wrapper,
                                              auto_archive_duration=handler['auto_archive_duration'],
                                              skip_onboarding_button=True)
            else:
                nested_triggered_handlers = handler['triggered_handlers']
                await respond_for_triggered_handlers(interaction_wrapper, nested_triggered_handlers, callback_ids_sets)
        if handler_type == API_EVENT_HANDLER_TYPE_GUIDED_FLOW_STEP:
            step = handler
            step_text = step["step_text"]

            view = await create_view_for_step(interaction_wrapper, step, callback_ids_sets)
            step_file_db_objects = step['attached_files']

            if len(step_file_db_objects) == 0:
                message = await interaction_wrapper.send_message(step_text, view=view,
                                                                 ephemeral=is_ephemeral)
            else:
                message = await interaction_wrapper.send_message(step_text + "\n\nLoading attachments...", view=view,
                                                                 ephemeral=is_ephemeral)
                files = get_step_files(step_file_db_objects)
                await message.edit(content=step_text, files=files)
            await add_discord_message_mapping(str(message.id), step["guided_flow_step_id"], callback_ids_sets)
        if handler_type == API_EVENT_HANDLER_TYPE_GRANT_ROLE:
            granted_role_id = handler['granted_role_id']
            granted_role_needs_approval_by = handler['granted_role_needs_approval_by']
            await handle_granted_role(interaction_wrapper, granted_role_id, granted_role_needs_approval_by)
        if handler_type == API_EVENT_HANDLER_TYPE_DELETE_CURRENT_THREAD:
            await interaction_wrapper.channel.delete()
        if handler_type == API_EVENT_HANDLER_TYPE_ARCHIVE_CURRENT_THREAD:
            if hasattr(interaction_wrapper.channel, 'archive'):
                await interaction_wrapper.channel.archive()
            else:
                await interaction_wrapper.channel.delete()
        if handler_type == API_EVENT_HANDLER_TYPE_SHOW_TICKET_MODAL:
            await interaction_wrapper.interaction.response.send_modal(
                CreateTicketModal(custom_id=generate_custom_id(EVENT_TYPE_SUBMIT_TICKET_MODAL_WITH_EVENT_ID,
                                                               [ handler['event_id'] ],
                                                               callback_ids_sets),
                                  title=handler.get('modal_title', "Create a ticket"),
                                  subject_label=handler.get('subject_label', 'Subject'),
                                  subject_placeholder=handler.get('subject_placeholder', 'Subject'),
                                  describe_label=handler.get('describe_label', "Please describe your issue"),
                                  describe_placeholder=handler.get('describe_placeholder', "Please describe your issue")
                                  ))
        if handler_type == API_EVENT_HANDLER_TYPE_SHOW_CUSTOM_MODAL:
            await interaction_wrapper.interaction.response.send_modal(
                CustomModal(custom_id=generate_custom_id(EVENT_TYPE_SUBMIT_CUSTOM_MODAL_WITH_EVENT_ID,
                                                               [handler['event_id']],
                                                               callback_ids_sets),
                            title=handler['title'],
                            fields=handler['fields'],
                            event_id=handler['event_id']))
        if handler_type == API_EVENT_HANDLER_TYPE_SHOW_SELECT_MENU:
            view = create_view_for_select_menu(handler, callback_ids_sets)
            await interaction_wrapper.send_message(handler['message_text'], view=view,
                                                   ephemeral=is_ephemeral)
        if handler_type == API_EVENT_HANDLER_TYPE_INVITE_USERS_TO_CURRENT_THREAD:
            user_ids = handler['users_ids_to_invite']
            guild = interaction_wrapper.guild
            for user_id in user_ids:
                u = await guild.fetch_member(str(user_id))
                if hasattr(interaction_wrapper.channel, 'set_permissions'):
                    await interaction_wrapper.channel.set_permissions(u, read_messages=True)
                else:
                    await interaction_wrapper.channel.add_user(u)
        if handler_type == API_EVENT_HANDLER_TYPE_INVITE_USERS_WITH_ROLE_TO_CURRENT_THREAD:
            role_id = handler['role_id']
            guild = interaction_wrapper.guild
            role = guild.get_role(role_id)
            if hasattr(interaction_wrapper.channel, 'set_permissions'):
                await interaction_wrapper.channel.set_permissions(role, read_messages=True)
            else:
                for member in guild.members:
                    if role in member.roles:
                        await interaction_wrapper.channel.add_user(member)
        if handler_type == API_EVENT_HANDLER_TYPE_SHOW_CAPTCHA:
            message_text = "Solve the equation show in the image below and then click on the button to verify your answer\n\n" + \
                " - The equation will either be addition or subtraction.\n" + \
                " - If you’re having trouble viewing the captcha, you can regenerate the captcha by clicking “Begin captcha” again.\n" + \
                " - You have 5 tries to complete the captcha.\n"

            verify_button_label = "Verify answer"

            if handler.get('captcha_message'):
                message_text = handler.get('captcha_message')

            if handler.get('verify_button_text'):
                verify_button_label = handler.get('verify_button_text')

            captcha_type = handler["captcha_type"]

            message = await interaction_wrapper.send_message(message_text,
                                                             ephemeral=is_ephemeral)

            response = await create_captcha_challenge(captcha_type)
            image_url = response["image"]
            captcha_request_id = response["id"]
            
            response = requests.get(image_url)
            if response.status_code != 200:
                print('file fetch error', image_url)
                message = await message.edit(content="Ups. Something went wrong")
                return

            data = io.BytesIO(response.content)

            view = discord.ui.View()
            view.add_item(CaptchaButton(handler['event_id'], callback_ids_sets, captcha_request_id,
                                        verify_button_label))

            message = await message.edit(content=message_text, view=view,
                                         file=discord.File(data, "captcha.png"))

class CaptchaButton(discord.ui.Button):
    def __init__(self, step_event_handler_id: int, callback_ids_sets, captcha_request_id, label):
        super().__init__(style=discord.ButtonStyle.secondary, label=label, row=0)
        self.step_event_id = step_event_handler_id
        self.custom_id = generate_custom_id(EVENT_TYPE_CAPTCHA_START,
                                            [step_event_handler_id, captcha_request_id],
                                            callback_ids_sets)

async def verify_captcha(custom_id: str, interaction: discord.Interaction):
    (event_type, values, callback_ids_sets) = parse_custom_id(custom_id)
    new_custom_id = generate_custom_id(
        EVENT_TYPE_CAPTCHA_VERIFY_ANSWER,
        values,
        callback_ids_sets
    )
    await interaction.response.send_modal(CaptchaVerifyModal(new_custom_id, "Captcha Answer"))

class CaptchaVerifyModal((Modal)):
    def __init__(self, custom_id, title, *args, **kwargs) -> None:
        super().__init__(custom_id=custom_id, title=title, *args, **kwargs)
        self.add_item(InputText(label="Answer", placeholder="Please put your answer here", custom_id=custom_id))

    async def callback(self, interaction: discord.Interaction):
        (_, [step_event_handler_id, captcha_request_id, *_], _) = parse_custom_id(interaction.custom_id)

        channel_prefix = generate_channel_name(interaction.user, "")
        
        is_ephemeral = not interaction.channel.name.startswith(channel_prefix)

        response = await verify_captcha_challenge(captcha_request_id, interaction.user.id, self.children[0].value)
        if response["success"]:
            # await interaction.response.send_message("Success")
            await action_button_callback(interaction.custom_id, interaction)
        elif response["failure_count"] > 4:
            await interaction.user.kick()
        else:
            await interaction.response.send_message("Wrong answer. Please try again", ephemeral=is_ephemeral)

class ApproveRoleButtonButton(discord.ui.Button):
    def __init__(self, step_event_handler_id: int, user_id: int):
        super().__init__(style=discord.ButtonStyle.secondary, label="Approve Role", row=0)
        self.step_event_id = step_event_handler_id
        self.custom_id = generate_custom_id(EVENT_TYPE_APPROVE_ROLE_FOR_STEP_WITH_EVENT_ID,
                                            [step_event_handler_id, user_id],
                                            callback_ids_sets=[])

async def approve_role_callback(custom_id: str, interaction: discord.Interaction):
    (_, [step_event_handler_id, user_id, *_], _) = parse_custom_id(custom_id)

    step = await get_event_handler_by_id(step_event_handler_id)
    granted_role_needs_approval_by = step['granted_role_needs_approval_by']
    granted_role_id = step['granted_role_id']

    if interaction.user.id not in granted_role_needs_approval_by:
        return await interaction.response.send_message("You don't have permission to do this", ephemeral=True)

    guild = interaction.guild

    user = await guild.fetch_member(user_id)

    role = guild.get_role(granted_role_id)
    if role not in user.roles:
        await user.add_roles(role)

    await interaction.response.send_message(f"<@{interaction.user.id}> approved role <@&{role.id}> granted to <@{user.id}>",
                                            ephemeral=False)


class ContactModeratorsButton(discord.ui.Button):
    def __init__(self, flow_event_id: int, step_event_handler_id: int):
        super().__init__(style=discord.ButtonStyle.secondary, label="Not helpful?", row=0)
        self.flow_event_id = flow_event_id
        self.step_event_id = step_event_handler_id
        self.custom_id = generate_custom_id(EVENT_TYPE_CONTACT_MOD_FOR_STEP_WITH_EVENT_ID,
                                            [step_event_handler_id, flow_event_id],
                                            callback_ids_sets=[])

async def contact_mod_callback(custom_id: str, interaction: discord.Interaction):
    (_, [step_event_handler_id, flow_event_id,*_], _) = parse_custom_id(custom_id)

    flow = await get_event_by_id(flow_event_id)

    user_ids = flow['moderators_to_contact']

    if len(user_ids) == 1:
        message = f"Please contact moderator <@{user_ids[0]}>"
    else:
        message = 'Please contact any moderator from the list: ' +', '.join( map(lambda user_id: f"<@{user_id}>", user_ids) )

    view = discord.ui.View()
    view.add_item(ActionButton("Go Back", None, 1, step_event_handler_id))

    await interaction.response.send_message(message, ephemeral=False, view=view)

class NeedHelpButton(discord.ui.Button):
    def __init__(self, flow_event_id: int, step_event_handler_id: int):
        super().__init__(style=discord.ButtonStyle.secondary, label="Need Help", row=0)
        self.flow_event_id = flow_event_id
        self.step_event_handler_id = step_event_handler_id
        self.custom_id = generate_custom_id(EVENT_TYPE_HELP_FOR_STEP_WITH_EVENT_ID,
                                            [step_event_handler_id, flow_event_id],
                                            callback_ids_sets=[])

async def need_help_callback(custom_id: str, interaction: discord.Interaction):
    (_, [step_event_handler_id, flow_event_id,*_], _) = parse_custom_id(custom_id)

    view = discord.ui.View()

    view.add_item(ActionButton("Go Back", None, 1, step_event_handler_id))
    view.add_item(ContactModeratorsButton(flow_event_id, step_event_handler_id))

    step = await get_event_handler_by_id(step_event_handler_id)

    await interaction.response.send_message(step['help_text'], view=view, ephemeral=False)

class ActionButton(discord.ui.Button):
    def __init__(self, button_label: str,
                 event_id: typing.Optional[int],
                 callback_ids_sets: list[list[int]],
                 button_style: int,
                 event_handler_id: typing.Optional[int] = None,
                 row: int = 0):
        super().__init__(style=button_style, label=button_label, row=row)
        self.event_id = event_id
        self.event_handler_id = event_handler_id
        if event_id is not None:
            self.custom_id = generate_custom_id(EVENT_TYPE_EVENT, [event_id], callback_ids_sets)
        if event_handler_id is not None:
            self.custom_id = generate_custom_id(EVENT_TYPE_EVENT_HANDLER, [event_handler_id], callback_ids_sets)

async def action_button_callback(custom_id: str, interaction: discord.Interaction):
    (event_type, [id,*_], callback_ids_sets) = parse_custom_id(custom_id)
    if event_type in [EVENT_TYPE_EVENT, EVENT_TYPE_SUBMIT_TICKET_MODAL_WITH_EVENT_ID,
                      EVENT_TYPE_SUBMIT_CUSTOM_MODAL_WITH_EVENT_ID,
                      EVENT_TYPE_SUBMIT_SELECT_MENU_WITH_EVENT_ID,
                      EVENT_TYPE_CAPTCHA_VERIFY_ANSWER]:
        sentry_sdk.add_breadcrumb(
                category='bot',
                message='action_button_callback_1',
                level='info',
                data={
                    "latency":'{0}'.format(interaction.client.latency),
                    "id": interaction.id,
                    "type": interaction.type,
                    "custom_id": interaction.custom_id,
                    "event_type": event_type,
                    "is_done": interaction.response.is_done(),
                    "current_time":'{0}'.format(datetime.datetime.now()),
                    "threading.active_count()": threading.active_count()
                }
            )
        event_data = await get_event_by_id(id)
        sentry_sdk.add_breadcrumb(
                category='bot',
                message='action_button_callback_2',
                level='info',
                data={
                    "latency":'{0}'.format(interaction.client.latency),
                    "id": interaction.id,
                    "type": interaction.type,
                    "custom_id": interaction.custom_id,
                    "event_type": event_type,
                    "is_done": interaction.response.is_done(),
                    "current_time":'{0}'.format(datetime.datetime.now()),
                    "threading.active_count()": threading.active_count()
                }
            )
        triggered_handlers = event_data["triggered_handlers"]
        handler_callbacks = event_data["handler_callbacks"]
        if len(handler_callbacks) > 0:
            new_callback_set = []
            for new_callback in handler_callbacks:
                new_callback_set.append(new_callback['event_handler_id'])
            callback_ids_sets.append(new_callback_set)
        interaction_wrapper = InteractionWrapper(interaction=interaction)
        await respond_for_triggered_handlers(interaction_wrapper, triggered_handlers, callback_ids_sets, event_data=event_data)
    if event_type == EVENT_TYPE_EVENT_HANDLER:
        triggered_handler = await get_event_handler_by_id(id)
        interaction_wrapper = InteractionWrapper(interaction=interaction)
        await respond_for_triggered_handlers(interaction_wrapper, [triggered_handler], callback_ids_sets)

class OnboardingInvitationButton(discord.ui.Button):
    def __init__(self, event_id: int, flow_label: str):
        super().__init__(style=discord.ButtonStyle.primary, label=f"Start {flow_label}", row=0)
        self.event_id = event_id
        self.custom_id = generate_custom_id(EVENT_TYPE_INVITATION_TO_FLOW_WITH_EVENT_ID,
                                            [event_id],
                                            callback_ids_sets=[])

class QaDocumentCompletionButton(discord.ui.Button):
    def __init__(self, flow_id: int, label: str, button_style: int):
        super().__init__(style=button_style, label=label, row=0)
        self.custom_id = generate_custom_id(EVENT_TYPE_QA_DOCUMENT_COMPLETION_BUTTON_FLOW_ID,
                                            [flow_id],
                                            callback_ids_sets=[])

async def qa_document_completion_button_callback(custom_id: str, interaction: discord.Interaction):
    (_, [flow_id, *_], _) = parse_custom_id(custom_id)

    event_handler = await get_flow_by_id(flow_id)

    interaction_wrapper = InteractionWrapper(interaction=interaction)

    await create_thread_with_flow(ctx=None, user_to_onboard=None, flow=event_handler,
                                  interaction_wrapper=interaction_wrapper,
                                  auto_archive_duration=event_handler['auto_archive_duration'],
                                  skip_onboarding_button=True)

async def ticket_modal_callback(custom_id: str, interaction: discord.Interaction):

    (_, [event_id, *_], _) = parse_custom_id(custom_id)

    event_data = await get_event_by_id(event_id)

    embed = discord.Embed(color=discord.Color.random())
    subj = interaction.data['components'][0]['components'][0]['value']
    desc = interaction.data['components'][1]['components'][0]['value']
    embed.add_field(name=event_data.get('subject_label', 'Subject'), value=subj, inline=False)
    embed.add_field(name=event_data.get('describe_label', 'Description'), value=desc, inline=False)
    await interaction.response.send_message(embeds=[embed])  # embeds=[embed])

    await action_button_callback(custom_id, interaction)

async def custom_modal_callback(custom_id: str, interaction: discord.Interaction):
    await action_button_callback(custom_id, interaction)

async def invitation_callback(custom_id: str, interaction: discord.Interaction, interaction_wrapper = None):
    user_to_onboard = interaction.user

    (_, [event_id, *_], _) = parse_custom_id(custom_id)

    guild_id = interaction.guild_id

    if event_id is None:
        return

    event_data = await get_event_by_id(event_id)

    triggered_handlers = event_data["triggered_handlers"]
    handler_callbacks = event_data["handler_callbacks"]
    handler_callbacks = list(map(lambda x: x['event_handler_id'], handler_callbacks))

    if interaction_wrapper is None:
        interaction_wrapper = InteractionWrapper(interaction=interaction)
    await respond_for_triggered_handlers(interaction_wrapper, triggered_handlers,
                                         [handler_callbacks] if len(handler_callbacks) > 0 else [])

def generate_channel_name(user, channel_name_suffix, channels=None):
    user_name = ''.join(filter(lambda c: c.isalnum(), user.name))
    basename = f'{user_name}-{channel_name_suffix}'.lower()

    if channels is None:
        return basename

    existing_channel_names = list(filter(lambda name: name.startswith(basename), map(lambda c: c.name, channels)))

    if len(existing_channel_names) == 0:
        return basename

    largest_existing_channel_index = 0

    for name in existing_channel_names:
        if name == basename:
            largest_existing_channel_index = max(1, largest_existing_channel_index)
            continue

        name_index = name[len(basename)+1:]
        if not name_index.isnumeric():
            continue

        largest_existing_channel_index = max(int(name_index), largest_existing_channel_index)

    if largest_existing_channel_index == 0:
        return basename

    return f'{basename}-{largest_existing_channel_index+1}'

async def create_thread_with_flow(ctx, user_to_onboard, flow, interaction_wrapper=None, auto_archive_duration=1440,
                                  skip_onboarding_button=False):

    if interaction_wrapper is None:
        interaction_wrapper = InteractionWrapper(interaction=ctx.interaction)

    guild_id = interaction_wrapper.guild.id
    guild = interaction_wrapper.guild

    flow_label = flow['flow_label']
    channel_name_suffix = flow['channel_name']
    event_id = flow['event_id']

    user_to_onboard_explicitly_provided = user_to_onboard is not None and interaction_wrapper.user.id != user_to_onboard.id

    is_ephemeral = flow['is_ephemeral']

    print("user_to_onboard_explicitly_provided", user_to_onboard_explicitly_provided)
    print("is_ephemeral", is_ephemeral)
    if user_to_onboard:
        print(interaction_wrapper.user.id, user_to_onboard.id)

    if not user_to_onboard_explicitly_provided:
        user_to_onboard = interaction_wrapper.user

    bot_user = guild.me

    community = SUPPORTED_COMMUNITIES[guild_id]

    channel = interaction_wrapper.channel

    if is_ephemeral and not user_to_onboard_explicitly_provided:
        view = discord.ui.View()
        invite_btn = OnboardingInvitationButton(event_id, flow_label)
        custom_id = invite_btn.custom_id
        await invitation_callback(custom_id, interaction_wrapper.interaction)
    elif guild.premium_tier >= 2:

        if hasattr(channel, 'parent'):
            channel = channel.parent
        else:
            channel = channel

        channel_name = generate_channel_name(user_to_onboard, channel_name_suffix, guild.threads)

        thread = await channel.create_thread(name=channel_name,
                                             type=discord.ChannelType.private_thread,
                                             auto_archive_duration=1440)

        await thread.add_user(user_to_onboard)

        if not user_to_onboard_explicitly_provided:
            message = f"<@{user_to_onboard.id}>, please go to <#{thread.id}>"
            ephemeral = True
        else:
            message = f"<@{user_to_onboard.id}>, you are invited to start {flow_label} in <#{thread.id}>"
            ephemeral = False

        message = await interaction_wrapper.send_message(message, ephemeral=ephemeral)

        button = OnboardingInvitationButton(event_id, flow_label)

        if skip_onboarding_button:
            custom_id = button.custom_id
            interaction_wrapper.override_channel(thread)
            await invitation_callback(custom_id, interaction_wrapper.interaction, interaction_wrapper=interaction_wrapper)
        else:
            view = discord.ui.View()
            view.add_item(button)
            await thread.send("", view=view)

    else:
        channel_name = generate_channel_name(user_to_onboard, channel_name_suffix, guild.channels)
        channel = None
        for c in guild.channels:
            if c.name == channel_name:
                channel = c
                break

        if channel is None:
            overwrites = {
                guild.default_role: discord.PermissionOverwrite(read_messages=False),
                user_to_onboard: discord.PermissionOverwrite(read_messages=True),
                bot_user: discord.PermissionOverwrite(read_messages=True)
            }
            channel = await guild.create_text_channel(channel_name, overwrites=overwrites)

        if not user_to_onboard_explicitly_provided:
            message = f"<@{user_to_onboard.id}>, please go to <#{channel.id}>"
            ephemeral = True
        else:
            message = f"<@{user_to_onboard.id}>, you are invited to start {flow_label} in <#{channel.id}>"
            ephemeral = False

        await interaction_wrapper.send_message(message, ephemeral=ephemeral)

        button = OnboardingInvitationButton(event_id, flow_label)

        if skip_onboarding_button:
            custom_id = button.custom_id
            interaction_wrapper.override_channel(channel)
            await invitation_callback(custom_id, interaction_wrapper.interaction, interaction_wrapper=interaction_wrapper)
        else:
            view = discord.ui.View()
            view.add_item(button)
            await channel.send("", view=view)

def generate_cog_for_guided_flow(flow):
    event_id = flow['event_id']
    flow_id = flow['flow_id']
    command_name = flow['slash_command_name']
    guild_ids = flow['guild_ids']
    flow_label = flow['flow_label']
    is_ephemeral = '1' if flow['is_ephemeral'] else '0'
    channel_name_suffix = flow['channel_name']
    auto_archive_duration = flow['auto_archive_duration']

    class CommandsGuidedFlows(discord.Cog):

        def __init__(self, bot):
            self.bot = bot

        @discord.slash_command(name=command_name, description=f"Start {flow_label} process",
                               guild_ids=guild_ids
                               )
        async def onboard(self,
                          ctx,
                          user: discord.commands.Option(discord.Member,
                                                        f"(optional) Select user to start {flow_label} for (mod only)",
                                                        required=False)
                          ):
            guild_id = ctx.interaction.guild_id
            community = SUPPORTED_COMMUNITIES[guild_id]

            is_admin = community.user_has_admin_access(ctx.interaction.user)

            user_to_onboard = None

            if user is None:
                user_to_onboard = ctx.interaction.user
            else:
                if is_admin:
                    user_to_onboard = user

                else:
                    await ctx.respond(f'Sorry, you don\'t have permissions to do this!')
                    return

            await create_thread_with_flow(ctx, user_to_onboard, flow, auto_archive_duration=auto_archive_duration,
                                          skip_onboarding_button=ctx.interaction.user.id == user_to_onboard.id)

    CommandsGuidedFlows.__name__ = f"flow-{flow_id}-{command_name}-{guild_ids[0]}-{flow_label}-{is_ephemeral}"
    CommandsGuidedFlows.__cog_name__ = CommandsGuidedFlows.__name__

    return CommandsGuidedFlows

async def generate_all_guided_flow_cogs(bot):
    has_proper_guild_permission_cache = {}

    async def check_has_proper_guild_permission(guild_id):
        if guild_id in has_proper_guild_permission_cache:
            return has_proper_guild_permission_cache[guild_id]
        else:
            try:
                guild = await bot.fetch_guild(guild_id * 1)
            except:
                has_proper_guild_permission_cache[guild_id] = False
                return has_proper_guild_permission_cache[guild_id]

            if bot.user is None:
                member = None
            else:
                member = await guild.fetch_member(bot.user.id)
            # Check permissions
            if member is None or not member.guild_permissions.use_application_commands:
                has_proper_guild_permission_cache[guild_id] = False
                return has_proper_guild_permission_cache[guild_id]

            # Check scopes
            # https://stackoverflow.com/a/71308859
            url = f"https://discord.com/api/v10/applications/{bot.application_id}/guilds/{guild_id}/commands"

            # For authorization, you can use either your bot token
            headers = {
                "Authorization": f"Bot {os.getenv('DISCORD_BOT_TOKEN')}"
            }

            r = requests.get(url, headers=headers)

            print("REQ", guild_id, r.status_code)

            if r.status_code != 200:
                has_proper_guild_permission_cache[guild_id] = False
                return has_proper_guild_permission_cache[guild_id]

            has_proper_guild_permission_cache[guild_id] = True
            return has_proper_guild_permission_cache[guild_id]



    cogs = []
    for flow in await get_all_guided_flows():
        if flow['slash_command_name'] is None or len(flow['slash_command_name']) == 0:
            continue
        guild_ids = flow['guild_ids']

        has_permissions = True
        for guild_id in guild_ids:

            has_permissions = await check_has_proper_guild_permission(guild_id)

            if not has_permissions:
                print("INVALID PERMISSIONS FOR GUILD " + guild_id)
                break

        if has_permissions:
            try:
                cogs.append( generate_cog_for_guided_flow(flow) )
            except Exception as e:
                print("generate_cog_for_guided_flow error:")
                print(flow)
                print(e)
    return cogs