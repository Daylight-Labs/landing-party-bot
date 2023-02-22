import re
from database import execute_sql

alphabets= "([A-Za-z])"
prefixes = "(Mr|St|Mrs|Ms|Dr)[.]"
suffixes = "(Inc|Ltd|Jr|Sr|Co)"
starters = "(Mr|Mrs|Ms|Dr|He\s|She\s|It\s|They\s|Their\s|Our\s|We\s|But\s|However\s|That\s|This\s|Wherever)"
acronyms = "([A-Z][.][A-Z][.](?:[A-Z][.])?)"
websites = "[.](com|net|org|io|gov)"

def split_into_sentences(text):
    text = " " + text + "  "
    text = text.replace("\n"," ")
    text = re.sub(prefixes,"\\1<prd>",text)
    text = re.sub(websites,"<prd>\\1",text)
    if "Ph.D" in text: text = text.replace("Ph.D.","Ph<prd>D<prd>")
    text = re.sub("\s" + alphabets + "[.] "," \\1<prd> ",text)
    text = re.sub(acronyms+" "+starters,"\\1<stop> \\2",text)
    text = re.sub(alphabets + "[.]" + alphabets + "[.]" + alphabets + "[.]","\\1<prd>\\2<prd>\\3<prd>",text)
    text = re.sub(alphabets + "[.]" + alphabets + "[.]","\\1<prd>\\2<prd>",text)
    text = re.sub(" "+suffixes+"[.] "+starters," \\1<stop> \\2",text)
    text = re.sub(" "+suffixes+"[.]"," \\1<prd>",text)
    text = re.sub(" " + alphabets + "[.]"," \\1<prd>",text)
    if "”" in text: text = text.replace(".”","”.")
    if "\"" in text: text = text.replace(".\"","\".")
    if "!" in text: text = text.replace("!\"","\"!")
    if "?" in text: text = text.replace("?\"","\"?")
    text = text.replace(".",".<stop>")
    text = text.replace("?","?<stop>")
    text = text.replace("!","!<stop>")
    text = text.replace("<prd>",".")
    sentences = text.split("<stop>")
    sentences = sentences[:-1]
    sentences = [s.strip() for s in sentences]
    return sentences

question_starts = ["who", "what", "when", "where", "why", "how", "is", "can", "does", "do",
                   "which", "am", "are", "was", "were", "may", "might", "can", "could", "will",
                   "shall", "would", "should", "has", "have", "had", "did", "whom",
                   "question is", "tell me"]

def check_if_text_contains_question(text):
    for sentence in split_into_sentences(text):
        trimmed_sentence = sentence.strip().strip('!').strip().lower()
        if trimmed_sentence.endswith('?'):
            return True
        for q_start in question_starts:
            if trimmed_sentence.startswith(q_start):
                is_whitespace_after_q_start = len(trimmed_sentence[q_start:]) != len(trimmed_sentence[q_start:].strip())
                return is_whitespace_after_q_start
    return False

def create_user_if_not_exists(user):
    avatar_key = None
    if user.avatar:
        avatar_key = user.avatar.key
        
    execute_sql('insert into api_user ' +
                '(discord_user_id, discord_username, discord_avatar_hash, password, date_registered, is_superuser, is_staff, is_active) ' +
                'VALUES (%s, %s, %s, %s, NOW(), FALSE, FALSE, TRUE) ON CONFLICT DO NOTHING',
                [user.id, user.display_name, avatar_key, ""],
                fetch=False)
