import argparse
from collections.abc import Sequence
import logging
import pprint
import zlib

import colorama

import NetUtils
import Utils
from Utils import output_path, restricted_dumps, restricted_loads
from NetUtils import MultiData

ARCHIPELAGO_DATA_VERSION = 3

def load(multidata_filename: str) -> MultiData:
    # Based off of MultiServer.Context.load
    if multidata_filename.lower().endswith(".zip"):
        import zipfile
        with zipfile.ZipFile(multidata_filename) as zf:
            for file in zf.namelist():
                if file.endswith(".archipelago"):
                    data_bytes = zf.read(file)
                    break
            else:
                raise Exception("No .archipelago found in archive.")
    else:
        with open(multidata_filename, 'rb') as f:
            data_bytes = f.read()

    format_version = data_bytes[0]
    if format_version != ARCHIPELAGO_DATA_VERSION:
        raise Utils.VersionException("Incompatible multidata.")

    data = restricted_loads(zlib.decompress(data_bytes[1:]))
    # logging.debug(pprint.pformat(data, width=160))
    return data

def write_shard(data: MultiData, shard_index: int):
    seed = data["seed_name"]
    data_bytes = zlib.compress(restricted_dumps(data), 9)
    filename = f"AP_{seed}_Shard{shard_index:02}.archipelago"
    with open(output_path(filename), "wb") as f:
        f.write(bytes([ARCHIPELAGO_DATA_VERSION]))
        f.write(data_bytes)
    logging.info(f"Finished writing {filename}.")

PROXY_SLOT = 1

def split_multidata(data: MultiData, num_shards: int) -> list[MultiData]:
    # Shards will be numbered 0 - (num_shards - 1)
    slot_ids = sorted(data["slot_info"].keys())
    assert slot_ids
    assert slot_ids == list(range(1, slot_ids[-1] + 1))
    assert len(slot_ids) == slot_ids[-1]
    num_slots = len(slot_ids)
    logging.debug(f"Slots are correctly numbered 1 - {num_slots}")

    # We will give the proxy slot 1 in each shard.
    # Distribute slots round-robin among shards
    # Round-robin is nice because it is deterministic, simple, and should
    # break up clumps.
    def map_slot(slot: int) -> (int, int):
        """Returns (shard, slot)"""
        base_slot, shard = divmod(slot - 1, num_shards)
        return (shard, base_slot + 2)

    # Our item and location ids will be chosen cleverly.
    # Must be integers > 0 for Archipelago protocol.
    # For the i-th (0-indexed) item in shard r which is found in a location in a different shard,
    # we create a location (i * num_shards + r + 1) in the proxy for shard r and an item with the same id
    # in the other shard.
    shard_counters = [0 for i in range(num_shards)]
    # map from (slot, id) to (slot, proxy id). If the item/location and it's pair are both in the
    # same shard, this is the identity map.
    # translate_items[(x, y)] gives the proxy item in the shard where item (x, y) is found.
    translate_items: dict[(int, int), (int, int)] = {}
    # translate_locations[(x, y)] gives the proxy location in the shard that location (x, y) sends to.
    translate_locations: dict[(int, int), (int, int)] = {}

    # TODO: I can't follow the translation logic on this little sleep.
    # Figure out what works consistently. Maybe work backwards, try the generation and see what you need.
    for location_slot, slot_locations in data["locations"].items():
        for location_id, (item_id, item_slot, _item_flags) in slot_locations.items():
            assert (location_slot, location_id) not in translate_locations
            assert (item_slot, item_id) not in translate_items
            location_shard, location_new_slot = map_slot(location_slot)
            item_shard, item_new_slot = map_slot(item_slot)
            if location_shard == item_shard:
                translate_items[(item_slot, item_id)] = (item_slot, item_id)
                translate_locations[(location_slot, location_id)] = (location_slot, location_id)
            else:
                new_id = shard_counters[item_shard] * num_shards + item_shard + 1
                shard_counters[item_shard] += 1
                translate_items[(item_slot, item_id)] = (PROXY_SLOT, new_id)
                translate_locations[(location_slot, location_id)] = (PROXY_SLOT, new_id)

def get_multidata_filename(data_filename: str | None=None):
    # Mimic MultiServer for opening the .archipelago file

    if data_filename:
        return data_filename

    try:
        filetypes = (("Multiworld data", (".archipelago", ".zip")),)
        data_filename = Utils.open_filename("Select multiworld data", filetypes)

    # I don't understand this except block: it is copied from MultiServer.py
    # TODO: I don't think we are going to be frozen, so can probably use builtin exit?
    #       Talk to people who wrote the original.
    except Exception as e:
        if isinstance(e, ImportError) or (e.__class__.__name__ == "TclError" and "no display" in str(e)):
            if not isinstance(e, ImportError):
                logging.error(f"Failed to load tkinter ({e})")
            logging.info("Pass a multidata filename on command line to run headless.")
            # when cx_Freeze'd the built-in exit is not available, so we import sys.exit instead
            import sys
            sys.exit(1)
        raise

    return data_filename

def main(*argv: Sequence[str]):
    colorama.just_fix_windows_console()

    from settings import get_settings

    defaults = get_settings().shards_options.as_dict()

    parser = argparse.ArgumentParser()
    parser.add_argument("multidata", nargs="?", default=defaults["multidata"])
    parser.add_argument("--num-shards", type=int, default=defaults["number_of_shards"])
    parser.add_argument("--loglevel", default=defaults["loglevel"],
                        choices=['debug', 'info', 'warning', 'error', 'critical'])

    args = parser.parse_args(argv)

    Utils.init_logging(name="Sharder",
                       loglevel=args.loglevel.lower())

    logging.debug(f"Given args: {argv}")

    data_filename = get_multidata_filename(args.multidata)

    if not data_filename:
        logging.info("No file selected. Exiting.")
        import sys
        sys.exit(1)

    logging.info(f"Opening {data_filename}")

    data: MultiData = load(data_filename)

    logging.info(f"Generating {args.num_shards} shards...")

