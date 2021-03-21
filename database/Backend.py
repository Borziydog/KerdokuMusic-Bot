import aiomysql
import json
import config
from database.Base import Base


class Create(Base):
    def __init__(self, one_used: bool = None):
        super().__init__(one_used=one_used)

    async def status(self, client):
        user = client.user

        pings_list = []
        for shard in client.shards:
            pings_list.append({f"shard": f"{shard}", "ping": f"{client.get_shard(shard).latency * 1000:.0f}"})
        pings = {'pings': pings_list}
        pings = json.dumps(pings)

        members_count = 0
        guild_count = 0
        for guild in client.guilds:
            guild_count += 1
            members_count += len([m for m in guild.members if not m.bot])

        await self.input(
            "INSERT INTO `backend_bot_status` (`pings`, `shards`, `guilds`, `members`, `version`, `cluster`, `owners`, `project`, `name`, `discriminator`, `id`) "
            "VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)",
            (pings, client.shard_count, guild_count, members_count, config.VERSION, config.CLUSTER["name"], json.dumps({"owners": config.OWNERS}), config.PROJECT, user.name,
             user.discriminator, user.id))

    async def wavelink(self, node, players):
        players = json.dumps(players)
        await self.input(
            "INSERT INTO `backend_wavelink_status` (`available`, `region`, `identifier`, `penalty`, `players`) VALUES (%s, %s, %s, %s, %s)",
            (node.is_available, node.region, node.identifier, node.penalty, players))


class Delete(Base):
    def __init__(self, one_used: bool = None):
        super().__init__(one_used=one_used)

    async def status(self, bot):
        await self.input("DELETE FROM `backend_bot_status` WHERE `id`=%s", bot.id)

    async def wavelink(self, node):
        await self.input("DELETE FROM `backend_wavelink_status` WHERE `identifier`=%s", node.identifier)


class Update(Base):
    def __init__(self, one_used: bool = None):
        super().__init__(one_used=one_used)

    async def status(self, client):
        user = client.user

        pings_list = []
        for shard in client.shards:
            pings_list.append({f"shard": f"{shard}", "ping": f"{client.get_shard(shard).latency * 1000:.0f}"})
        pings = {'pings': pings_list}
        pings = json.dumps(pings)

        members_count = 0
        guild_count = 0
        for guild in client.guilds:
            guild_count += 1
            members_count += len([m for m in guild.members if not m.bot])

        await self.input(
            "UPDATE `backend_bot_status` SET `pings`=%s, `shards`=%s, `guilds`=%s, `members`=%s, `version`=%s, `cluster`=%s, `owners`=%s, `project`=%s, `name`=%s, `discriminator`=%s WHERE `id`=%s",
            (pings, client.shard_count, guild_count, members_count, config.VERSION, config.HOST["name"], json.dumps({"owners": config.OWNERS}), config.PROJECT, user.name,
             user.discriminator, user.id))

    async def wavelink(self, node, players):
        players = json.dumps(players)
        await self.input(
            "UPDATE `backend_wavelink_status` SET `available`=%s, `region`=%s, `penalty`=%s, `players`=%s WHERE `identifier`=%s",
            (node.is_available, node.region, node.penalty, players, node.identifier))


class Select(Base):
    def __init__(self, one_used: bool = None):
        super().__init__(one_used=one_used)

    async def status(self, client):
        result = await self.output_one("SELECT * FROM `backend_bot_status` WHERE `id`=%s", client.user.id)
        return result

    async def wavelink(self, identifier=None):
        if identifier is None:
            result = await self.output_all("SELECT * FROM `backend_wavelink_status`")
            return result
        else:
            result = await self.output_one("SELECT * FROM `backend_wavelink_status` WHERE `identifier`=%s", identifier)
            return result
