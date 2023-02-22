import datetime
import sentry_sdk

class InteractionWrapper:
    def __init__(self, interaction=None, message=None):
        self.interaction = interaction
        self.message = message
        self.last_sent_message = None
        self.overriden_channel = None

    @property
    def is_message(self):
        return self.message is not None

    async def send_message(self, text, view=None, file=None, files=None, ephemeral=False):
        sentry_sdk.add_breadcrumb(
                category='bot',
                message='send_message',
                level='info',
                data={
                    "latency":'{0}'.format(self.interaction.client.latency),
                    "id": self.interaction.id,
                    "type": self.interaction.type,
                    "is_done": self.interaction.response.is_done(),
                    "current_time":'{0}'.format(datetime.datetime.now()),
                    "ephemeral": ephemeral
                }
            )
        if self.interaction is not None:
            # if self.interaction.response.is_done():
            if not ephemeral:
                self.last_sent_message = await self.channel.send(text, view=view,
                                                                       file=file,
                                                                       files=files)
                if not self.interaction.response.is_done():
                    await self.interaction.response.defer()
            else:
                try:
                    await self.interaction.response.send_message(text, view=view, files=files, file=file,
                                                                ephemeral=ephemeral)
                    self.last_sent_message = await self.interaction.original_message()
                except Exception as e:
                    sentry_sdk.add_breadcrumb(
                        category='bot',
                        message='send_message_exception',
                        level='info',
                        data={
                            "latency":'{0}'.format(self.interaction.client.latency),
                            "id": self.interaction.id,
                            "type": self.interaction.type,
                            "is_done": self.interaction.response.is_done(),
                            "current_time":'{0}'.format(datetime.datetime.now()),
                            "ephemeral": ephemeral
                        }
                    )
                    raise e
            # else:
            #     await self.interaction.response.send_message(text, view=view, files=files,
            #                                                  ephemeral=ephemeral)
            #     self.last_sent_message = await self.interaction.original_message()
        elif self.message is not None:
            self.last_sent_message = await self.message.reply(text, view=view, file=file, files=files)
        else:
            raise 'invalid state'

        return self.last_sent_message
    
    async def edit_last_sent_message(self, text, files):
        await message.edit(content=text, files=files)

    @property
    def guild(self):
        if self.interaction is not None:
            return self.interaction.guild
        elif self.message is not None:
            return self.message.guild
        else:
            raise 'invalid state'

    @property
    def user(self):
        if self.interaction is not None:
            return self.interaction.user
        elif self.message is not None:
            return self.message.author
        else:
            raise 'invalid state'

    @property
    def channel(self):
        if self.overriden_channel:
            return self.overriden_channel
        if self.interaction is not None:
            return self.interaction.channel
        elif self.message is not None:
            return self.message.channel
        else:
            raise 'invalid state'

    def override_channel(self, channel):
        self.overriden_channel = channel

    @property
    def application_id(self):
        if self.interaction is not None:
            return self.interaction.application_id
        elif self.message is not None:
            return None
        else:
            raise 'invalid state'

    @property
    def locale(self):
        if self.interaction is not None:
            return self.interaction.locale
        elif self.message is not None:
            return None
        else:
            raise 'invalid state'