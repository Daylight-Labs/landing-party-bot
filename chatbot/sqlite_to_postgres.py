import sys
import sqlite3
import os

from database import execute_sql


# Run as
# python3 sqlite_to_postgres.py guild_id sqlite_db_path
# e.g. "python3 sqlite_to_postgres.py 948626665716727869 sqlite3_db/948626665716727869.db"

if __name__ == '__main__':
    for file_name in os.listdir('sqlite3_db'):
        if not file_name.endswith('.db') or 'backup' in file_name:
            continue

        guild_id = file_name.split('.db')[0]
        database_file_name = f'sqlite3_db/{file_name}'

        connection = sqlite3.connect(database_file_name)

        cur = connection.cursor()

        cur.execute("select doc_idx, prompt, completion, model, embedding_vector from qa_documents d JOIN qa_embeddings e USING (doc_idx) WHERE (d.is_deleted = 0 OR d.is_deleted IS NULL) AND (e.is_deleted = 0 OR e.is_deleted IS NULL)")
        data = cur.fetchall()

        i = 0
        for item in data:
            doc_idx, prompt, completion, model, embedding_vector = item
            execute_sql("insert into api_qadocument (created_on, last_modified_on, guild_id, prompt, completion, model, embedding_vector, is_public) values (NOW(), NOW(), %s,%s,%s,%s,%s, FALSE)",
                        [guild_id, prompt, completion, model, embedding_vector],
                        fetch=False)
            i += 1

        execute_sql("UPDATE api_qadocument SET deleted_on = NOW() WHERE deleted_on IS NULL AND id NOT IN (SELECT MIN(id) FROM api_qadocument WHERE deleted_on IS NULL GROUP BY guild_id, prompt)",
                    fetch=False)