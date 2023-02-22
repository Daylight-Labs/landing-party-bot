import discord
from database import execute_sql
from community import initialize_all_supported_communities, SUPPORTED_COMMUNITIES
from qa_view import QAView
from datetime import datetime, timezone
import traceback
from discord.ui import InputText, Modal

from utils import create_user_if_not_exists

from commands_guided_flows import generate_custom_id, parse_custom_id
from database import execute_sql

EVENT_TYPE_CREATE_QA_DOC = 'EVENT_TYPE_CREATE_QA_DOC'
EVENT_TYPE_UPDATE_QA_DOC = 'EVENT_TYPE_UPDATE_QA_DOC'
EVENT_TYPE_DELETE_QA_DOC = 'EVENT_TYPE_DELETE_QA_DOC'
EVENT_TYPE_ADD_ADMIN_RIGHTS = 'EVENT_TYPE_ADD_ADMIN_RIGHTS'
EVENT_TYPE_REMOVE_ADMIN_RIGHTS = 'EVENT_TYPE_REMOVE_ADMIN_RIGHTS'

class ApplicationCommandError(Exception):
    pass

async def get_questions(ctx: discord.AutocompleteContext):
    guild_id = ctx.interaction.guild_id

    search = ctx.value.lower()
    tokens = list(filter(lambda x: len(x) > 0, search.split(' ')))

    sql = 'SELECT prompt FROM "api_qadocument" WHERE deleted_on IS NULL AND guild_id = %s'
    params = [guild_id]

    for token in tokens:
        sql += " AND prompt ILIKE %s"
        params.append('%%%s%%' % token)

    result = execute_sql(sql, params)

    return [row['prompt'][:99] for row in result]

async def get_answers(ctx: discord.AutocompleteContext):
    guild_id = ctx.interaction.guild_id

    search = ctx.value.lower()
    tokens = list(filter(lambda x: len(x) > 0, search.split(' ')))

    sql = 'SELECT completion FROM "api_qadocument" WHERE deleted_on IS NULL AND guild_id = %s'
    params = [guild_id]

    for token in tokens:
        sql += " AND completion ILIKE %s"
        params.append('%%%s%%' % token)

    result = execute_sql(sql, params)

    return [row['completion'][:99] for row in result]

async def get_tags(ctx: discord.AutocompleteContext):
    guild_id = ctx.interaction.guild_id

    search = ctx.value.lower()
    tokens = list(filter(lambda x: len(x) > 0, search.split(' ')))

    sql = 'SELECT t.name AS name FROM "api_tag" t JOIN api_community c ON t.community_id = c.id WHERE guild_id = %s ' \
          'AND t.deleted_on IS NULL'
    params = [guild_id]

    for token in tokens:
        sql += " AND t.name ILIKE %s"
        params.append('%%%s%%' % token)

    result = execute_sql(sql, params)

    return [row['name'][:99] for row in result]

async def add_tags_to_question(question, guild_id, tag_options):
    qa_doc_id = get_qadocument_id(question, guild_id)

    tag_ids = []
    tag_names = []

    for t in tag_options:
        if t is None:
            continue
        tag_ids.append(get_tag_id_or_create(t, guild_id))
        tag_names.append(t)

    for tag_id in tag_ids:
        add_tag_to_qa_doc(qa_doc_id, tag_id)

    return tag_names

async def remove_tags_from_question(question, guild_id, tag_options):
    qa_doc_id = get_qadocument_id(question, guild_id)

    tag_ids = []
    tag_names = []

    for t in tag_options:
        if t is None:
            continue
        tag_id = get_tag_id(t, qa_doc_id)
        if tag_id is None:
            continue
        tag_ids.append(tag_id)
        tag_names.append(t)

    for tag_id in tag_ids:
        remove_tag_from_qa_doc(qa_doc_id, tag_id)

    return tag_names

