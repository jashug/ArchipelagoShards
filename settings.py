import typing

import settings

class ShardsSettings(settings.Group):
    number_of_shards: int = 4
    multidata: str | None = None
    loglevel: str = "info"
