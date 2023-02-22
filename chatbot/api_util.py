import os
import requests
import json
import sentry_sdk
import aiohttp

BACKEND_URL = os.environ['BACKEND_URL']

API_CHATBOT_AUTH_TOKEN = os.environ['CHATBOT_API_AUTH_TOKEN']

OPENAI_API_KEY = os.environ['OPENAI_API_KEY']

API_EVENT_TYPE_GUIDED_FLOW = 'EVENT_TYPE_GUIDED_FLOW'
API_EVENT_TYPE_GUIDED_FLOW_STEP_BUTTON = 'EVENT_TYPE_GUIDED_FLOW_STEP_BUTTON'
API_EVENT_TYPE_PERMANENT_EMBED_BUTTON = 'EVENT_TYPE_PERMANENT_EMBED_BUTTON'
API_EVENT_TYPE_SHOW_TICKET_MODAL = 'EVENT_HANDLER_TYPE_SHOW_TICKET_MODAL'
API_EVENT_TYPE_SHOW_CUSTOM_MODAL = 'EVENT_HANDLER_TYPE_SHOW_CUSTOM_MODAL'
API_EVENT_TYPE_SHOW_SELECT_MENU = 'EVENT_HANDLER_TYPE_SHOW_SELECT_MENU'

API_EVENT_HANDLER_TYPE_GUIDED_FLOW_STEP = 'EVENT_HANDLER_TYPE_GUIDED_FLOW_STEP'
API_EVENT_HANDLER_TYPE_GRANT_ROLE = 'EVENT_HANDLER_TYPE_GRANT_ROLE'
API_EVENT_HANDLER_TYPE_DELETE_CURRENT_THREAD = 'EVENT_HANDLER_TYPE_DELETE_CURRENT_THREAD'
API_EVENT_HANDLER_TYPE_ARCHIVE_CURRENT_THREAD = 'EVENT_HANDLER_TYPE_ARCHIVE_CURRENT_THREAD'
API_EVENT_HANDLER_TYPE_INVITE_USERS_TO_CURRENT_THREAD = 'EVENT_HANDLER_TYPE_INVITE_USERS_TO_CURRENT_THREAD'
API_EVENT_HANDLER_TYPE_TRIGGER_CALLBACK = 'EVENT_HANDLER_TYPE_TRIGGER_CALLBACK'
API_EVENT_HANDLER_TYPE_GUIDED_FLOW = API_EVENT_TYPE_GUIDED_FLOW
API_EVENT_HANDLER_TYPE_SHOW_TICKET_MODAL = API_EVENT_TYPE_SHOW_TICKET_MODAL
API_EVENT_HANDLER_TYPE_SHOW_SELECT_MENU = API_EVENT_TYPE_SHOW_SELECT_MENU
API_EVENT_HANDLER_TYPE_SHOW_CUSTOM_MODAL = API_EVENT_TYPE_SHOW_CUSTOM_MODAL
API_EVENT_HANDLER_TYPE_INVITE_USERS_WITH_ROLE_TO_CURRENT_THREAD = \
    'EVENT_HANDLER_TYPE_INVITE_USERS_WITH_ROLE_TO_CURRENT_THREAD'
API_EVENT_HANDLER_TYPE_SHOW_CAPTCHA = 'EVENT_HANDLER_TYPE_SHOW_CAPTCHA'

async def get_entry_point_events():
    async with aiohttp.ClientSession() as session:
        response = await session.get(BACKEND_URL + '/api/events/entry-points', headers={'auth': API_CHATBOT_AUTH_TOKEN})
        return await response.json()

async def sync_all_channels(data):
    async with aiohttp.ClientSession() as session:
        response = await session.post(
            BACKEND_URL + '/api/sync_all_channels',
            json=data,
            headers={
                'auth': API_CHATBOT_AUTH_TOKEN,
                'Content-Type': 'application/json'})
        return await response.json()
    

async def get_event_by_id(event_id):
    async with aiohttp.ClientSession() as session:
        sentry_sdk.add_breadcrumb(
            category='bot',
            message='get_event_by_id_before_request',
            level='info',
            data={
                "event_id": event_id
            }
        )
        response = await session.get(BACKEND_URL + f'/api/events/{event_id}', headers={'auth': API_CHATBOT_AUTH_TOKEN})
        sentry_sdk.add_breadcrumb(
            category='bot',
            message='get_event_by_id_after_request',
            level='info',
            data={
                "event_id": event_id
            }
        )
        return await response.json()


