import os
import requests

SLACK_WEBHOOK_DIRECT_ANSWER_LOGS_URL = os.environ['SLACK_WEBHOOK_DIRECT_ANSWER_LOGS_URL']
SLACK_WEBHOOK_OTHER_LOGS_URL = os.environ['SLACK_WEBHOOK_OTHER_LOGS_URL']

def post_message_to_slack_event_logs(message, is_direct_answer):
    response = requests.post(SLACK_WEBHOOK_DIRECT_ANSWER_LOGS_URL if is_direct_answer else SLACK_WEBHOOK_OTHER_LOGS_URL,
        json={
            "text": "",
            "blocks": [
                {
                    "type": "section",
                    "text": {
                        "type": "mrkdwn",
                        "text": message
                    }
                }
            ]
        })
