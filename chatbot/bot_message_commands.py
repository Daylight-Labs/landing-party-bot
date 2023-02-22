import logging
from const import REPLY_ANSWER_UPDATED, REPLY_DO_YOU_WANT_TO_DELETE_THIS_QA_PAIR, REPLY_WHAT_IS_CORRECT_ANSWER
from slack_util import post_message_to_slack_event_logs
from utils import check_if_text_contains_question, create_user_if_not_exists
from database import execute_sql
import traceback
import discord
import datetime

from commands_guided_flows import QaDocumentCompletionButton

from event_logger import EventLogger

EVENT_TYPE_QUESTION_WITH_DIRECT_ANSWER = "QUESTION_WITH_DIRECT_ANSWER"
EVENT_TYPE_QUESTION_WITH_POTENTIAL_ANSWERS = "QUESTION_WITH_POTENTIAL_ANSWERS"
EVENT_TYPE_QUESTION_WITHOUT_ANSWER = "QUESTION_WITHOUT_ANSWER"
EVENT_TYPE_QUESTION_PROCESSING_RUNTIME_ERROR = "QUESTION_PROCESSING_RUNTIME_ERROR"

async def is_message_new_answer(bot, message, _community, conversation):
    conversation_bot_messages = list(filter(lambda m: m.author.id == bot.user.id, conversation))
    return len(conversation_bot_messages) == 2 and len(list(filter(lambda m: m.author.id == bot.user.id and m.content == REPLY_WHAT_IS_CORRECT_ANSWER, conversation))) == 1

async def is_message_question(bot, message, _community, conversation):
    return not message.reference

