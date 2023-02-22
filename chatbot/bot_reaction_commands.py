import logging
from const import REPLY_WHAT_IS_CORRECT_ANSWER, REPLY_ANSWER_UPDATED, EMOJIS_YES, EMOJIS_NO

async def is_reaction_mark_as_answer(bot, emoji, message, _community, conversation):
    bot_conversation_depth = len(list(filter(lambda m: m.author.id == bot.user.id, conversation)))
    return bot_conversation_depth == 0 and emoji in EMOJIS_YES and message.author.id != bot.user.id
    
async def handle_reaction_mark_as_answer(bot, message, _community, conversation):
    # Ensure this message is a reply
    if message.reference is None:
        return
    
    # Fetch the parent message 
    question_message = await bot.get_reference_message(message)

    # Get the QAView for the current guild
    qa_view = bot.get_qa_view(_community)
    if not qa_view:
        return
    
    # Insert question and answer into database
    await qa_view.insert_qa_pair_into_db(question_message.content, message.content,
                                   question_message.author, message.author,
                                   question_jump_url=question_message.jump_url,
                                   answer_jump_url=message.jump_url)
    await message.add_reaction('✅')

async def is_reaction_wrong_answer(bot, emoji, message, _community, conversation):
    bot_conversation_depth = len(list(filter(lambda m: m.author.id == bot.user.id, conversation)))
    return bot_conversation_depth == 1 and emoji in EMOJIS_NO and message.author.id == bot.user.id

async def handle_reaction_delete_answer(bot, message, _community, conversation):
    answer, question = conversation[-2], conversation[-1]

    qa_view = bot.get_qa_view(_community)
    bot_response = None

    should_ask_to_delete = False
    should_delete_without_ask = False

    # TODO: Update
    bot_response = await qa_view.get_answer_for_question(question.content)

    if bot_response.direct_answer:
        qa_view.delete_qa_pair_from_db(bot_response.direct_answer.doc_idx)
        await message.delete()


REACTION_COMMANDS = [
    {
        "condition": is_reaction_mark_as_answer,
        "handler": handle_reaction_mark_as_answer,
        "admin_only": True
    },
    {
        "condition": is_reaction_wrong_answer,
        "handler": handle_reaction_delete_answer,
        "admin_only": True
    }
]