def get_tag_id(tag_name, qa_doc_id):
    select_sql = """
        SELECT t.id AS id, t.name AS name FROM "api_tag" t 
            JOIN "api_tag_qa_documents" tq ON tq.tag_id = t.id
            WHERE t.deleted_on IS NULL AND t.name = %s
            AND qadocument_id = %s
            AND t.deleted_on IS NULL
    """
    params = [tag_name, qa_doc_id]
    result = execute_sql(select_sql, params)

    if len(result) == 0:
        return None

    return result[0]['id']

def get_tag_id_or_create(tag_name, guild_id):
    select_sql = 'SELECT t.id FROM "api_tag" t JOIN "api_community" c ON t.community_id = c.id WHERE t.deleted_on IS NULL AND t.name = %s AND guild_id = %s'
    params = [tag_name, guild_id]
    result = execute_sql(select_sql, params)
    if len(result) == 0:
        insert_sql = 'INSERT INTO "api_tag" (name, community_id, created_on, last_modified_on) ' \
                    'SELECT %s, id, NOW(), NOW() FROM api_community WHERE deleted_on IS NULL AND guild_id = %s'
        params = [tag_name, guild_id]
        result = execute_sql(insert_sql, params, fetch=False)

        params = [tag_name, guild_id]
        result = execute_sql(select_sql, params)

    return result[0]['id']

def add_tag_to_qa_doc(qa_doc_id, tag_id):
    sql = 'INSERT INTO "api_tag_qa_documents" (tag_id, qadocument_id) VALUES (' \
          '%s, ' \
          '%s' \
          ')'
    params = [tag_id, qa_doc_id]
    result = execute_sql(sql, params, fetch=False)

def remove_tag_from_qa_doc(qa_doc_id, tag_id):
    sql = 'DELETE FROM "api_tag_qa_documents" WHERE tag_id = %s AND qadocument_id = %s'
    params = [tag_id, qa_doc_id]
    result = execute_sql(sql, params, fetch=False)

def get_qadocument_id(prompt, guild_id):
    sql = 'SELECT id FROM "api_qadocument" WHERE deleted_on IS NULL AND prompt = %s AND guild_id = %s'
    params = [prompt, guild_id]

    result = execute_sql(sql, params)

    if result:
        return result[0]['id']
    else:
        raise ApplicationCommandError("No QA document found for supplied prompt and guild id")

def get_tags_by_qa_doc(qa_doc_id):
    sql = """
        SELECT t.id AS id, t.name AS name 
            FROM "api_tag_qa_documents" tq
            JOIN "api_tag" t ON tq.tag_id = t.id
            JOIN "api_qadocument" q ON tq.qadocument_id = q.id
            WHERE qadocument_id = %s 
            AND t.deleted_on IS NULL
            AND q.deleted_on IS NULL
    """

    params = [qa_doc_id]

    result = execute_sql(sql, params)

    return list(map(lambda x: x['name'], result))


def get_answer(prompt, guild_id):
    sql = 'SELECT completion FROM "api_qadocument" WHERE deleted_on IS NULL AND prompt = %s AND guild_id = %s'
    params = [prompt, guild_id]

    result = execute_sql(sql, params)

    if len(result) == 0:
        return None

    return result[0]['completion']

def get_qa_doc_by_completion(completion, guild_id):
    sql = 'SELECT prompt, completion FROM "api_qadocument" WHERE deleted_on IS NULL AND completion = %s AND guild_id = %s'
    params = [completion, guild_id]

    result = execute_sql(sql, params)

    if len(result) == 0:
        return None

    return result[0]


DATETIME_FORMAT = '%Y-%m-%d %H:%M'
DATE_FORMAT = '%Y-%m-%d'

def parse_datetime(datetime_str):
    try:
        return datetime.strptime(datetime_str, DATETIME_FORMAT)
    except:
        return datetime.strptime(datetime_str, DATE_FORMAT)

def format_datetime(dt):
    return dt.replace(tzinfo=timezone.utc).strftime(DATETIME_FORMAT)

