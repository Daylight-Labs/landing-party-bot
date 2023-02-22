Landing Party Bot that can automatically:
1) answer questions in Discord
2) create Discord flows/surveys in channels based on configuration in Django admin on back-end

Bot depends on the backend which is located here: https://github.com/Daylight-Labs/landing-party-backend

# Tech Stack:
- Python (py-cord library for Discord API)
- Postgres database
- depends on back-end (Python Django)

# Running/deploying
- Install dependencies
- Fill environmental variables (search for "environ" word usage in the project to get a list of them)
- Both backend and bot need to point to same Postgres database
- CHATBOT_API_AUTH_TOKEN env variable needs to be the same for bot and back-end
- In flow_commands.py update S3 url to your S3 bucket url (needs to be the same as on Django back-end)
- Update all references of 'app.landing.party' to your own back-end url, and all references of our discord community link to your own discord community link
- Run 'main_bot.py' to start the bot
- Bot can run on just a single server now. Did not find a reasonable way to scale