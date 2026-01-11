import argparse
from collections.abc import Sequence
import logging
import pprint
import zlib

import colorama

import NetUtils
import Utils
from Utils import restricted_loads
from NetUtils import MultiData

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
    if format_version != 3:
        raise Utils.VersionException("Incompatible multidata.")

    data = restricted_loads(zlib.decompress(data_bytes[1:]))
    # logging.debug(pprint.pformat(data, width=160))
    return data

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

