import asyncio
import async_timeout
import copy
import datetime
import discord
import math
import random
import re
import config
import typing
import wavelink
from discord.ext import commands, menus, tasks
from database import Settings as DB
from database import Backend as DB_B
from utils import Translates as TR

# URL matching REGEX...
URL_REG = re.compile(r'https?://(?:www\.)?.+')
OPTIONS = {
    "1️⃣": 0,
    "2⃣": 1,
    "3⃣": 2,
    "4⃣": 3,
    "5⃣": 4,
}

# СВЕТЛО ЧЁРНЫЕ КОШКИ
class IsConnected(commands.CommandError):
    """Ошибка когда бот уже подключен к каналу"""
    pass


class IsNotConnected(commands.CommandError):
    """Ошибка когда бот не подключен к каналу к которому привязан плеер"""
    pass


class NoChannelProvided(commands.CommandError):
    """Ошибка когда не указан подходящий голосовой канал."""
    pass


class IncorrectChannelError(commands.CommandError):
    """Ошибка, когда команды выдаются вне канала сеанса плеера."""
    pass


# САМ КОТ
class Track(wavelink.Track):
    """Объект Wavelink Track с атрибутом запрашивающего."""

    __slots__ = ('requester',)

    def __init__(self, *args, **kwargs):
        super().__init__(*args)

        self.requester = kwargs.get('requester')


