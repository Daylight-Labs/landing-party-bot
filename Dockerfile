############
# BASE IMAGE
############
FROM python:3.9 as slim

WORKDIR /usr/src/app

COPY ./chatbot/requirements.txt ./

RUN pip install --no-cache-dir -r requirements.txt

COPY ./chatbot/ .

# Migration
# CMD ["python3", "sqlite_to_postgres.py"]

CMD ["python3", "main_bot.py" ]