async def handle_message_question(bot, message, _community, conversation):
    qa_view = bot.get_qa_view(_community)
    
    try:
        is_question = check_if_text_contains_question(message.content)
    except:
        return

    create_user_if_not_exists(message.author)

    qa_matches_result = None

    event_type = None

    bot_answer = None
    bot_answer_buttons = []
    slackbot_log = None
    is_spam = False
    is_spam_final_warning = False
    is_spam_kick = False

    logger = EventLogger()

    try:
        qa_matches_result = await qa_view.get_answer_for_question(message.content)
        if qa_matches_result.direct_answer:
            bot_answer = qa_matches_result.direct_answer.answer
            bot_original_q = qa_matches_result.direct_answer.question
            confidence = qa_matches_result.direct_answer.confidence
            question_jump_url = qa_matches_result.direct_answer.question_jump_url
            answer_jump_url = qa_matches_result.direct_answer.answer_jump_url
            slackbot_log = f"\n*Event DIRECT Answer* in community *{_community.display_name}* ({_community.guild_id})\n\nUser Question: {message.content}\n\nBot Trained Question: {bot_original_q} {f'({question_jump_url})' if question_jump_url else ''}\n\nAnswer: {bot_answer}\n\nConfidence: {confidence}"
            related_document_idx = qa_matches_result.direct_answer.doc_idx
            bot_answer_buttons = qa_matches_result.direct_answer.buttons
            is_spam = qa_matches_result.direct_answer.is_spam
            event_type = EVENT_TYPE_QUESTION_WITH_DIRECT_ANSWER
            
            logger.track_faq_bot_event(
                EVENT_TYPE_QUESTION_WITH_DIRECT_ANSWER,
                {
                    "message_id": str(message.id),
                    "message_content": message.content,
                    "bot_answer": bot_answer,
                    "confidence": f"{confidence}",
                    "guild_id": str(message.guild.id)
                },
                message
            )

            if is_spam:
                count_start = datetime.datetime.now() - datetime.timedelta(days=7)

                if count_start < datetime.datetime.fromisoformat('2022-12-02'):
                    count_start = datetime.datetime.fromisoformat('2022-12-02')

                res = execute_sql("SELECT COUNT(*) AS cnt FROM api_eventlog WHERE triggered_by_user_id = %s AND related_qa_document_id = %s AND created_on > %s",
                                  [message.author.id, qa_matches_result.direct_answer.doc_idx,
                                   count_start])

                count = res[0]['cnt'] + 1

                if _community.kick_users_who_sent_spam_times is not None and _community.kick_users_who_sent_spam_times > 0:
                    if _community.kick_users_who_sent_spam_times == count + 1:
                        is_spam_final_warning = True

                    if _community.kick_users_who_sent_spam_times <= count:
                        is_spam_kick = True

        elif len(qa_matches_result.alternative_answers) > 0:
            if is_question:
                slackbot_log = f"\n*Event POSSIBLE Answer* in community *{_community.display_name}* ({_community.guild_id})\n\nQuestion: {message.content}"
                
                potential_answers = {}
                for i, result in enumerate(qa_matches_result.alternative_answers):
                    question_jump_url = result.question_jump_url
                    slackbot_log += f"\n\n Confidence: {result.confidence}\n - Bot Trained Question: {result.question} {f'({question_jump_url})' if question_jump_url else ''}\n - Answer: {result.answer}"
                    potential_answers[f"potential_answer_{i}"] = result.answer
                    potential_answers[f"potential_answer_{i}_confidence"] = result.confidence
                    potential_answers[f"potential_answer_{i}_question"] = result.question

                event_type = EVENT_TYPE_QUESTION_WITH_POTENTIAL_ANSWERS

                event_properties = {
                    "message_id": str(message.id),
                    "message_content": message.content,
                    "potential_answers": potential_answers,
                    "confidence": f"{result.confidence}",
                    "guild_id": str(message.guild.id)
                }
                
                logger.track_faq_bot_event(
                    EVENT_TYPE_QUESTION_WITH_POTENTIAL_ANSWERS,
                    event_properties | potential_answers,
                    message
                )
        else:
            if is_question:
                slackbot_log = f"\n*Event NO Answer* in community *{_community.display_name}* ({_community.guild_id}):\n\nUser Question:{message.content}"
                event_type = EVENT_TYPE_QUESTION_WITHOUT_ANSWER
            
            logger.track_faq_bot_event(
                EVENT_TYPE_QUESTION_WITHOUT_ANSWER,
                {
                    "message_id": str(message.id),
                    "message_content": message.content,
                    "guild_id": str(message.guild.id)
                },
                message
            )
    except Exception as e:
        logging.exception("Error encountered for query: "+str(message.content))
        error_print = traceback.format_exc()

        slackbot_log = f"\n*Event BOT ERROR* in community *{_community.display_name}* ({_community.guild_id}):\n\nUser Question:{message.content}\n\nError: {error_print}"
        event_type = EVENT_TYPE_QUESTION_PROCESSING_RUNTIME_ERROR

    if is_spam_final_warning:
        bot_answer = f'This is a final warning!\n\n{bot_answer}'

    if bot_answer:
        if len(bot_answer_buttons) > 0:
            view = discord.ui.View()
            for b in bot_answer_buttons:
                view.add_item(QaDocumentCompletionButton(
                    b['triggered_flow_id'],
                    b['label'],
                    b['button_style']
                ))
        else:
            view = None
        await message.reply(bot_answer, view=view)

    if is_spam_kick:
        await message.author.kick()

    if event_type == EVENT_TYPE_QUESTION_WITH_DIRECT_ANSWER:
        execute_sql(
            'INSERT INTO api_eventlog (created_on, last_modified_on, type, user_prompt, bot_response, community_id, related_qa_document_id, triggered_by_user_id, slackbot_log, is_spam) VALUES ( NOW(), NOW(), %s, %s, %s, %s, %s, %s, %s, %s )',
            [EVENT_TYPE_QUESTION_WITH_DIRECT_ANSWER, message.content, bot_answer, _community.guild_id,
             related_document_idx, message.author.id, slackbot_log, is_spam],
            fetch=False)
    elif event_type == EVENT_TYPE_QUESTION_WITH_POTENTIAL_ANSWERS:
        execute_sql(
            'INSERT INTO api_eventlog (created_on, last_modified_on, type, user_prompt, bot_response, community_id, related_qa_document_id, triggered_by_user_id, slackbot_log, is_spam) VALUES ( NOW(), NOW(), %s, %s, %s, %s, %s, %s, %s, %s )',
            [EVENT_TYPE_QUESTION_WITH_POTENTIAL_ANSWERS, message.content, bot_answer, _community.guild_id,
             None, message.author.id, slackbot_log, is_spam],
            fetch=False)
    elif event_type == EVENT_TYPE_QUESTION_WITHOUT_ANSWER:
        qa_view.insert_unanswered_question_into_db(message.content, message.author.id)
        execute_sql(
            'INSERT INTO api_eventlog (created_on, last_modified_on, type, user_prompt, bot_response, community_id, related_qa_document_id, triggered_by_user_id, slackbot_log, is_spam) VALUES ( NOW(), NOW(), %s, %s, %s, %s, %s, %s, %s, %s )',
            [EVENT_TYPE_QUESTION_WITHOUT_ANSWER, message.content, "", _community.guild_id, None, message.author.id, slackbot_log, is_spam],
            fetch=False)
    elif event_type == EVENT_TYPE_QUESTION_PROCESSING_RUNTIME_ERROR:
        execute_sql(
            'INSERT INTO api_eventlog (created_on, last_modified_on, type, user_prompt, bot_response, community_id, related_qa_document_id, triggered_by_user_id, slackbot_log, is_spam) VALUES ( NOW(), NOW(), %s, %s, %s, %s, %s, %s, %s, %s )',
            [EVENT_TYPE_QUESTION_PROCESSING_RUNTIME_ERROR, message.content, "", _community.guild_id, None, message.author.id, slackbot_log, is_spam],
            fetch=False)

    if slackbot_log:
        post_message_to_slack_event_logs(slackbot_log,
                                         is_direct_answer=event_type==EVENT_TYPE_QUESTION_WITH_DIRECT_ANSWER)



MESSAGE_COMMANDS = [
    {
        "condition": is_message_question,
        "handler": handle_message_question
    }
]