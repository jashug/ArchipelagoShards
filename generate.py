import argparse
from collections.abc import Sequence
import logging
import pprint
import zlib

import colorama

import NetUtils
import Utils
from Utils import output_path, restricted_dumps, restricted_loads
from NetUtils import Hint, MultiData, NetworkSlot, SlotType

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
ONLY_TEAM = 0

def split_multidata(data: MultiData, num_shards: int, proxy_slot_name: str) -> list[MultiData]:
    assert num_shards > 0
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
    def map_slot(slot: int) -> tuple[int, int]:
        """Returns (shard, slot)"""
        base_slot, shard = divmod(slot - 1, num_shards)
        return (shard, base_slot + 2)

    # shard_slots[shard_ix][input_slot] = shard_local_slot
    shard_slots: list[dict[int, int]] = [{} for slot in range(1, num_slots + 1)]
    for slot in range(1, num_slots + 1):
        (shard, new_slot) = map_slot(slot)
        shard_slots[shard][slot] = new_slot
    # We use both map_slot and shard_slots: they need to be consistent

    # Our item and location ids will be chosen cleverly.
    # Must be integers > 0 for Archipelago protocol.
    # For the i-th (1-indexed) item in shard r which is found in a location in shard s,
    # we create an id (i * num_shards ** 2 + s * num_shards + r) in the proxy games for shards r and s
    base = num_shards ** 2
    shard_counters = [1 for i in range(base)]
    # map from shard# to input (slot, id) to output (slot, id).
    # When generating multidata for the given shard, replace all instances of the input
    # item/location with the mapped value.
    translate_items: dict[int, dict[tuple[int, int], tuple[int, int]]] = {}
    translate_locations: dict[int, dict[tuple[int, int], tuple[int, int]]] = {}

    # sharded_locations[shard][slot][location_id] = (item_id, item_slot, item_flags)
    sharded_locations: list[dict[int, dict[int, (int, int, int)]]] = \
                       [{PROXY_SLOT: {}} for shard_ix in range(num_shards)]    

    for location_slot, slot_locations in data["locations"].items():
        location_shard, location_new_slot = map_slot(location_slot)
        assert location_new_slot not in sharded_locations[location_shard]
        sharded_locations[location_shard][location_new_slot] = {}
        for location_id, (item_id, item_slot, item_flags) in slot_locations.items():
            item_shard, item_new_slot = map_slot(item_slot)
            if location_shard == item_shard:
                both_shard = item_shard
                translate_items[both_shard][(item_slot, item_id)] = (item_new_slot, item_id)
                translate_locations[both_shard][(location_slot, location_id)] = (location_new_slot, location_id)
                sharded_locations[both_shard][location_new_slot][location_id] = (item_id, item_new_slot, item_flags)
            else:
                counter_ix = location_shard * num_shards + item_shard
                new_id = shard_counters[counter_ix] * base + counter_ix
                shard_counters[counter_ix] += 1
                translate_items[item_shard][(item_slot, item_id)] = (item_new_slot, item_id)
                translate_items[location_shard][(item_slot, item_id)] = (PROXY_SLOT, new_id)
                translate_locations[item_shard][(location_slot, location_id)] = (PROXY_SLOT, new_id)
                translate_locations[location_shard][(location_slot, location_id)] = (location_new_slot, location_id)
                sharded_locations[item_shard][PROXY_SLOT][new_id] = (item_id, item_new_slot, item_flags)
                sharded_locations[location_shard][location_new_slot][location_id] = (new_id, PROXY_SLOT, item_flags)

    sharded_slot_data = [{"num_shards": num_shards, "shard_index": shard_ix} for shard_ix in range(num_slots)]
    for slot, data in data["slot_data"].items():
        shard, new_slot = map_slot(slot)
        sharded_slot_data[shard][new_slot] = data

    sharded_slot_info = [{PROXY_SLOT: proxy_slot_info} for shard_ix in range(num_slots)]
    for slot, info in data["slot_info"].items():
        shard, new_slot = map_slot(slot)
        sharded_slot_info[shard][new_slot] = info

    # Generate shard MultiData

    proxy_slot_info = NetworkSlot(name=proxy_slot_name, game="Shard Proxy", type=SlotType.player)

    sharded_connect_names: list[dict[str, tuple[int, int]]] = \
                           [{proxy_slot_name, (ONLY_TEAM, PROXY_SLOT)} for shard_ix in range(num_shards)]
    for name, (team, slot) in data["connect_names"].items():
        assert team == ONLY_TEAM
        assert name != proxy_slot_name
        shard, new_slot = map_slot(slot)
        sharded_connect_names[shard][name] = (team, new_slot)

    # ignore checks_in_area[PROXY_SLOT] for the moment, TODO: should be possible
    sharded_checks_in_area = [{}]
    for slot, areas in data["checks_in_area"].items():
        shard, new_slot = map_slot(slot)
        sharded_checks_in_area[shard][new_slot] = areas

    if data["server_options"]["port"] is not None:
        logging.warning("Port is included in multidata: must override when hosting")

    if data["server_options"]["savefile"] is not None:
        logging.warning("Save file is included in multidata: danger of shards competing for one save file")

    # sharded_er_hint_data[shard][slot][location_id]
    input_er_hint_data = data["er_hint_data"]
    sharded_er_hint_data = [{PROXY_SLOT: {}} for shard_ix in range(num_shards)]
    for location_slot, slot_er_hint_data in data["er_hint_data"].items():
        location_shard, new_location_slot = map_slot(location_slot)
        for location_id, hint in slot_er_hint_data.items():
            sharded_er_hint_data[location_shard].setdefault(new_location_slot, {})[location_id] = hint
            item_id, item_slot, _item_flags = data["locations"][slot][location_id]
            item_shard, new_item_slot = map_slot(item_slot)
            if item_shard != location_shard:
                proxy_location_slot, proxy_id = translate_item[(item_slot, item_id)]
                assert proxy_location_slot == PROXY_SLOT
                sharded_er_hint_data[item_shard][PROXY_SLOT][proxy_id] = hint

    sharded_precollected_items = [{} for shard_ix in range(num_shards)]
    for slot, items in data["precollected_items"].items():
        shard, new_slot = map_slot(slot)
        sharded_precollected_items[shard][new_slot] = items

    sharded_precollected_hints = [{PROXY_SLOT: set()} for shard_ix in range(num_shards)]
    for slot, hints in data["precollected_hints"].items():
        shard, new_slot = map_slot(slot)
        new_hints = set()
        sharded_precollected_hints[shard][new_slot] = new_hints
        for hint in hints:
            receiving_shard, receiving_new_slot = map_slot(hint.receiving_player)
            finding_shard, finding_new_slot = map_slot(hint.finding_player)
            assert slot == hint.receiving_player or slot == hint.finding_player
            if receiving_shard == finding_shard:
                new_hints.add(Hint(
                    receiving_new_slot,
                    finding_new_slot,
                    hint.location,
                    hint.item,
                    hint.found,
                    hint.entrance,
                    hint.item_flags,
                    hint.status,
                ))
            else:
                # TODO: Go over this again, I feel like I made a mistake somewhere
                new_location_slot, new_location_id = translate_locations[receiving_shard][(hint.finding_player, hint.location)]
                assert new_location_slot == PROXY_SLOT 
                sharded_precollected_hints[receiving_shard][receiving_new_slot].add(Hint(
                    receiving_new_slot,
                    new_location_slot,
                    new_location_id,
                    hint.item,
                    hint.found,
                    hint.entrance,
                    hint.item_flags,
                    hint.status,
                ))
                new_item_slot, new_item_id = translate_items[finding_shard][(hint.receiving_player, hint.item)]
                assert new_item_slot == PROXY_SLOT
                sharded_precollected_hints[finding_shard][finding_new_slot].add(Hint(
                    new_item_slot,
                    finding_new_slot,
                    hint.location,
                    new_item_id,
                    hint.found,
                    hint.entrance,
                    hint.item_flags,
                    hint.status,
                ))

    def translate_sphere(shard_ix: int, sphere: dict[int, set[int]]):
        new_sphere = {}
        for slot, items in sphere.items():
            for item_id in items:
                new_slot, new_item_id = translate_item[(slot, item_id)]
                new_sphere.setdefault(new_slot, set()).add(new_item_id)
    sharded_spheres = [[translate_sphere(shard_ix, sphere) for sphere in data["spheres"]] for shard_ix in range(num_shards)]

    for shard_ix in range(num_shards):
        multidata: MultiData = {
            "slot_data": sharded_slot_data[shard_ix],
            "slot_info": sharded_slot_info[shard_ix],
            "connect_names": sharded_connect_names[shard_ix],
            "locations": sharded_locations[shard_ix],
            "checks_in_area": sharded_checks_in_area[shard_ix],
            "server_options": data["server_options"],
            "er_hint_data": sharded_er_hint_data[shard_ix],
            "precollected_items": sharded_precollected_items[shard_ix],
            "precollected_hints": sharded_precollected_hints[shard_ix],
            "version": data["version"],
            "tags": data["tags"] + ["Shards"],
            "minimum_versions": data["minimum_versions"],
            "seed_name": data["seed_name"],
            "spheres": [translate_sphere(shard_ix, sphere) for sphere in data["spheres"]],
            "datapackage": data["datapackage"],
            "race_mode": data["race_mode"], # TODO: investigate race_mode
        }
        write_shard(multidata, shard_ix)

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

