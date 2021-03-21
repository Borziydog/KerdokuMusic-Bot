import os
import config
import discord
import threading
from rabbitmq import ServerRPC
from datetime import datetime
from discord.ext import commands
from database import Settings as DB
from utils.CommandErrorHandler import CommandErrorHandler

intents = discord.Intents.default()
intents.guilds = True  # Сервера
intents.members = False  # Мемберы
intents.bans = False  # Баны
intents.emojis = True  # Эмодзи

intents.integrations = False  # Ивент - Интеграции Сервера
intents.webhooks = False  # Ивент - Вебхуки
intents.invites = False  # Ивент - Создание Удаление Приглашений
intents.voice_states = True  # Ивент - Проверка обновлений войса
intents.presences = False  # Ивент - Обновление пользователя

intents.messages = True  # Ивент - Сообщения | Действие - Добавление Реакций
intents.guild_messages = True  # На сервере
intents.dm_messages = True  # ЛС

intents.reactions = True  # Ивент - Реакции
intents.guild_reactions = True  # На сервере
intents.dm_reactions = True  # В лс

intents.typing = False  # Ивент - Кто-то вводит текст
intents.guild_typing = False  # На сервере
intents.dm_typing = False  # В лс


class MusicBot(commands.AutoShardedBot):
    def __init__(self):
        super().__init__(command_prefix=self.prefix, owners=config.OWNERS,
                         allowed_mentions=discord.AllowedMentions(everyone=False, users=True, roles=False),
                         status=discord.Status.online, activity=discord.Game(name=config.STATUS),
                         intents=intents)
        self.remove_command("help")

    def setup(self):
        print(f"\n\n[{datetime.now().strftime('%H:%M:%S')}] Загружаю Коги...")

        # loading cogs
        for file in os.listdir('./cogs'):
            if file.endswith(".py"):
                if file[:-3] not in config.COGS_IGNORE:
                    try:
                        self.load_extension(f'cogs.{file[:-3]}')
                    except commands.errors.NoEntryPointError:
                        print(f"|| Не Загружен Ког - {file[:-3]} \t(Отсуствует SETUP функция)")
                    except Exception as error:
                        print(f"|| Не Загружен Ког - {file[:-3]} \t({error})")
                    else:
                        print(f"||    Загружен Ког - {file[:-3]}")

        print(f"[{datetime.now().strftime('%H:%M:%S')}] Коги загружены.\n")

    def run(self):
        self.setup()

        print(f"[{datetime.now().strftime('%H:%M:%S')}] Бот Запускается...")

        if config.RABBITMQ_ENABLE:
            thread = threading.Thread(target=self._rabbit, args=(client,))
            thread.start()

            print(f"[{datetime.now().strftime('%H:%M:%S')}]   Бот подключен к RabbitMQ.")
        else:
            print(f"[{datetime.now().strftime('%H:%M:%S')}]   RabbitMQ отключен в конфиге.")

        super().run(config.TOKEN, reconnect=True)

    @staticmethod
    def _rabbit(client):
        rabbitmq = ServerRPC(client=client)
        rabbitmq.start()

    async def shutdown(self):
        print(f"[{datetime.now().strftime('%H:%M:%S')}] Закрытие подключения с Discord...")
        await super().close()

    async def close(self):
        print(f"[{datetime.now().strftime('%H:%M:%S')}] Отключение Бота...")
        await self.shutdown()

    async def on_connect(self):
        print(f"[{datetime.now().strftime('%H:%M:%S')}]   Бот подключен к Discord (пинг: {self.latency * 1000:,.0f} ms).")

    async def on_resumed(self):
        print(f"[{datetime.now().strftime('%H:%M:%S')}] Бот подключился.")

    async def on_disconnect(self):
        print(f"[{datetime.now().strftime('%H:%M:%S')}] Бот отключился.")

    async def on_ready(self):
        self.client_id = (await self.application_info()).id
        print("Бот запущен.\n")
        print(f"ID - {self.user.id}")
        print(f"Никнейм - {self.user.name}#{self.user.discriminator}")
        print(f"Серверов - {len(self.guilds)}")
        print(f"Время - {datetime.now().strftime('%H:%M:%S')}")

    async def on_message_edit(self, before, message):
        if message.author.bot:
            return
        if not message.guild:
            return
        await self.process_commands(message)

    @staticmethod
    async def prefix(bot, ctx):
        if ctx.guild is not None:
            Settings = await DB.Select(one_used=True).prefix(guild=ctx.guild)
            if Settings is None:
                prefix = config.PREFIX
            else:
                prefix = Settings["prefix"]

            return commands.when_mentioned_or(prefix)(bot, ctx)
        return "None"

    async def process_commands(self, msg):
        ctx = await self.get_context(msg, cls=commands.Context)

        #if ctx.command is not None:
        await self.invoke(ctx)

    async def on_message(self, msg):
        if msg.guild is not None:
            if not msg.author.bot:
                await self.process_commands(msg)

    async def on_command_error(self, ctx, error):
        await CommandErrorHandler.handler(ctx, error, True)
        return


client = MusicBot()
client.run()