def get_qa_docs_with_revision_dates(guild_id):
    sql = """
                SELECT * FROM "api_qadocument"
                    WHERE revision_date IS NOT NULL
                    AND deleted_on IS NULL
                    AND guild_id = %s
            """

    params = [guild_id]

    result = execute_sql(sql, params)

    return result

def get_qa_docs_with_due_revision_dates(guild_id):
    sql = """
                SELECT * FROM "api_qadocument"
                    WHERE revision_date IS NOT NULL
                    AND deleted_on IS NULL
                    AND guild_id = %s
                    AND revision_date < timezone('utc', now())
            """

    params = [guild_id]

    result = execute_sql(sql, params)

    return result

def set_revision_date(q_id, dt, guild_id):
    sql = """
            UPDATE "api_qadocument"
                SET revision_date = %s
                WHERE id = %s 
        """

    params = [dt, q_id]

    result = execute_sql(sql, params, fetch=False)

    return list(filter(lambda x: x['id'] == q_id, get_qa_docs_with_revision_dates(guild_id)))[0]['revision_date']

def clear_revision_date(q_id, guild_id):
    sql = """
            UPDATE "api_qadocument"
                SET revision_date = NULL
                WHERE id = %s 
        """

    params = [q_id]

    result = execute_sql(sql, params, fetch=False)

def get_notification_channel_id(guild_id):
    sql = """
                    SELECT ch.channel_id FROM "api_community" com
                        JOIN api_alldiscordchanels ch ON ch.id = com.notifications_channel_ref_id
                        WHERE com.guild_id = %s
                        AND ch.deleted_on IS NULL and com.deleted_on IS NULL
                """

    params = [guild_id]

    result = execute_sql(sql, params)

    if len(result) == 0:
        return None

    return result[0]["channel_id"]

def set_notification_channel_id(guild_id, channel_id):
    sql = """
                UPDATE "api_community"
                    SET notifications_channel_ref_id = (
                        SELECT id
                        FROM api_alldiscordchanels
                        WHERE channel_id = %s
                        AND deleted_on IS NULL
                    )
                    WHERE guild_id = %s
            """

    params = [channel_id, guild_id]

    result = execute_sql(sql, params, fetch=False)

    return get_notification_channel_id(guild_id)



class CreateQAModal(Modal):
    def __init__(self, *args, **kwargs) -> None:
        super().__init__(custom_id=generate_custom_id(EVENT_TYPE_CREATE_QA_DOC, [], []),
                         title=f"Create Q&A doc", *args, **kwargs)
        self.add_item(InputText(label="Question", placeholder="", custom_id='question', max_length=1990,
                                style=discord.InputTextStyle.long))
        self.add_item(InputText(label="Answer", placeholder="", custom_id='answer', max_length=1990,
                                style=discord.InputTextStyle.long))

async def create_qa_modal_callback(custom_id, interaction, bot):
    _community = SUPPORTED_COMMUNITIES.get(interaction.guild_id)
    qa_view = bot.get_qa_view(_community)
    if not qa_view:
        return

    q = interaction.data['components'][0]['components'][0]['value']
    a = interaction.data['components'][1]['components'][0]['value']

    # Insert question and answer into database
    await qa_view.insert_qa_pair_into_db(q, a,
                                         interaction.user, interaction.user,
                                         question_jump_url=None,
                                         answer_jump_url=None)

    await interaction.response.send_message('Q&A pair successfully added',
                                            ephemeral=True)

class UpdateQAModal(Modal):
    def __init__(self, custom_id, prompt, current_answer, *args, **kwargs) -> None:
        super().__init__(custom_id=custom_id, title=f"Update answer for '{prompt[:20]}'", *args, **kwargs)
        self.add_item(InputText(label="New Answer", placeholder="", custom_id='new_answer', max_length=1990,
                                value=current_answer,
                                style=discord.InputTextStyle.long))