class Player(wavelink.Player):
    """Кастомный wavelink Player класс."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

        self.context: commands.Context = kwargs.get('context', None)

        self.queue = asyncio.Queue()
        self.controller = None

        self.waiting = False
        self.updating = False

        self.pause_votes = set()
        self.resume_votes = set()
        self.skip_votes = set()
        self.shuffle_votes = set()
        self.stop_votes = set()

    async def do_next(self) -> None:
        if self.is_playing or self.waiting:
            return

        # Очистить голоса за новую песню...
        self.pause_votes.clear()
        self.resume_votes.clear()
        self.skip_votes.clear()
        self.shuffle_votes.clear()
        self.stop_votes.clear()

        try:
            self.waiting = True
            with async_timeout.timeout(300):
                track = await self.queue.get()
        except asyncio.TimeoutError:
            # Никакой музыки 5 минут не играет, чистим очередь и отключаем бота от канал...
            return await self.teardown()

        await self.play(track)
        self.waiting = False

        # Вызов нашего контроллера плееров...
        await self.invoke_controller()

    async def choose_track(self, ctx, tracks):
        def _check(r, u):
            return (
                    r.emoji in OPTIONS.keys()
                    and u == ctx.author
                    and r.message.id == msg.id
            )

        lang = await TR.lang(ctx.guild)
        lang = lang["music"]

        embed = discord.Embed(
            title=lang["choose_track"],
            description=(
                "\n".join(
                    f"**{i + 1}.** {t.title} ({t.length // 60000}:{str(t.length % 60).zfill(2)})"
                    for i, t in enumerate(tracks[:5])
                )
            ),
            colour=ctx.author.colour,
            timestamp=datetime.datetime.utcnow()
        )
        embed.set_author(name=lang["footer"]["author"])
        embed.set_footer(text=lang["footer"]["text"].format(author=ctx.author.display_name), icon_url=ctx.author.avatar_url)

        msg = await ctx.send(embed=embed)
        for emoji in list(OPTIONS.keys())[:min(len(tracks), len(OPTIONS))]:
            await msg.add_reaction(emoji)
        
        try:
            try:
                reaction, _ = await self.bot.wait_for("reaction_add", timeout=60.0, check=_check)
            except asyncio.TimeoutError:
                await msg.delete()
            else:
                await msg.delete()
                return tracks[OPTIONS[reaction.emoji]]
        except discord.errors.NotFound:
            pass

    async def invoke_controller(self) -> None:
        """Метод, который обновляет или отправляет новый контроллер плееров."""
        if self.updating:
            return

        if self.current is None:
            return

        if not self.channel_id:
            return

        self.updating = True

        if not self.controller:
            self.controller = InteractiveController(embed=await self.build_embed(), player=self)
            try:
                await self.controller.start(self.context)
            except AttributeError as error:
                print("==== ERROR ====")
                print("==== ERROR ====")
                print("==== ERROR ====")
                channel = self.context.channel
                print(f"channel: {channel}")
                me = self.context.guild.me if isinstance(channel, discord.abc.GuildChannel) else self.context.bot.user
                print(f"self.context.guild.me: {self.context.guild.me}")
                print(f"isinstance(channel, discord.abc.GuildChannel): {isinstance(channel, discord.abc.GuildChannel)}")
                print(f"self.context.bot.user: {self.context.bot.user}")
                print(f"me: {me}")
                print("==== ERROR ====")
                print("==== ERROR ====")
                print("==== ERROR ====")
                raise error

        elif not await self.is_position_fresh():
            try:
                await self.controller.message.delete()
            except discord.HTTPException:
                pass

            self.controller.stop()

            self.controller = InteractiveController(embed=await self.build_embed(), player=self)
            await self.controller.start(self.context)

        else:
            embed = await self.build_embed()
            await self.controller.message.edit(content=None, embed=embed)

        self.updating = False

    async def build_embed(self) -> typing.Optional[discord.Embed]:
        """Метод, который создаёт ембед контроллера плеера."""

        track = self.current
        channel = self.bot.get_channel(int(self.channel_id))
        qsize = self.queue.qsize()

        lang = await TR.lang(self.context.guild)
        lang = lang["music"]["player"]

        embed = discord.Embed(title=lang["title"].format(channel=channel), color=config.COLORS['base'])
        embed.description = lang["description"].format(track=track)
        if hasattr(track, 'thumb'):
            embed.set_thumbnail(url=track.thumb)
        if hasattr(track, 'requester'):
            embed.add_field(name=lang["requester"], value=track.requester)
        embed.add_field(name=lang["qsize"], value=str(qsize))
        embed.add_field(name=lang["volume"], value=f'**`{self.volume}%`**')
        embed.add_field(name=lang["equalizer"], value=f'{self.equalizer}')

        if hasattr(track, 'author'):
            embed.add_field(name=lang["author"], value=f'{track.author}')
        if not track.is_stream:
            embed.set_footer(text=lang["length"].format(length=str(datetime.timedelta(milliseconds=int(track.length)))))
        else:
            embed.set_footer(text=lang["stream"])

        return embed

    async def is_position_fresh(self) -> bool:
        """Метод, который проверяет, нужно ли переделывать или обновлять контроллер плеера."""
        try:
            async for message in self.context.channel.history(limit=5):
                if message.id == self.controller.message.id:
                    return True
        except (discord.HTTPException, AttributeError):
            return False

        return False

    async def teardown(self):
        """Очищает внутренние состояния, удаляет контроллер плеера и отключает бота от канала."""
        try:
            await self.controller.message.delete()
        except discord.HTTPException:
            pass
        except AttributeError:
            pass

        try:
            self.controller.stop()
        except AttributeError:
            pass

        try:
            await self.destroy()
        except KeyError:
            pass
        except wavelink.errors.InvalidIDProvided:
            pass


class InteractiveController(menus.Menu):
    """Класс меню интерактивного контроллера плеера."""

    def __init__(self, *, embed: discord.Embed, player: Player):
        super().__init__(timeout=None)

        self.embed = embed
        self.player = player

    def update_context(self, payload: discord.RawReactionActionEvent):
        """Обновить контекст с помощью указаного пользователя, который установил реакцию."""
        ctx = copy.copy(self.ctx)
        ctx.author = payload.member

        return ctx

    def reaction_check(self, payload: discord.RawReactionActionEvent):
        if payload.event_type == 'REACTION_REMOVE':
            return False

        if not payload.member:
            return False
        if payload.member.bot:
            return False
        if payload.message_id != self.message.id:
            return False
        if payload.member not in self.bot.get_channel(int(self.player.channel_id)).members:
            return False

        return payload.emoji in self.buttons

    async def send_initial_message(self, ctx: commands.Context, channel: discord.TextChannel) -> discord.Message:
        try:
            return await channel.send(embed=self.embed)
        except discord.errors.NotFound:
            pass
        except Exception as error:
            print("---------- ОШИБКА ОШИБКА ОШИБКА -------------")
            print("---------- ОШИБКА ОШИБКА ОШИБКА -------------")
            print("---------- ОШИБКА ОШИБКА ОШИБКА -------------")
            print("---------- ОШИБКА ОШИБКА ОШИБКА -------------")
            print(f"\nerror: {error}")
            print(f"self.embed: {self.embed}\n")
            print(f"channel: {channel}")
            print("---------- ОШИБКА ОШИБКА ОШИБКА -------------")
            print("---------- ОШИБКА ОШИБКА ОШИБКА -------------")
            print("---------- ОШИБКА ОШИБКА ОШИБКА -------------")
            print("---------- ОШИБКА ОШИБКА ОШИБКА -------------")
            raise error

    @menus.button(emoji='\u25B6')
    async def resume_command(self, payload: discord.RawReactionActionEvent):
        """Кнопка возобновления."""
        ctx = self.update_context(payload)

        command = self.bot.get_command('resume')
        ctx.command = command

        await self.bot.invoke(ctx)

    @menus.button(emoji='\u23F8')
    async def pause_command(self, payload: discord.RawReactionActionEvent):
        """Кнопка паузы."""
        ctx = self.update_context(payload)

        command = self.bot.get_command('pause')
        ctx.command = command

        await self.bot.invoke(ctx)

    @menus.button(emoji='\u23F9')
    async def stop_command(self, payload: discord.RawReactionActionEvent):
        """Кнопка остановки."""
        ctx = self.update_context(payload)

        command = self.bot.get_command('stop')
        ctx.command = command

        await self.bot.invoke(ctx)

    @menus.button(emoji='\u23ED')
    async def skip_command(self, payload: discord.RawReactionActionEvent):
        """Кнопка скипа трека."""
        ctx = self.update_context(payload)

        command = self.bot.get_command('skip')
        ctx.command = command

        await self.bot.invoke(ctx)

    @menus.button(emoji='\U0001F500')
    async def shuffle_command(self, payload: discord.RawReactionActionEvent):
        """Кнопка перемешивания."""
        ctx = self.update_context(payload)

        command = self.bot.get_command('shuffle')
        ctx.command = command

        await self.bot.invoke(ctx)

    @menus.button(emoji='\u2795')
    async def volup_command(self, payload: discord.RawReactionActionEvent):
        """Кнопка повышения громкости"""
        ctx = self.update_context(payload)

        command = self.bot.get_command('vol_up')
        ctx.command = command

        await self.bot.invoke(ctx)

    @menus.button(emoji='\u2796')
    async def voldown_command(self, payload: discord.RawReactionActionEvent):
        """Кнопка понижения громкости."""
        ctx = self.update_context(payload)

        command = self.bot.get_command('vol_down')
        ctx.command = command

        await self.bot.invoke(ctx)

    @menus.button(emoji='\U0001F1F6')
    async def queue_command(self, payload: discord.RawReactionActionEvent):
        """Кнопка показа очереди плеера."""
        ctx = self.update_context(payload)

        command = self.bot.get_command('queue')
        ctx.command = command

        await self.bot.invoke(ctx)


class PaginatorSource(menus.ListPageSource):
    """Класс пагинатора очереди Плеера."""

    def __init__(self, entries, *, per_page=8):
        super().__init__(entries, per_page=per_page)

    async def format_page(self, menu: menus.Menu, page):
        embed = discord.Embed(
            title="Очередь",
            description='\n'.join(f'**{index}.** `{title}`' for index, title in enumerate(page, 1)),
            color=config.COLORS["base"],
        )

        return embed

    def is_paginating(self):
        # Хотим ли мы ембед даже на 1 страницу результатов... (We always want to embed even on 1 page of results)
        return True


class Music(commands.Cog, wavelink.WavelinkMixin, name="Музыкальное"):
    """Всё что связано с музыкой"""

    def __init__(self, bot: commands.Bot):
        self.bot = bot

        if not hasattr(bot, 'wavelink'):
            bot.wavelink = wavelink.Client(bot=bot)

        bot.loop.create_task(self.start_nodes())
        self.status.start()

    def cog_unload(self):
        self.status.cancel()

    def cog_reload(self):
        self.status.cancel()

    @tasks.loop(seconds=30)
    async def status(self):
        if not config.DEBUG:
            await self.bot.wait_until_ready()
            if self.bot.user is None:
                pass
            else:
                if await DB_B.Select(one_used=True).status(self.bot) is None:
                    await DB_B.Create(one_used=True).status(self.bot)
                else:
                    await DB_B.Update(one_used=True).status(self.bot)

                nodes = config.NODES
                for node_ind in nodes.keys():
                    if node_ind is not None:
                        node = self.bot.wavelink.get_node(node_ind)
                        if node is not None:
                            players_total = 0
                            players_playing = 0
                            players_connected = 0
                            players_paused = 0
                            players_unknown = 0
                            for player in self.bot.wavelink.players:
                                if player is None:
                                    continue
                                player = node.get_player(player)
                                if player is not None:
                                    players_total += 1
                                    if player.is_playing:
                                        players_playing += 1
                                    elif player.is_connected:
                                        players_connected += 1
                                    elif player.is_paused:
                                        players_paused += 1
                                    else:
                                        players_unknown += 1

                            players = {"total": players_total, "playing": players_playing, "connected": players_connected, "paused": players_paused, "unknown": players_unknown}

                            if await DB_B.Select(one_used=True).wavelink(identifier=node.identifier) is None:
                                await DB_B.Create(one_used=True).wavelink(node, players)
                            else:
                                await DB_B.Update(one_used=True).wavelink(node, players)

    async def start_nodes(self) -> None:
        """Подключение и инициирует узлы."""
        await self.bot.wait_until_ready()

        if self.bot.wavelink.nodes:
            previous = self.bot.wavelink.nodes.copy()

            for node in previous.values():
                await node.destroy()

        nodes = config.NODES
        for n in nodes.values():
            await self.bot.wavelink.initiate_node(**n)

    @wavelink.WavelinkMixin.listener()
    async def on_node_ready(self, node: wavelink.Node):
        print(f'  Wavelink Node - {node.identifier} Готов!')

    @wavelink.WavelinkMixin.listener('on_track_stuck')
    @wavelink.WavelinkMixin.listener('on_track_end')
    @wavelink.WavelinkMixin.listener('on_track_exception')
    async def on_player_stop(self, node: wavelink.Node, payload):
        await payload.player.do_next()

    @commands.Cog.listener()
    async def on_voice_state_update(self, member: discord.Member, before: discord.VoiceState, after: discord.VoiceState):
        if member.bot:
            return

        player: Player = self.bot.wavelink.get_player(member.guild.id, cls=Player)
        if not player.channel_id or not player.context:
            await player.teardown()
            return

        channel = self.bot.get_channel(int(player.channel_id))
        if channel is not None:
            if not [m for m in channel.members if not m.bot]:
                await player.teardown()

    async def cog_command_error(self, ctx: commands.Context, error):
        """Обработчик ошибок Кога."""
        lang_ = await TR.lang(ctx.guild)
        lang = lang_["music"]["errors"]["voice"]

        if isinstance(error, IncorrectChannelError): #'Вы не находитесь в голосовом канале',
            return

        if isinstance(error, NoChannelProvided):
            return await ctx.send(embed=discord.Embed(title=lang_["errors"]["types"]["voice"],
                                                      description=lang["user"],
                                                      color=config.COLORS["error"]), delete_after=15)
        elif isinstance(error, IsNotConnected):
            return await ctx.send(embed=discord.Embed(title=lang_["errors"]["types"]["voice"],
                                                      description=lang["bot"],
                                                      color=config.COLORS["error"]), delete_after=15)

    async def cog_check(self, ctx: commands.Context):
        """Проверка Кога, которая запрещает команды в DM."""
        lang_ = await TR.lang(ctx.guild)
        lang = lang_["music"]["errors"]
        
        if not ctx.guild:
            await ctx.send(embed=discord.Embed(title=lang_["errors"]["types"]["permission"],
                                               description=lang["dm"],
                                               color=config.COLORS["error"]))
            return False

        return True

    async def cog_before_invoke(self, ctx: commands.Context):
        """Coroutine вызывается перед вызовом команды.
        В основном мы просто хотим проверить, находится ли пользователь в канале контроллера проигрывателя.
        """
        player: Player = self.bot.wavelink.get_player(ctx.guild.id, cls=Player, context=ctx)
        lang_ = await TR.lang(ctx.guild)
        lang = lang_["music"]["errors"]

        if player.context:
            if player.context.channel != ctx.channel:
                return await ctx.send(
                    embed=discord.Embed(title=lang["session"]["title"],
                    description=lang["session"]["description"].format(author=ctx.author, channel=player.context.channel),
                    color=config.COLORS["error"]), delete_after=15)

        if ctx.command.name == 'connect' and not player.context:
            return
        elif await self.is_privileged(ctx):
            return

        if not player.channel_id:
            return

        channel = self.bot.get_channel(int(player.channel_id))
        if not channel:
            return

        if player.is_connected:
            if ctx.author not in channel.members:
                return await ctx.send(
                    embed=discord.Embed(title=lang_["errors"]["types"]["voice"],
                                        description=lang["voice"]["channel"].format(author=ctx.author.mention, channel=channel),
                                        color=config.COLORS["error"]), delete_after=15)

    def required(self, ctx: commands.Context):
        """Метод, который возвращает необходимые голоса в зависимости от количества участников в канале."""
        player: Player = self.bot.wavelink.get_player(guild_id=ctx.guild.id, cls=Player, context=ctx)
        channel = self.bot.get_channel(int(player.channel_id))
        required = math.ceil((len(channel.members) - 1) / 2.5)

        if ctx.command.name == 'stop':
            if len(channel.members) - 1 == 2:
                required = 2

        return required

    async def is_privileged(self, ctx: commands.Context):
        """Проверить является ли пользователь администратором или ди-джеем и настроен ли вообще диджей."""
        Settings = await DB.Select(one_used=True).music(guild=ctx.guild)
        if Settings is not None:
            if Settings["djrole"] is not None:
                if Settings["djrole"] != 'null':
                    if discord.utils.get(ctx.author.roles, id=int(Settings["djrole"])) is None:
                        if not ctx.author.guild_permissions.administrator:
                            return False
        return True

    @commands.command(
        name="подключить",
        aliases=["connect", "join", "коннект", "зайти", "войти"],
        usage="подключить [Канал]",
        description="Подключить бота к голосовому каналу")
    async def connect(self, ctx: commands.Context, *, channel: discord.VoiceChannel = None):
        """Подключиться к голосовому каналу."""
        player: Player = self.bot.wavelink.get_player(guild_id=ctx.guild.id, cls=Player, context=ctx)
        lang_ = await TR.lang(ctx.guild)
        lang = lang_["music"]["errors"]

        if not await self.is_privileged(ctx):
            return await ctx.send(
                embed=discord.Embed(title=lang_["errors"]["types"]["permission"],
                                    description=lang["dj"],
                                    color=config.COLORS['error']), delete_after=10)

        if player.is_connected:
            await ctx.send(embed=discord.Embed(title=lang_["errors"]["types"]["voice"],
                                               description=lang["voice"]["bot_connected"],
                                               color=config.COLORS["error"]), delete_after=15)

        channel = getattr(ctx.author.voice, 'channel', channel)
        if channel is None:
            return False

        await player.connect(channel.id)
        return True

    @commands.command(
        name="плей",
        aliases=["play", "p"],
        usage="плей [Название/URL]",
        description="Начать/Продолжить воспроизводение музыки")
    #@commands.bot_has_permissions(add_reactions=True)
    async def play(self, ctx: commands.Context, *, query: str):
        """Воспроизведение или добавление в очередь песни с заданным запросом."""
        player: Player = self.bot.wavelink.get_player(guild_id=ctx.guild.id, cls=Player, context=ctx)
        lang_ = await TR.lang(ctx.guild)
        lang = lang_["music"]["errors"]

        if not await self.is_privileged(ctx):
            return await ctx.send(
                embed=discord.Embed(title=lang_["errors"]["types"]["permission"],
                                    description=lang["dj"],
                                    color=config.COLORS['error']), delete_after=10)

        if not player.is_connected:
            check = await ctx.invoke(self.connect)
            if not check:
                return await ctx.send(embed=discord.Embed(title=lang_["errors"]["types"]["voice"],
                                                          description=lang["voice"]["user"],
                                                          color=config.COLORS["error"]), delete_after=15)

        if player.is_playing:
            if getattr(ctx.author, 'voice'):
                if str(ctx.author.voice.channel.id) != str(player.channel_id):
                    return await ctx.send(embed=discord.Embed(title=lang_["errors"]["types"]["voice"],
                                                              description=lang["voice"]["user_bot"],
                                                              color=config.COLORS["error"]), delete_after=15)
            else:
                return await ctx.send(embed=discord.Embed(title=lang_["errors"]["types"]["voice"],
                                                          description=lang["voice"]["user_bot"],
                                                          color=config.COLORS["error"]), delete_after=15)

        query = query.strip('<>')
        if not URL_REG.match(query):
            query = f'ytsearch:{query}'

        playlist = await self.bot.wavelink.get_tracks(query)
        if not playlist:
            return await ctx.send(lang["notfoundtrack"], delete_after=15)

        limit_queue = 100
        limit_time = 10800_000
        Options = await DB.Select(one_used=True).music(guild=ctx.guild)
        if Options is not None:
            if Options["maxqueuelength"] is not None: limit_queue = int(Options["maxqueuelength"])
            if Options["maxsonglength"] is not None: limit_time = int(Options["maxsonglength"])

        if player.queue is not None:
            qsize = player.queue.qsize()
            if int(qsize) > limit_queue:
                return await ctx.send(lang["limits"]["queue"].format(limit=limit_queue), delete_after=25)

        if isinstance(playlist, wavelink.TrackPlaylist):
            tracks = playlist.tracks
        else:
            tracks = playlist

        check = False
        if len(tracks) == 1:
            check = True

        for track in tracks:
            try:
                if track.is_stream:
                    continue
                if track.length / 1000 > limit_time:
                    if check:
                        return await ctx.send(
                            lang["limits"]["length"].format(
                                track=track,
                                length=str(datetime.timedelta(milliseconds=track.length)),
                                limit=str(datetime.timedelta(seconds=limit_time))), delete_after=15)
                    else:
                        await ctx.send(
                            lang["limits"]["playlist_length"].format(
                                track=track,
                                length=str(datetime.timedelta(milliseconds=track.length)),
                                limit=str(datetime.timedelta(seconds=limit_time))), delete_after=15)
                        tracks.remove(track)
            except OverflowError:
                return await ctx.send(lang["limits"]["error_length"].format(track=track), delete_after=15)

        track_info = None
        if isinstance(playlist, wavelink.TrackPlaylist):
            for track in tracks:
                track = Track(track.id, track.info, requester=ctx.author)
                await player.queue.put(track)
            track_info = tracks[0]
        else:
            if check:
                await player.queue.put(tracks[0])
                track_info = tracks[0]
            elif (track := await player.choose_track(ctx, tracks)) is not None:
                await player.queue.put(track)
                track_info = track

        if track_info is None:
            track_info = tracks[0]

        if not player.is_connected:
            check = await ctx.invoke(self.connect)
            if not check:
                await player.teardown()
                return await ctx.send(embed=discord.Embed(title=lang_["errors"]["types"]["voice"],
                                                          description=lang["voice"]["user"],
                                                          color=config.COLORS["error"]), delete_after=15)

        if player.is_playing:
            player_lang = lang_["music"]["player"]
            if isinstance(playlist, wavelink.TrackPlaylist):
                embed = discord.Embed(title=playlist.data["playlistInfo"]["name"],
                                      color=config.COLORS['base'])
                embed.add_field(name=player_lang["requester"], value=ctx.author.display_name)
                embed.add_field(name=player_lang["tracks"], value=f"{len(tracks)}")
                embed.add_field(name=player_lang["channel"],
                                value=discord.utils.get(ctx.guild.channels, id=player.channel_id).mention)
                if not hasattr(track_info, 'thumb'):
                    embed.set_thumbnail(url=track_info.thumb)

            else:
                embed = discord.Embed(title=track_info.title, url=track_info.uri, color=config.COLORS['base'])
                embed.add_field(name=player_lang["requester"], value=ctx.author.display_name)
                embed.add_field(name=player_lang["channel"],
                                value=discord.utils.get(ctx.guild.channels, id=player.channel_id).mention)
                if track_info.thumb is not None:
                    embed.set_thumbnail(url=track_info.thumb)
                if not track_info.is_stream:
                    embed.set_footer(text=player_lang["length"].format(length=str(datetime.timedelta(milliseconds=track_info.length))))
                else:
                    embed.set_footer(text=player_lang["stream"])

            await ctx.send(embed=embed, delete_after=30)

        if not player.is_playing:
            await player.do_next()

    @commands.command(
        name="пауза",
        aliases=["pause"],
        usage="пауза",
        description="Поставить музыку на паузу")
    async def pause(self, ctx: commands.Context):
        """Приостановить воспроизведение текущей песни."""
        player: Player = self.bot.wavelink.get_player(guild_id=ctx.guild.id, cls=Player, context=ctx)
        lang_ = await TR.lang(ctx.guild)
        lang = lang_["music"]["errors"]

        if player.is_playing:
            if getattr(ctx.author, 'voice'):
                if str(ctx.author.voice.channel.id) != str(player.channel_id):
                    return await ctx.send(embed=discord.Embed(title=lang_["errors"]["types"]["voice"],
                                                              description=lang["voice"]["user_bot"],
                                                              color=config.COLORS["error"]), delete_after=15)
            else:
                return await ctx.send(embed=discord.Embed(title=lang_["errors"]["types"]["voice"],
                                                          description=lang["voice"]["user_bot"],
                                                          color=config.COLORS["error"]), delete_after=15)

        if player.is_paused:
            await ctx.send(lang_["music"]["pause"]["error"], delete_after=10)
        if not player.is_connected:
            return await ctx.send(embed=discord.Embed(title=lang_["errors"]["types"]["voice"],
                                                      description=lang["voice"]["bot"],
                                                      color=config.COLORS["error"]), delete_after=15)

        if await self.is_privileged(ctx):
            await ctx.send(lang_["music"]["pause"]["success"], delete_after=10)
            player.pause_votes.clear()

            return await player.set_pause(True)

        required = self.required(ctx)
        player.pause_votes.add(ctx.author)
        votes = len(player.pause_votes)
        if votes >= required:
            await ctx.send(lang_["music"]["pause"]["vote"]["success"].format(votes=votes, required=required), delete_after=10)
            player.pause_votes.clear()
            await player.set_pause(True)
        else:
            await ctx.send(lang_["music"]["pause"]["vote"]["voted"].format(votes=votes, required=required, author=ctx.author), delete_after=10)

    @commands.command(
        name="возобновить",
        aliases=["resume"],
        usage="возобновить",
        description="Возобновить проигрывание треков плеером")
    async def _resume(self, ctx: commands.Context):
        """Возобновить приостановленного в данный момент игрока."""
        player: Player = self.bot.wavelink.get_player(guild_id=ctx.guild.id, cls=Player, context=ctx)
        lang_ = await TR.lang(ctx.guild)
        lang = lang_["music"]["errors"]

        if player.is_playing:
            if getattr(ctx.author, 'voice'):
                if str(ctx.author.voice.channel.id) != str(player.channel_id):
                    return await ctx.send(embed=discord.Embed(title=lang_["errors"]["types"]["voice"],
                                                              description=lang["voice"]["user_bot"],
                                                              color=config.COLORS["error"]), delete_after=15)
            else:
                return await ctx.send(embed=discord.Embed(title=lang_["errors"]["types"]["voice"],
                                                          description=lang["voice"]["user_bot"],
                                                          color=config.COLORS["error"]), delete_after=15)

        if not player.is_paused:
            await ctx.send(lang_["music"]["resume"]["error"], delete_after=10)
        if not player.is_connected:
            return await ctx.send(embed=discord.Embed(title=lang_["errors"]["types"]["voice"],
                                                      description=lang["voice"]["bot"],
                                                      color=config.COLORS["error"]), delete_after=15)

        if await self.is_privileged(ctx):
            await ctx.send(lang_["music"]["resume"]["success"], delete_after=10)
            player.resume_votes.clear()

            return await player.set_pause(False)

        required = self.required(ctx)
        player.resume_votes.add(ctx.author)
        votes = len(player.resume_votes)

        if votes >= required:
            await ctx.send(lang_["music"]["resume"]["vote"]["success"].format(votes=votes, required=required),
                           delete_after=10)
            player.resume_votes.clear()
            await player.set_pause(False)
        else:
            await ctx.send(
                lang_["music"]["resume"]["vote"]["voted"].format(votes=votes, required=required, author=ctx.author),
                delete_after=10)

    @commands.command(
        name="скип",
        aliases=["skip", "пропуск", "next"],
        usage="пропуск",
        description="Пропустить текущий трек")
    async def _skip(self, ctx: commands.Context):
        """Пропустить песню, которая воспроизводится в данный момент."""
        player: Player = self.bot.wavelink.get_player(guild_id=ctx.guild.id, cls=Player, context=ctx)
        lang_ = await TR.lang(ctx.guild)
        lang = lang_["music"]["errors"]

        if not player.is_connected:
            return await ctx.send(embed=discord.Embed(title=lang_["errors"]["types"]["voice"],
                                                      description=lang["voice"]["bot"],
                                                      color=config.COLORS["error"]), delete_after=15)

        if player.is_playing:
            if getattr(ctx.author, 'voice'):
                if str(ctx.author.voice.channel.id) != str(player.channel_id):
                    return await ctx.send(embed=discord.Embed(title=lang_["errors"]["types"]["voice"],
                                                              description=lang["voice"]["user_bot"],
                                                              color=config.COLORS["error"]), delete_after=15)
            else:
                return await ctx.send(embed=discord.Embed(title=lang_["errors"]["types"]["voice"],
                                                          description=lang["voice"]["user_bot"],
                                                          color=config.COLORS["error"]), delete_after=15)

        if await self.is_privileged(ctx):
            await ctx.send(lang_["music"]["skip"]["success"], delete_after=10)
            player.skip_votes.clear()

            return await player.stop()

        if ctx.author == player.current.requester:
            await ctx.send(lang_["music"]["skip"]["author"], delete_after=10)
            player.skip_votes.clear()

            return await player.stop()

        required = self.required(ctx)
        player.skip_votes.add(ctx.author)
        votes = len(player.skip_votes)

        if votes >= required:
            await ctx.send(lang_["music"]["skip"]["vote"]["success"].format(votes=votes, required=required),
                           delete_after=10)
            player.skip_votes.clear()
            await player.stop()
        else:
            await ctx.send(
                lang_["music"]["skip"]["vote"]["voted"].format(votes=votes, required=required, author=ctx.author),
                delete_after=10)

    @commands.command(
        name="стоп",
        aliases=["stop", "s"],
        usage="стоп",
        description="Остановить воспроизведение музыки")
    async def _stop(self, ctx: commands.Context):
        """Остановить плеер и очистить все внутренние состояния."""
        player: Player = self.bot.wavelink.get_player(guild_id=ctx.guild.id, cls=Player, context=ctx)
        lang_ = await TR.lang(ctx.guild)
        lang = lang_["music"]["errors"]

        if not player.is_connected:
            return await ctx.send(embed=discord.Embed(title=lang_["errors"]["types"]["voice"],
                                                      description=lang["voice"]["bot"],
                                                      color=config.COLORS["error"]), delete_after=15)

        if player.is_playing:
            if getattr(ctx.author, 'voice'):
                if str(ctx.author.voice.channel.id) != str(player.channel_id):
                    return await ctx.send(embed=discord.Embed(title=lang_["errors"]["types"]["voice"],
                                                              description=lang["voice"]["user_bot"],
                                                              color=config.COLORS["error"]), delete_after=15)
            else:
                return await ctx.send(embed=discord.Embed(title=lang_["errors"]["types"]["voice"],
                                                          description=lang["voice"]["user_bot"],
                                                          color=config.COLORS["error"]), delete_after=15)

        if await self.is_privileged(ctx):
            await ctx.send(lang_["music"]["stop"]["success"], delete_after=10)
            return await player.teardown()

        required = self.required(ctx)
        player.stop_votes.add(ctx.author)
        votes = len(player.stop_votes)

        if votes >= required:
            await ctx.send(lang_["music"]["stop"]["vote"]["success"].format(votes=votes, required=required),
                           delete_after=10)
            player.stop_votes.clear()
            await player.teardown()
        else:
            await ctx.send(
                lang_["music"]["stop"]["vote"]["voted"].format(votes=votes, required=required, author=ctx.author),
                delete_after=10)

    @commands.command(
        name="громкость",
        aliases=["volume", "v"],
        usage="громкость <Процент>",
        description="Изменить громкость воспроизвидения музыки")
    async def _volume(self, ctx: commands.Context, *, vol: int):
        """Change the players volume, between 1 and 100."""
        player: Player = self.bot.wavelink.get_player(guild_id=ctx.guild.id, cls=Player, context=ctx)
        lang_ = await TR.lang(ctx.guild)
        lang = lang_["music"]["errors"]

        if not player.is_connected:
            return await ctx.send(embed=discord.Embed(title=lang_["errors"]["types"]["voice"],
                                                      description=lang["voice"]["bot"],
                                                      color=config.COLORS["error"]), delete_after=15)

        if player.is_playing:
            if getattr(ctx.author, 'voice'):
                if str(ctx.author.voice.channel.id) != str(player.channel_id):
                    return await ctx.send(embed=discord.Embed(title=lang_["errors"]["types"]["voice"],
                                                              description=lang["voice"]["user_bot"],
                                                              color=config.COLORS["error"]), delete_after=15)
            else:
                return await ctx.send(embed=discord.Embed(title=lang_["errors"]["types"]["voice"],
                                                          description=lang["voice"]["user_bot"],
                                                          color=config.COLORS["error"]), delete_after=15)

        if not await self.is_privileged(ctx):
            return await ctx.send(
                embed=discord.Embed(title=lang_["errors"]["types"]["permission"],
                                    description=lang["dj"],
                                    color=config.COLORS['error']), delete_after=10)

        if not 0 < vol < 151:
            return await ctx.send(lang_["music"]["volume"]["errors"]["input"])

        await player.set_volume(vol)
        await player.invoke_controller()
        await ctx.send(lang_["music"]["volume"]["success"].format(vol=vol), delete_after=7)

    @commands.command(
        name="перемешать",
        aliases=["shuffle", "mix"],
        usage="перемешать",
        description="Перемешать очередь музыки")
    async def _shuffle(self, ctx: commands.Context):
        """Перемешайте очередь игроков."""
        player: Player = self.bot.wavelink.get_player(guild_id=ctx.guild.id, cls=Player, context=ctx)
        lang_ = await TR.lang(ctx.guild)
        lang = lang_["music"]["errors"]

        if not player.is_connected:
            return await ctx.send(embed=discord.Embed(title=lang_["errors"]["types"]["voice"],
                                                      description=lang["voice"]["bot"],
                                                      color=config.COLORS["error"]), delete_after=15)

        if player.is_playing:
            if getattr(ctx.author, 'voice'):
                if str(ctx.author.voice.channel.id) != str(player.channel_id):
                    return await ctx.send(embed=discord.Embed(title=lang_["errors"]["types"]["voice"],
                                                              description=lang["voice"]["user_bot"],
                                                              color=config.COLORS["error"]), delete_after=15)
            else:
                return await ctx.send(embed=discord.Embed(title=lang_["errors"]["types"]["voice"],
                                                          description=lang["voice"]["user_bot"],
                                                          color=config.COLORS["error"]), delete_after=15)

        if player.queue.qsize() < 3:
            return await ctx.send(lang_["music"]["shuffle"]["error"], delete_after=15)

        if await self.is_privileged(ctx):
            await ctx.send(lang_["music"]["volume"]["success"], delete_after=10)
            player.shuffle_votes.clear()
            return random.shuffle(player.queue._queue)

        required = self.required(ctx)
        player.shuffle_votes.add(ctx.author)
        votes = len(player.stop_votes)

        if votes >= required:
            await ctx.send(lang_["music"]["shuffle"]["vote"]["success"].format(votes=votes, required=required), delete_after=10)
            player.shuffle_votes.clear()
            random.shuffle(player.queue._queue)
        else:
            await ctx.send(lang_["music"]["shuffle"]["vote"]["voted"].format(votes=votes, required=required, author=ctx.author), delete_after=10)

    @commands.command(hidden=True)
    async def vol_up(self, ctx: commands.Context):
        """Команда, используемая для кнопки увеличения громкости."""
        player: Player = self.bot.wavelink.get_player(guild_id=ctx.guild.id, cls=Player, context=ctx)
        lang_ = await TR.lang(ctx.guild)

        if player.is_playing:
            if getattr(ctx.author, 'voice'):
                if str(ctx.author.voice.channel.id) != str(player.channel_id):
                    return
            else:
                return

        if not player.is_connected or not await self.is_privileged(ctx):
            return

        vol = int(math.ceil((player.volume + 10) / 10)) * 10

        if vol > 150:
            vol = 150
            await ctx.send(lang_["music"]["volume"]["errors"]["max"], delete_after=7)

        await player.set_volume(vol)
        await player.invoke_controller()

    @commands.command(hidden=True)
    async def vol_down(self, ctx: commands.Context):
        """Функция, используемая для кнопки уменьшения громкости."""
        player: Player = self.bot.wavelink.get_player(guild_id=ctx.guild.id, cls=Player, context=ctx)
        lang = await TR.lang(ctx.guild)

        if not player.is_connected or not await self.is_privileged(ctx):
            return

        if player.is_playing:
            if getattr(ctx.author, 'voice'):
                if str(ctx.author.voice.channel.id) != str(player.channel_id):
                    return
            else:
                return

        vol = int(math.ceil((player.volume - 10) / 10)) * 10

        if vol < 0:
            vol = 0
            await ctx.send(lang["music"]["volume"]["errors"]["min"], delete_after=10)

        await player.set_volume(vol)
        await player.invoke_controller()

    @commands.command(
        name="эквалайзер",
        aliases=["equalizer", "eq"],
        usage="эквалайзер [Режим]",
        description="Изменить режим эквалайзера")
    async def _equalizer(self, ctx: commands.Context, *, equalizer: str):
        """Смена эквалайзера плеера."""
        player: Player = self.bot.wavelink.get_player(guild_id=ctx.guild.id, cls=Player, context=ctx)
        lang_ = await TR.lang(ctx.guild)
        lang = lang_["music"]["errors"]

        if not player.is_connected:
            return await ctx.send(embed=discord.Embed(title=lang_["errors"]["types"]["voice"],
                                                      description=lang["voice"]["bot"],
                                                      color=config.COLORS["error"]), delete_after=15)

        if player.is_playing:
            if getattr(ctx.author, 'voice'):
                if str(ctx.author.voice.channel.id) != str(player.channel_id):
                    return await ctx.send(embed=discord.Embed(title=lang_["errors"]["types"]["voice"],
                                                              description=lang["voice"]["user_bot"],
                                                              color=config.COLORS["error"]), delete_after=15)
            else:
                return await ctx.send(embed=discord.Embed(title=lang_["errors"]["types"]["voice"],
                                                          description=lang["voice"]["user_bot"],
                                                          color=config.COLORS["error"]), delete_after=15)

        if not await self.is_privileged(ctx):
            return await ctx.send(
                embed=discord.Embed(title=lang_["errors"]["types"]["permission"],
                                    description=lang["dj"],
                                    color=config.COLORS['error']), delete_after=10)

        eqs = {'flat': wavelink.Equalizer.flat(),
               'boost': wavelink.Equalizer.boost(),
               'metal': wavelink.Equalizer.metal(),
               'piano': wavelink.Equalizer.piano()}

        eq = eqs.get(equalizer.lower(), None)

        if not eq:
            joined = "\n".join(eqs.keys())
            return await ctx.send(lang_["music"]["equalizer"]["error"].format(joined=joined), delete_after=15)

        await ctx.send(lang_["music"]["equalizer"]["success"].format(equalizer=equalizer), delete_after=15)
        await player.set_eq(eq)
        await player.invoke_controller()

    @commands.command(
        name="очередь",
        aliases=["queue", "q"],
        usage="очередь [Количество]",
        description="Показать текущую очередь треков")
    async def _queue(self, ctx: commands.Context):
        """Отображение очереди плеера."""
        player: Player = self.bot.wavelink.get_player(guild_id=ctx.guild.id, cls=Player, context=ctx)
        lang_ = await TR.lang(ctx.guild)
        lang = lang_["music"]["errors"]

        if not player.is_connected:
            return await ctx.send(embed=discord.Embed(title=lang_["errors"]["types"]["voice"],
                                                      description=lang["voice"]["bot"],
                                                      color=config.COLORS["error"]), delete_after=15)

        if player.is_playing:
            if getattr(ctx.author, 'voice'):
                if str(ctx.author.voice.channel.id) != str(player.channel_id):
                    return await ctx.send(embed=discord.Embed(title=lang_["errors"]["types"]["voice"],
                                                              description=lang["voice"]["user_bot"],
                                                              color=config.COLORS["error"]), delete_after=15)
            else:
                return await ctx.send(embed=discord.Embed(title=lang_["errors"]["types"]["voice"],
                                                          description=lang["voice"]["user_bot"],
                                                          color=config.COLORS["error"]), delete_after=15)

        if player.queue.qsize() == 0:
            return await ctx.send(lang_["music"]["queue"]["error"], delete_after=15)

        entries = [track.title for track in player.queue._queue]
        pages = PaginatorSource(entries=entries)
        paginator = menus.MenuPages(source=pages, timeout=None, delete_message_after=True)

        await paginator.start(ctx)

    @commands.command(
        name="статус",
        aliases=["status", "np", "nowplaying"],
        usage="статус",
        description="Показать Текущий Трек (создать новый контроллер)")
    #@commands.bot_has_permissions(add_reactions=True)
    async def _nowplaying(self, ctx: commands.Context):
        """Обновить контроллер плеера. (удалить старый создать новый)"""
        player: Player = self.bot.wavelink.get_player(guild_id=ctx.guild.id, cls=Player, context=ctx)
        lang_ = await TR.lang(ctx.guild)
        lang = lang_["music"]["errors"]

        if not player.is_connected:
            return await ctx.send(embed=discord.Embed(title=lang_["errors"]["types"]["voice"],
                                                      description=lang["voice"]["bot"],
                                                      color=config.COLORS["error"]), delete_after=15)

        if player.is_playing:
            if getattr(ctx.author, 'voice'):
                if str(ctx.author.voice.channel.id) != str(player.channel_id):
                    return await ctx.send(embed=discord.Embed(title=lang_["errors"]["types"]["voice"],
                                                              description=lang["voice"]["user_bot"],
                                                              color=config.COLORS["error"]), delete_after=15)
            else:
                return await ctx.send(embed=discord.Embed(title=lang_["errors"]["types"]["voice"],
                                                          description=lang["voice"]["user_bot"],
                                                          color=config.COLORS["error"]), delete_after=15)

        await player.invoke_controller()


    """    @commands.command(aliases=['swap'])
    async def swap_dj(self, ctx: commands.Context, *, member: discord.Member = None):
        \"\"\"Поменять текущего ди-джея на другого участника в голосовом канале.\"\"\"
        player: Player = self.bot.wavelink.get_player(guild_id=ctx.guild.id, cls=Player, context=ctx)

        if not player.is_connected:
            return await ctx.send(embed=discord.Embed(title='Как бот может что-то сделать если он не подключен?',
                                                      description='Бот не подключен к голосовому каналу',
                                                      color=config.COLORS["error"]), delete_after=15)

        if not await self.is_privileged(ctx):
            return await ctx.send(
                embed=discord.Embed(title=lang_["errors"]["types"]["permission"],
                                    description=lang["dj"],
                                    color=config.COLORS['error']), delete_after=10)

        members = self.bot.get_channel(int(player.channel_id)).members

        if member and member not in members:
            return await ctx.send(f'{member} в настоящее время не находиться в голосовом канале, поэтому он не может быть ди-джеем.', delete_after=15)

        if member and member == player.dj:
            return await ctx.send('Невозможно поменять DJ на текущего DJ... Хотя я могу забрать себе роль DJ если ты так хочешь :>', delete_after=15)

        if len(members) <= 2:
            return await ctx.send('No more members to swap to.', delete_after=15)

        if member:
            player.dj = member
            return await ctx.send(f'{member.mention} is now the DJ.')

        for m in members:
            if m == player.dj or m.bot:
                continue
            else:
                player.dj = m
                return await ctx.send(f'{member.mention} is now the DJ.')"""


def setup(bot: commands.Bot):
    bot.add_cog(Music(bot))
