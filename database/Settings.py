import aiomysql
from database.Base import Base


class Create(Base):
    def __init__(self, one_used: bool = None):
        super().__init__(one_used=one_used)

    async def prefix(self, guild, prefix):
        await self.input("INSERT INTO `guilds_settings_prefix` (`guild`, `prefix`) VALUES (%s, %s)", (guild.id, prefix))

    async def language(self, guild, language: str):
        await self.input("INSERT INTO `guilds_settings_language` (`guild`, `language`) VALUES (%s, %s)", (guild.id, language))

    async def music(self, guild, maxqueuelength=None, maxsonglength=None, djrole=None):
        await self.input("INSERT INTO `guilds_settings_music` (`guild`, `maxqueuelength`, `maxsonglength`, `djrole`) VALUES (%s, %s, %s, %s)",
                         (guild.id, maxqueuelength, maxsonglength, djrole))


class Delete(Base):
    def __init__(self, one_used: bool = None):
        super().__init__(one_used=one_used)

    async def prefix(self, guild):
        await self.input("DELETE FROM `guilds_settings_prefix` WHERE `guild`=%s", guild.id)

    async def language(self, guild):
        await self.input("DELETE FROM `guilds_settings_language` WHERE `guild`=%s", guild.id)

    async def music(self, guild):
        await self.input("DELETE FROM `guilds_settings_music` WHERE `guild`=%s", guild.id)


class Update(Base):
    def __init__(self, one_used: bool = None):
        super().__init__(one_used=one_used)

    async def prefix(self, guild, prefix):
        await self.input("UPDATE `guilds_settings_prefix` SET `prefix`=%s WHERE `guild`=%s", (prefix, guild.id))

    async def language(self, guild, language: str):
        await self.input("UPDATE `guilds_settings_language` SET `language`=%s WHERE `guild`=%s", (language, guild.id))

    async def music(self, guild, maxqueuelength=None, maxsonglength=None, djrole=None):
        if maxqueuelength is not None:
            await self.input("UPDATE `guilds_settings_music` SET `maxqueuelength`=%s WHERE `guild`=%s",
                             (maxqueuelength, guild.id))

        if maxsonglength is not None:
            await self.input("UPDATE `guilds_settings_music` SET `maxsonglength`=%s WHERE `guild`=%s",
                             (maxsonglength, guild.id))

        if djrole is not None:
            await self.input("UPDATE `guilds_settings_music` SET `djrole`=%s WHERE `guild`=%s",
                             (djrole, guild.id))
        else:
            if djrole == "null":
                await self.input("UPDATE `guilds_settings_music` SET `djrole`=%s WHERE `guild`=%s",
                                 (None, guild.id))


class Select(Base):
    def __init__(self, one_used: bool = None):
        super().__init__(one_used=one_used)

    async def prefix(self, guild):
        result = await self.output_one("SELECT * FROM `guilds_settings_prefix` WHERE `guild`=%s", guild.id)
        return result

    async def language(self, guild):
        result = await self.output_one("SELECT * FROM `guilds_settings_language` WHERE `guild`=%s", guild.id)
        return result

    async def music(self, guild):
        result = await self.output_one("SELECT * FROM `guilds_settings_music` WHERE `guild`=%s", guild.id)
        return result