async def update_qa_modal_callback(custom_id, interaction, bot):
    _community = SUPPORTED_COMMUNITIES.get(interaction.guild_id)
    qa_view = bot.get_qa_view(_community)
    if not qa_view:
        return

    (_, [message_id, *_], _) = parse_custom_id(custom_id)
    
    message = await interaction.channel.fetch_message(message_id)
    
    bot_response = await qa_view.get_answer_for_question(message.content)

    answer = interaction.data['components'][0]['components'][0]['value']

    if bot_response.direct_answer:
        await qa_view.update_answer_for_qa_doc(bot_response.direct_answer.doc_idx, answer)

        await interaction.response.send_message('Q&A pair successfully updated',
                                                ephemeral=True)

class DeleteQAModal(Modal):
    def __init__(self, custom_id, prompt, *args, **kwargs) -> None:
        super().__init__(custom_id=custom_id, title=f"Delete q&a doc '{prompt[:20]}'", *args, **kwargs)
        self.add_item(InputText(label="You won't be able to revert this change", placeholder="Type 'confirm' here",
                                custom_id='confirm', max_length=50))


async def delete_qa_modal_callback(custom_id, interaction, bot):
    _community = SUPPORTED_COMMUNITIES.get(interaction.guild_id)
    qa_view = bot.get_qa_view(_community)
    if not qa_view:
        return

    (_, [message_id, *_], _) = parse_custom_id(custom_id)

    message = await interaction.channel.fetch_message(message_id)

    bot_response = await qa_view.get_answer_for_question(message.content)

    confirm = interaction.data['components'][0]['components'][0]['value']

    if confirm.lower().strip() != 'confirm':
        await interaction.response.send_message('Invalid "confirm" phrase provided',
                                                ephemeral=True)
        return

    if bot_response.direct_answer:
        qa_view.delete_qa_pair_from_db(bot_response.direct_answer.doc_idx)

        await interaction.response.send_message('Q&A pair successfully deleted',
                                                ephemeral=True)

class ToggleAdminRightsButton(discord.ui.Button):
    def __init__(self, add: bool, user_id: int):
        super().__init__(style=discord.ButtonStyle.secondary, label="Grant adming rights" if add else "Remove admin rights", row=0)
        self.custom_id = generate_custom_id(EVENT_TYPE_ADD_ADMIN_RIGHTS if add else EVENT_TYPE_REMOVE_ADMIN_RIGHTS,
                                            [user_id, 1 if add else 0],
                                            callback_ids_sets=[])

async def toggle_admin_rights_callback(custom_id: str, interaction: discord.Interaction):
    (_, [user_id, add, *_], _) = parse_custom_id(custom_id)

    guild = interaction.guild
    user = await guild.fetch_member(user_id)

    create_user_if_not_exists(user)
    
    if add == 1:
        execute_sql("INSERT INTO api_community_admins (community_id, user_id) VALUES ((SELECT id FROM api_community WHERE guild_id = %s), (SELECT id FROM api_user WHERE discord_user_id = %s))",
                    [guild.id, user_id],
                    fetch=False)
    else:
        execute_sql(
            "DELETE FROM api_community_admins WHERE community_id = (SELECT id FROM api_community WHERE guild_id = %s) AND user_id = (SELECT id FROM api_user WHERE discord_user_id = %s)",
            [guild.id, user_id],
            fetch=False)

    await interaction.response.send_message(f"<@{user_id}> was succesfully added to admin list"
                                            if add
                                            else f"<@{user_id}> was successfully removed from admin list",
                                            ephemeral=True)

