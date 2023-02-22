from typing import List, Any
import pickle

import subprocess
from api_util import get_embeddings

class EmbeddingsService:

    def __init__(self):
        self.api_engine = "text-similarity-ada-001"

    async def get_embedding_for_text(self, text: str) -> List[float]:
        embedding_response = await get_embeddings(text, self.api_engine)
        embedding = embedding_response['data'][0]['embedding']
        return embedding

    def format_embedding_for_db(self, embedding: List[float]) -> Any:
        # sqlite3 can't store lists/arrays, so concatenate floats with commas and store it as a string.
        # TODO: Conversion precision loss from float to str?
        # return ",".join((map(lambda x: str(x), embedding)))
        return pickle.dumps(embedding)