async def get_event_handler_by_id(event_handler_id):
    async with aiohttp.ClientSession() as session:
        response = await session.get(BACKEND_URL + f'/api/event_handlers/{event_handler_id}', headers={'auth': API_CHATBOT_AUTH_TOKEN})
        return await response.json()

async def get_flow_by_id(flow_id):
    # TODO: Start refactor from here
    async with aiohttp.ClientSession() as session:
        response = await session.get(BACKEND_URL + f'/api/get_flow_by_id/{flow_id}', headers={'auth': API_CHATBOT_AUTH_TOKEN})
        return await response.json()

async def get_permanent_embed_by_channel_id(channel_id):
    async with aiohttp.ClientSession() as session:
        response = await session.get(BACKEND_URL + f'/api/permanent_embed/{channel_id}', headers={'auth': API_CHATBOT_AUTH_TOKEN})
        return await response.json()

async def get_first_message_mapping_in_message_id_list(message_id_list):
    async with aiohttp.ClientSession() as session:
        response = await session.post(
            BACKEND_URL + f'/api/get_discord_message_mapping/list',
            json={'message_id_list': message_id_list},
            headers={'auth': API_CHATBOT_AUTH_TOKEN,
            'Content-Type': 'application/json'})
        return await response.json()

async def add_discord_message_mapping(message_id, flow_step_id, callback_ids_sets):
    async with aiohttp.ClientSession() as session:
        response = await session.post(
            BACKEND_URL + f'/api/add_discord_message_mapping/{message_id}',
            json={
                'flow_step_id': flow_step_id,
                'callback_ids_sets': callback_ids_sets
            },
            headers={
                'auth': API_CHATBOT_AUTH_TOKEN,
                'Content-Type': 'application/json'
            })
        return await response.json()

async def add_user_file_upload(filename, file_url, discord_user_id, discord_username, flow_step_id):
    async with aiohttp.ClientSession() as session:
        response = await session.post(
            BACKEND_URL + f'/api/add_user_file_upload',
            json={
                'filename': filename,
                'file_url': file_url,
                'discord_user_id': discord_user_id,
                'flow_step_id': flow_step_id,
                'discord_username': discord_username
            },
            headers={
                'auth': API_CHATBOT_AUTH_TOKEN,
                'Content-Type': 'application/json'})
        return await response.json()

async def create_event_record(event_id: str, record_source: str, discord_user_id: str,
                        discord_user_name: str,
                        guild_id: str, channel_id: str, values: object):
    async with aiohttp.ClientSession() as session:
        response = await session.post(
            BACKEND_URL + f'/api/event_records/',
            json={
                "source": record_source,
                "discord_user_id": discord_user_id,
                "discord_user_name": discord_user_name,
                "guild_id": guild_id,
                "channel_id": channel_id,
                "record": values,
                "event": event_id
            },
            headers={
                'auth': API_CHATBOT_AUTH_TOKEN,
                'Content-Type': 'application/json'
            })
        return await response.json()


async def create_captcha_challenge(captcha_type: str):
    async with aiohttp.ClientSession() as session:
        response = await session.post(
            BACKEND_URL + '/api/create-captcha-challenge',
            json={"captcha_type":captcha_type},
            headers={'auth': API_CHATBOT_AUTH_TOKEN})
        return await response.json()

async def verify_captcha_challenge(request_id: str, discord_user_id: str,  answer: str):
    async with aiohttp.ClientSession() as session:
        response = await session.post(
            BACKEND_URL + f'/api/verify-captcha-challenge/{request_id}/{discord_user_id}',
            json={
                "answer": answer
            },
            headers={
                'auth': API_CHATBOT_AUTH_TOKEN,
                'Content-Type': 'application/json'
            })

        return await response.json()

async def get_embeddings(text: str, model: str):
    async with aiohttp.ClientSession() as session:
            response = await session.post(
                "https://api.openai.com/v1/embeddings", 
                json={
                    "input": text,
                    "model": model
                },
                headers={
                    'Content-Type': 'application/json',
                    'Authorization': f"Bearer {OPENAI_API_KEY}"
                })
            return await response.json()