class Commands(discord.Cog):

    def __init__(self, bot):
        self.bot = bot
    
    @discord.slash_command(name="ping")
    async def ping(self, ctx):
        await ctx.interaction.response.send_message('Pong! Latency {0}'.format(ctx.interaction.client.latency))

    @discord.user_command(name="Make LParty admin")
    async def toggle_admin_rights(self,
                             ctx,
                             user
                             ):
        initialize_all_supported_communities()

        community = SUPPORTED_COMMUNITIES[ctx.guild_id]
        is_admin = community.user_has_admin_access(ctx.author)
        if not is_admin:
            await ctx.respond(f'Sorry, you don\'t have permissions to do this!', ephemeral=True)
            return

        admin_rows = execute_sql("SELECT * FROM api_community_admins WHERE community_id = (SELECT id FROM api_community WHERE guild_id = %s) AND user_id = (SELECT id FROM api_user WHERE discord_user_id = %s)",
                                 [ctx.guild_id, user.id])

        add = len(admin_rows) == 0

        view = discord.ui.View()
        view.add_item(ToggleAdminRightsButton(add=add, user_id=user.id))

        admin_role_id = community.has_admin_role(user)

        await ctx.interaction.response.send_message((f"<@{user.id}> currently is not in admin list"  if add else f"<@{user.id}> is currently already in admin list") + (f"\nAdmin rights are granted implicitly through role <@&{admin_role_id}>" if admin_role_id else ""),
                                                    view=view,
                                                    ephemeral=True)

    @discord.message_command(name="Create Q&A pair")
    async def create_qa_pair(self,
                            ctx,
                            message
                            ):
        community = SUPPORTED_COMMUNITIES[ctx.guild_id]
        is_admin = community.user_has_admin_access(ctx.author)
        if not is_admin:
            await ctx.respond(f'Sorry, you don\'t have permissions to do this!', ephemeral=True)
            return

        await ctx.interaction.response.send_modal(CreateQAModal())

    @discord.message_command(name="Update Q&A pair")
    async def update_answer(self,
                            ctx,
                            message
                            ):
        community = SUPPORTED_COMMUNITIES[ctx.guild_id]
        is_admin = community.user_has_admin_access(ctx.author)
        if not is_admin:
            await ctx.respond(f'Sorry, you don\'t have permissions to do this!', ephemeral=True)
            return
        prompt_message = None
        if ctx.guild.me.id == message.author.id and message.reference is not None:
            prompt_message = await ctx.channel.fetch_message(message.reference.message_id)
        else:
            await ctx.respond(f'Q&A pair not found. Please use this command on answer message posted by bot', ephemeral=True)
            return

        custom_id = generate_custom_id(EVENT_TYPE_UPDATE_QA_DOC, [prompt_message.id], [])
        modal = UpdateQAModal(custom_id=custom_id, prompt=prompt_message.content,
                              current_answer=message.content)
        await ctx.interaction.response.send_modal(modal)

    @discord.message_command(name="Delete Q&A pair")
    async def delete_qa_pair(self,
                             ctx,
                             message
                             ):
        community = SUPPORTED_COMMUNITIES[ctx.guild_id]
        is_admin = community.user_has_admin_access(ctx.author)
        if not is_admin:
            await ctx.respond(f'Sorry, you don\'t have permissions to do this!', ephemeral=True)
            return
        prompt_message = None
        if ctx.guild.me.id == message.author.id and message.reference is not None:
            prompt_message = await ctx.channel.fetch_message(message.reference.message_id)
        else:
            await ctx.respond(f'Q&A pair not found. Please use this command on answer message posted by bot',
                              ephemeral=True)
            return

        custom_id = generate_custom_id(EVENT_TYPE_DELETE_QA_DOC, [prompt_message.id], [])
        modal = DeleteQAModal(custom_id=custom_id, prompt=prompt_message.content)
        await ctx.interaction.response.send_modal(modal)
    
    @discord.slash_command(name="question")
    async def find_question(self,
                   ctx,
                   search: discord.commands.Option(str, "Search questions", autocomplete=get_questions)
                   ):

        guild_id = ctx.interaction.guild_id

        answer = get_answer(search, guild_id)

        if answer:
            await ctx.respond(f"Question: {search}\n\nAnswer: {answer}\n")
        else:
            await ctx.respond(f"Oops! Looks like the question doesn't exist")

    @discord.slash_command(name="answer")
    async def find_answer(self,
                            ctx,
                            search: discord.commands.Option(str, "Search questions", autocomplete=get_answers),
                            show_question: discord.commands.Option(bool, "(Optional) If not set, shows only answer", required=False)
                            ):

        guild_id = ctx.interaction.guild_id

        qa_doc = get_qa_doc_by_completion(search, guild_id)

        if qa_doc:
            if show_question:
                await ctx.respond(f"Question: {qa_doc['prompt']}\n\nAnswer: {qa_doc['completion']}\n")
            else:
                await ctx.respond(f"{qa_doc['completion']}\n")
        else:
            await ctx.respond(f"Oops! Looks like the Q&A pair doesn't exist")

    @discord.slash_command(name="addtags", description="Add tag(s) to existing question")
    async def addtags(self,
                      ctx,
                      question: discord.commands.Option(str, "Search questions", autocomplete=get_questions),
                      tag: discord.commands.Option(str, "Search tags", autocomplete=get_tags),
                      tag2: discord.commands.Option(str, "Search tags", autocomplete=get_tags, required=False),
                      tag3: discord.commands.Option(str, "Search tags", autocomplete=get_tags, required=False),
                      tag4: discord.commands.Option(str, "Search tags", autocomplete=get_tags, required=False),
                      tag5: discord.commands.Option(str, "Search tags", autocomplete=get_tags, required=False),
                      tag6: discord.commands.Option(str, "Search tags", autocomplete=get_tags, required=False),
                      tag7: discord.commands.Option(str, "Search tags", autocomplete=get_tags, required=False),
                      tag8: discord.commands.Option(str, "Search tags", autocomplete=get_tags, required=False),
                      tag9: discord.commands.Option(str, "Search tags", autocomplete=get_tags, required=False),
                      tag10: discord.commands.Option(str, "Search tags", autocomplete=get_tags, required=False),
                      ):
        guild_id = ctx.interaction.guild_id

        initialize_all_supported_communities()

        community = SUPPORTED_COMMUNITIES[guild_id]

        is_admin = community.user_has_admin_access(ctx.interaction.user)

        if not is_admin:
            await ctx.respond(f'Sorry, you don\'t have permissions to do this!')
            return

        try:
            await add_tags_to_question(question, guild_id,
                                    [tag, tag2, tag3, tag4, tag5, tag6, tag7, tag8, tag9, tag10])
            ctx.respond(f'Successfully added tags to question')
        except Exception as e:
            ctx.respond(f'Oops! Something went wrong!')
            print(traceback.format_exc())

    @discord.slash_command(name="createquestion", description="Create Q&A with tags (optional)")
    async def createquestion(self,
                      ctx,
                      question: discord.commands.Option(str, "Question"),
                      answer: discord.commands.Option(str, "Answer"),
                      tag: discord.commands.Option(str, "Search tags", autocomplete=get_tags, required=False),
                      tag2: discord.commands.Option(str, "Search tags", autocomplete=get_tags, required=False),
                      tag3: discord.commands.Option(str, "Search tags", autocomplete=get_tags, required=False),
                      tag4: discord.commands.Option(str, "Search tags", autocomplete=get_tags, required=False),
                      tag5: discord.commands.Option(str, "Search tags", autocomplete=get_tags, required=False),
                      tag6: discord.commands.Option(str, "Search tags", autocomplete=get_tags, required=False),
                      tag7: discord.commands.Option(str, "Search tags", autocomplete=get_tags, required=False),
                      tag8: discord.commands.Option(str, "Search tags", autocomplete=get_tags, required=False),
                      tag9: discord.commands.Option(str, "Search tags", autocomplete=get_tags, required=False),
                      ):
        guild_id = ctx.interaction.guild_id

        initialize_all_supported_communities()
        community = SUPPORTED_COMMUNITIES[guild_id]
        is_admin = community.user_has_admin_access(ctx.interaction.user)
        if not is_admin:
            await ctx.respond(f'Sorry, you don\'t have permissions to do this!')
            return

        if get_answer(question, guild_id) is not None:
            await ctx.respond(f"Oops! It looks like this question already exists")
            return

        user = ctx.interaction.user

        qa_view = QAView(community)

        await qa_view.insert_qa_pair_into_db(question, answer, user, user)

        try:
            tag_names = await add_tags_to_question(question, guild_id,
                                                [tag, tag2, tag3, tag4, tag5, tag6, tag7, tag8, tag9])
            await ctx.respond(f'Successfully added the question and answer')
        except Exception as e:
            print(traceback.format_exc())
            await ctx.respond(f'Oops! Something went wrong!')
            return

    @discord.slash_command(name="listtags", description="List tag(s) of existing Q&A pair")
    async def listtags(self,
                      ctx,
                      question: discord.commands.Option(str, "Search questions", autocomplete=get_questions)
                      ):
        guild_id = ctx.interaction.guild_id
        initialize_all_supported_communities()
        community = SUPPORTED_COMMUNITIES[guild_id]
        is_admin = community.user_has_admin_access(ctx.interaction.user)
        if not is_admin:
            await ctx.respond(f'Sorry, you don\'t have permissions to do this!')
            return

        try:
            qa_doc_id = get_qadocument_id(question, guild_id)
            tag_names = get_tags_by_qa_doc(qa_doc_id)
            await ctx.respond(f"Q: {question}\n\nTags: {', '.join(tag_names)}")
        except Exception as e:
            print(traceback.format_exc())
            await ctx.respond(f'Oops! Something went wrong!')

    @discord.slash_command(name="removetags", description="Remove tag(s) from existing question")
    async def removetags(self,
                      ctx,
                      question: discord.commands.Option(str, "Search questions", autocomplete=get_questions),
                      tag: discord.commands.Option(str, "Search tags", autocomplete=get_tags),
                      tag2: discord.commands.Option(str, "Search tags", autocomplete=get_tags, required=False),
                      tag3: discord.commands.Option(str, "Search tags", autocomplete=get_tags, required=False),
                      tag4: discord.commands.Option(str, "Search tags", autocomplete=get_tags, required=False),
                      tag5: discord.commands.Option(str, "Search tags", autocomplete=get_tags, required=False),
                      tag6: discord.commands.Option(str, "Search tags", autocomplete=get_tags, required=False),
                      tag7: discord.commands.Option(str, "Search tags", autocomplete=get_tags, required=False),
                      tag8: discord.commands.Option(str, "Search tags", autocomplete=get_tags, required=False),
                      tag9: discord.commands.Option(str, "Search tags", autocomplete=get_tags, required=False),
                      tag10: discord.commands.Option(str, "Search tags", autocomplete=get_tags, required=False),
                      ):
        guild_id = ctx.interaction.guild_id
        initialize_all_supported_communities()
        community = SUPPORTED_COMMUNITIES[guild_id]
        is_admin = community.user_has_admin_access(ctx.interaction.user)
        if not is_admin:
            await ctx.respond(f'Sorry, you don\'t have permissions to do this!')
            return

        try:
            await remove_tags_from_question(question, guild_id,
                                            [tag, tag2, tag3, tag4, tag5, tag6, tag7, tag8, tag9, tag10])
            await ctx.respond(f'Successfully removed the tags')
        except Exception as e:
            await ctx.respond(f'Oops! Something went wrong!')
            print(traceback.format_exc())

    @discord.slash_command(name="setnotificationchannel",
                           description="Set channel for bot notifications (e.g. when revision for question is needed)")
    async def setnotificationchannel(self,
                              ctx,
                              channel: discord.commands.Option(discord.SlashCommandOptionType.channel, "Channel")
                              ):
        initialize_all_supported_communities()
        guild_id = ctx.interaction.guild_id
        community = SUPPORTED_COMMUNITIES[guild_id]
        is_admin = community.user_has_admin_access(ctx.interaction.user)
        if not is_admin:
            await ctx.respond(f'Sorry, you don\'t have permissions to do this!',
                              ephemeral=True)
            return

        channel_id = set_notification_channel_id(ctx.interaction.guild_id, channel.id)
        if channel_id is None:
            await ctx.respond(f'Unexpected error happened (channel seems to have been created very recently), please try again in 10 seconds',
                              ephemeral=True)
            return
        await ctx.respond(f'Notification channel of FAQ bot successfully set to <#{channel_id}>',
                          ephemeral=True)

    @discord.slash_command(name="setrevisiondate",
                           description="Set revision date for question (bot will send notification on revision date)")
    async def setrevisiondate(self,
                       ctx,
                       question: discord.commands.Option(str, "Search questions", autocomplete=get_questions),
                       datetime: discord.commands.Option(str, "'YYYY-MM-DD HH:MM' in UTC")
                       ):
        initialize_all_supported_communities()
        guild_id = ctx.interaction.guild_id
        community = SUPPORTED_COMMUNITIES[guild_id]

        is_admin = community.user_has_admin_access(ctx.interaction.user)

        notifications_channel_id = get_notification_channel_id(guild_id)

        if notifications_channel_id is None:
            await ctx.respond(f"First, please use **/setnotificationchannel** slash command to set the channel where notifications " + \
                              "question revisions will be sent",
                              ephemeral=True)
            return

        community = SUPPORTED_COMMUNITIES[guild_id]
        is_admin = community.user_has_admin_access(ctx.interaction.user)
        if not is_admin:
            await ctx.respond(f'Sorry, you don\'t have permissions to do this!',
                              ephemeral=True)
            return

        try:
            qa_doc_id = get_qadocument_id(question, guild_id)
            dt = parse_datetime(datetime)
            set_dt = set_revision_date(qa_doc_id, dt, guild_id)
            await ctx.respond(f"✏️ Revision date for Q: '**{question}**' successfully set to 🕒 **{format_datetime(set_dt)}** UTC. " + \
                              f"You will be notified in <#{notifications_channel_id}> when question needs revision. " + \
                              "In order to view revision dates of all questions, please use **/showrevisiondates** slash command. ",
                              ephemeral=True)
        except Exception as e:
            print(traceback.format_exc())
            await ctx.respond(f'Oops! Something went wrong! Please double check that time format matches \'YYYY-MM-DD HH:MM\' or \'YYYY-MM-DD\'', ephemeral=True)

    @discord.slash_command(name="showrevisiondates",
                           description="Show revision dates")
    async def showrevisiondates(self,
                              ctx
                              ):
        guild_id = ctx.interaction.guild_id
        community = SUPPORTED_COMMUNITIES[guild_id]

        is_admin = community.user_has_admin_access(ctx.interaction.user)
        if not is_admin:
            await ctx.respond(f'Sorry, you don\'t have permissions to do this!',
                              ephemeral=True)
            return

        strings_by_revision_date = {}

        for qa_doc in get_qa_docs_with_revision_dates(guild_id):
            strings_by_revision_date[qa_doc['revision_date']] = \
                f"- Revision date 🕒 **{format_datetime(qa_doc['revision_date'])}** UTC. Q: '**{qa_doc['prompt']}**'; A: '**{qa_doc['completion']}**'"

        strings = []

        for rev_date in sorted(strings_by_revision_date.keys()):
            strings.append(strings_by_revision_date[rev_date])

        if len(strings) > 0:
            await ctx.respond('✏️ **Revision dates:**\n' + '\n'.join(strings),
                              ephemeral=True)
        else:
            await ctx.respond("No revision dates set yet in future. Use **/setrevisiondate** to set revision dates for questions",
                              ephemeral=True)

async def send_all_notifications(guild):
    channel_id = get_notification_channel_id(guild.id)
    if channel_id is None:
        return
    strings = []
    qa_doc_ids = []
    for qa_doc in get_qa_docs_with_due_revision_dates(guild.id):
        try:
            strings.append(f'**{str(len(strings) + 1)}.** Q: "**{qa_doc["prompt"]}**"; A: "**{qa_doc["completion"]}**"')
            qa_doc_ids.append(qa_doc['id'])
        except:
            pass
    channel = await guild.fetch_channel(channel_id)
    if len(strings) > 0:
        await channel.send('🕒 ✏️ **Revisions due: **\n' + '\n'.join(strings))
        for qa_id in qa_doc_ids:
            clear_revision_date(qa_id, guild.id)
