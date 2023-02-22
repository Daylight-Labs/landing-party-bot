import datetime
import discord
import commands_guided_flows
import os

from amplitude import Amplitude, BaseEvent

class EventLogger:

    _event_logger = None
    _amplitude_client = None

    def __new__(cls, *args, **kwargs):
        if cls._event_logger is None:
            print("Logger new")
            cls._event_logger = super(EventLogger, cls).__new__(cls, *args, **kwargs)
            cls._amplitude_client = Amplitude(os.getenv('AMPLITUDE_KEY'))

        return cls._event_logger

    def track_faq_bot_event(self, event_name, event_properties, message):
        self._amplitude_client.track(
            BaseEvent(
                event_type = event_name,
                user_id = str(message.author.id),
                event_properties = event_properties
            )
        )
    
    def track_handler_event(self, handler, interaction_wrapper):
        event_name = None
        if not 'handler_type' in handler:
            return
        else:
            event_name = handler['handler_type']

        event_properties = {}
        user_properties = {}

        if 'event_handler_id' in handler:
            event_properties["event_handler_id"] = str(handler['event_handler_id'])

        if 'flow_event_id' in handler:
            event_properties["flow_event_id"] = str(handler['flow_event_id'])

        if 'guided_flow_step_id' in handler:
            event_properties["guided_flow_step_id"] = str(handler['guided_flow_step_id'])

        if 'guided_flow_id' in handler:
            event_properties["guided_flow_id"] = str(handler['guided_flow_id'])

        if 'show_custom_modal_id' in handler:
            event_properties["show_custom_modal_id"] = str(handler['show_custom_modal_id'])

        if 'show_select_menu_id' in handler:
            event_properties["show_select_menu_id"] = str(handler['show_select_menu_id'])

        if interaction_wrapper.user.id:
            user_properties["discord_user_id"] = str(interaction_wrapper.user.id)
        if interaction_wrapper.user.name:
            user_properties["discord_user_name"] = interaction_wrapper.user.name
        if interaction_wrapper.application_id:
            event_properties["application_id"] = str(interaction_wrapper.application_id)
        if interaction_wrapper.guild.id:
            event_properties["guild_id"] = str(interaction_wrapper.guild.id)
        if interaction_wrapper.channel.id:
            event_properties["channel_id"] = str(interaction_wrapper.channel.id)
        if interaction_wrapper.locale:
            user_properties["locale"] = interaction_wrapper.locale

        if interaction_wrapper.channel:
            if interaction_wrapper.channel.jump_url:
                event_properties["channel_jump_url"] = interaction_wrapper.channel.jump_url
            if interaction_wrapper.channel.name:
                event_properties["channel_name"] = interaction_wrapper.channel.name
            if interaction_wrapper.channel.guild:
                event_properties["guild_name"] = interaction_wrapper.channel.guild.name
                event_properties["guild_jump_url"] = interaction_wrapper.channel.guild.jump_url

        self._amplitude_client.track(
            BaseEvent(
                event_type = event_name,
                user_id = str(interaction_wrapper.user.id),
                event_properties = event_properties,
                user_properties = user_properties
            )
        )

    def track_user_kick(self, user, community):

        event_name = 'KICK_USER'

        event_properties = {}
        user_properties = {}

        if user.id:
            user_properties["discord_user_id"] = str(user.id)
        if user.name:
            user_properties["discord_user_name"] = user.name
        if user.joined_at:
            event_properties["joined_at"] = str(user.joined_at)

        event_properties["guild_id"] = str(community.guild_id)

        if community.kick_users_ignore_datetime_before_utc is not None:
            event_properties["kick_users_ignore_datetime_before_utc"] = \
                str(community.kick_users_ignore_datetime_before_utc)

        if community.kick_users_who_joined_but_did_not_verify_after_days is not None:
            event_properties["kick_users_who_joined_but_did_not_verify_after_days"] = \
                community.kick_users_who_joined_but_did_not_verify_after_days

        if community.kick_users_who_joined_but_did_not_verify_after_hours is not None:
            event_properties["kick_users_who_joined_but_did_not_verify_after_hours"] = \
                community.kick_users_who_joined_but_did_not_verify_after_hours

        if community.verified_role_id is not None:
            event_properties["verified_role_id"] = \
                community.verified_role_id

        self._amplitude_client.track(
            BaseEvent(
                event_type=event_name,
                user_id=str(user.id),
                event_properties=event_properties,
                user_properties=user_properties
            )
        )
