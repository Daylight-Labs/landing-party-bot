import community
import sqlite3
from scipy import spatial
import logging
from typing import List, Any
from dotenv import load_dotenv
import pickle
import os
from embeddings_service import EmbeddingsService
from utils import create_user_if_not_exists

load_dotenv()
import openai

from database import execute_sql

class BotException(Exception):
    """
    Common base class for application exceptions.
    """
    pass

class QASingleMatch:
    def __init__(self, doc_idx, question, answer, confidence, question_jump_url, answer_jump_url,
                 is_spam=False,
                 buttons=[]):
        self.doc_idx = doc_idx
        self.question = question
        self.answer = answer
        self.confidence = confidence
        self.question_jump_url = question_jump_url
        self.answer_jump_url = answer_jump_url
        self.buttons = buttons
        self.is_spam = is_spam

class QaMatchesResult:
    def __init__(self, direct_answer: QASingleMatch, alternative_answers: [QASingleMatch]):
        self.direct_answer = direct_answer
        self.alternative_answers = alternative_answers

class QAView:

    def __init__(self, community: community.CommunityConfiguration):
        self.__community = community
        self.__embeddings_service = EmbeddingsService()
        
        self.__guild_id = community.guild_id

    def parse_embedding_from_db(self, embedding_from_db: Any) -> List[float]:
        # return embedding_str.split(",")
        # TODO: validate this is a list of floats
        return pickle.loads(embedding_from_db)

    def compute_spatial_distance_for_embedding(self, list1,list2):
        """
        :param: list1, list2    Vectors (lists) of floats, representing embeddings.
        """
        return 1 - spatial.distance.cosine(list1, list2)

    async def update_answer_for_qa_doc(self, doc_idx, answer):
        execute_sql(
            "update api_qadocument set completion=%(completion)s where id=%(doc_idx)s",
            {"completion": answer, "doc_idx": doc_idx},
            fetch=False)

    async def get_answer_for_question(self, question):
        community = self.__community

        try:
            new_embedding = await self.__embeddings_service.get_embedding_for_text(question)
        except:
            return QaMatchesResult(
                direct_answer=None,
                alternative_answers=[]
            )

        qa_documents = execute_sql("select id, prompt, completion, embedding_vector, question_jump_url, answer_jump_url, is_spam from api_qadocument where guild_id=%(guild_id)s AND model=%(model_used)s AND deleted_on IS NULL", {"guild_id": self.__guild_id, "model_used": self.__embeddings_service.api_engine})

        print("ALL QA DOCUMENTS CNT", len(qa_documents))

        if len(qa_documents) == 0:
            return QaMatchesResult(
                direct_answer=None,
                alternative_answers=[]
            )

        alternative_prompts = execute_sql('SELECT alternative_prompt, ap.embedding_vector, qa_document_id FROM api_qadocumentalternativeprompt ap JOIN api_qadocument qa ON ap.qa_document_id = qa.id where guild_id=%(guild_id)s AND ap.model=%(model_used)s AND deleted_on IS NULL', {"guild_id": self.__guild_id, "model_used": self.__embeddings_service.api_engine})

        alternative_prompts_by_qa_doc_id = {}

        for alt_prompt in alternative_prompts:
            doc_id = alt_prompt['qa_document_id']
            alternative_prompts_by_qa_doc_id[doc_id] = alternative_prompts_by_qa_doc_id.get(doc_id, [])
            alternative_prompts_by_qa_doc_id[doc_id].append(alt_prompt)

        similarity_map = []
        for qa_doc in qa_documents:
            embedding = qa_doc['embedding_vector']
            if embedding:
                vector = self.parse_embedding_from_db(embedding)
                similarity = self.compute_spatial_distance_for_embedding(vector, new_embedding)

                for alt_prompt in alternative_prompts_by_qa_doc_id.get(qa_doc['id'], []):
                    embedding = alt_prompt['embedding_vector']
                    vector = self.parse_embedding_from_db(embedding)
                    alt_similarity = self.compute_spatial_distance_for_embedding(vector, new_embedding)

                    if alt_similarity > similarity:
                        similarity = alt_similarity

                # map to document index
                similarity_map.append((similarity,qa_doc))

        # Sort by similarity score (first member of tuple)
        similarity_map.sort(key = lambda x: x[0], reverse=True)
        similarity_map = list(filter(lambda x: x[0] > 0.5, similarity_map))

        if not similarity_map:
            return QaMatchesResult(
                direct_answer=None,
                alternative_answers=[]
            )

        most_similar_qa_mapping = similarity_map[0]
        direct_answer = None
        if most_similar_qa_mapping[0] >= community.minimum_threshold:
            most_similar_qa_pair = most_similar_qa_mapping[1]

            buttons = execute_sql("SELECT label, button_style, triggered_flow_id FROM api_qadocumentcompletionbutton WHERE qa_document_id = %s",
                                  [ most_similar_qa_pair['id'] ])

            direct_answer = QASingleMatch(
                doc_idx=most_similar_qa_pair['id'],
                question=most_similar_qa_pair['prompt'],
                answer=most_similar_qa_pair['completion'],
                question_jump_url=most_similar_qa_pair['question_jump_url'],
                answer_jump_url=most_similar_qa_pair['answer_jump_url'],
                confidence=most_similar_qa_mapping[0],
                is_spam=most_similar_qa_pair['is_spam'],
                buttons=buttons
            )
        
        #If we have a direct answer (i.e with a 0.9 similarity or greater) the next closest answers will be starting at index 1s
        start_index = 1 if direct_answer else 0

        #Add up to 3 close results to the output
        end_index = start_index + 3

        highest_alternative_answers = []
        for x in range(start_index, end_index):
            if x >= len(similarity_map):
                break
            current_qa_mapping = similarity_map[x]
            current_confidence = current_qa_mapping[0]
            current_qa_pair =  current_qa_mapping[1]
            current_answer = QASingleMatch(
                doc_idx=current_qa_pair['id'],
                question=current_qa_pair['prompt'],
                answer=current_qa_pair['completion'],
                question_jump_url=current_qa_pair['question_jump_url'],
                answer_jump_url=current_qa_pair['answer_jump_url'],
                confidence=current_confidence,
                is_spam=current_qa_pair['is_spam']
            )
            highest_alternative_answers.append(current_answer)
        
        return QaMatchesResult(
            direct_answer=direct_answer,
            alternative_answers=highest_alternative_answers
        )
    
    def delete_qa_pair_from_db(self, idx) -> None:
        execute_sql("update api_qadocument set deleted_on=NOW() where id=%(idx)s", {"idx": idx},
                    fetch=False)

    async def insert_qa_pair_into_db(self, question, answer, asked_by, answered_by, question_jump_url=None, answer_jump_url=None):
        try:
            embedding = await self.__embeddings_service.get_embedding_for_text(question)
            embedding_str = self.__embeddings_service.format_embedding_for_db(embedding)
        except:
            return

        create_user_if_not_exists(asked_by)
        create_user_if_not_exists(answered_by)

        execute_sql('insert into api_qadocument (guild_id, prompt, completion, asked_by_id, answered_by_id, model, embedding_vector, created_on, last_modified_on, is_public, question_jump_url, answer_jump_url, is_spam) values (%s, %s, %s, %s, %s, %s, %s, NOW(), NOW(), FALSE, %s, %s, FALSE)',
                    [self.__guild_id, question, answer, asked_by.id, answered_by.id, self.__embeddings_service.api_engine, embedding_str, question_jump_url, answer_jump_url],
                    fetch=False)

        self.remove_unanswered_questions_for_prompt(question)

    def insert_unanswered_question_into_db(self, question, user_id):

        existing_unanswered_questions = execute_sql('select id from api_unansweredquestion where guild_id = %s and prompt = %s',
                                        [self.__guild_id, question])

        if len(existing_unanswered_questions) > 0:
            return

        execute_sql(
            'insert into api_unansweredquestion (guild_id, user_id, prompt, created_on, last_modified_on) values (%s, %s, %s, NOW(), NOW())',
            [self.__guild_id, user_id, question],
            fetch=False)

    def remove_unanswered_questions_for_prompt(self, prompt):
        execute_sql(
            'update api_unansweredquestion set deleted_on = NOW() where guild_id = %s and prompt = %s',
            [self.__guild_id, prompt],
            fetch=False
        )
