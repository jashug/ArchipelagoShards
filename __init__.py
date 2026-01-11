from worlds.AutoWorld import World

import typing

from . import components as components
from .settings import ShardsSettings

# We create a dummy world in order to be able to use the settings system
# Based off of what Universal Tracker does
# TODO: can we give more meta-data (like item_name_to_id) based on
#   the generated shards, and is that used anywhere?
#   We will have a game "proxy", how accuratly can we plug that in to the system?
class ShardsWorld(World):
    settings: typing.ClassVar[ShardsSettings]
    settings_key = "shards_options"

    game = "Shard Proxy"
    hidden = True
    item_name_to_id = {}
    location_name_to_id = {}
