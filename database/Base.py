import config
import aiomysql


def connect(func):
    async def wrapped(*args, **kwargs):
        self = args[0]
        self = await self.conn_db()

        result = await func(*args, **kwargs)
        if self is not None:
            if self.one_used:
                self.conn.close()

        return result

    return wrapped


class Base:
    def __init__(self, one_used: bool = False):
        self.conn = None
        if not one_used:
            self.one_used = False
        else:
            self.one_used = True

    async def close(self):
        self.conn.close()
        return None

    async def conn_db(self):
        if self.conn is None:
            data = config.DATABASE
            self.conn = await aiomysql.connect(host=data['host'], port=data['port'],
                                               user=data['login'], password=data['password'],
                                               db=data['dbname'], autocommit=True)
            return self

    @connect
    async def input(self, sql, args):
        async with self.conn.cursor(aiomysql.DictCursor) as cursor:
            await cursor.execute(sql, args)

    @connect
    async def output_one(self, sql, args=None):
        async with self.conn.cursor(aiomysql.DictCursor) as cursor:
            if args is not None:
                await cursor.execute(sql, args)
            else:
                await cursor.execute(sql)
            result = await cursor.fetchone()

        return result

    @connect
    async def output_all(self, sql, args=None):
        async with self.conn.cursor(aiomysql.DictCursor) as cursor:
            if args is not None:
                await cursor.execute(sql, args)
            else:
                await cursor.execute(sql)
                result = await cursor.fetchall()

        return result