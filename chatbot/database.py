import psycopg2
from os import environ

connection = psycopg2.connect(user=environ['SQL_USER'],
                              password=environ['SQL_PASSWORD'],
                              host=environ['SQL_HOST'],
                              port=environ['SQL_PORT'],
                              database=environ['SQL_DATABASE'])

def reinitialize_connection():
    global connection

    connection = psycopg2.connect(user=environ['SQL_USER'],
                                  password=environ['SQL_PASSWORD'],
                                  host=environ['SQL_HOST'],
                                  port=environ['SQL_PORT'],
                                  database=environ['SQL_DATABASE'])

def execute_sql(query, vars=None, fetch=True):
    if connection.closed:
        reinitialize_connection()

    cursor = connection.cursor()

    try:
        cursor.execute(query, vars)
    except psycopg2.errors.InFailedSqlTransaction as e:
        connection.rollback()
        cursor.execute(query, vars)

    if fetch:
        rows = cursor.fetchall()
        colnames = [desc[0] for desc in cursor.description]

        result = list(map(lambda row: dict(zip(colnames, row)), rows))
    else:
        result = None

    connection.commit()
    cursor.close()

    return result
