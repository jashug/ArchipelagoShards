A way to hack in support for sharding huge archipelago multiworlds.

Rather than one server that everyone has to connect to, this
repository supports running multiple servers, and every player only connects to one server.
This should allow for increased scale and load-balancing.

The basic idea is that we take the `.archipelago` file, and split the slots up into shards.
We also add a proxy game to each shard that contains a location for every items that is supposed to come from another shard,
and an item for each location that has an item that needs to be sent to another shard.

Then we have one proxy client that connects to all of the servers (but only one connection to each, not one per player),
and plays the proxy games by relaying checks.

# Installation

Once I have something working, I will release an `.apworld` that can be installed and used more easily.

## Development Setup

Put this repository as a folder named `shards` in `C:\ProgramData\Archipelago\lib\worlds` (Or wherever your Archipelago data is already installed).
I'm currently running from the command line (on Windows) with `\ProgramData\Archipelago\ArchipelagoLauncherDebug.exe "Generate Shards" --`,
and I set up settings in my `host.yaml`:
```yaml
shards_options:
  loglevel: "debug"
  number_of_shards: 3
  multidata: "C:\\ProgramData\\Archipelago\\output\\AP_26392360222573641375.zip"
```
You will need to change the `multidata` setting to a generated archipelago you want to test with.
These settings can also be given on the command line, run the program with `--help` to see details.

I know I should set up type checking, but I'm not sure how to get types for the `Archipelago` libraries that
this is being used as a plugin with.

# Notes

Inspired by the failure of the first Cjya community archipelago where 1200 sync players were too much for the server.
That was hosted on `archipelago.gg`, beefier hardware on a dedicated server might or might not be able to handle
1200 players, but there will eventually be a limit to what one server can handle.

(Sidenote: I don't have access to performance metrics to really guess what the limiting factor was,
but broadcasting TextJSON messages to all players on connect and chat smells particularly fishy.
That's a *lot* of work for not much benefit when the number of players is this large.
A switch in MultiServer to turn off most/all indiscriminate broadcasting might be both easy and useful
for these mega-sized games)

This proxy strategy is a hack that roughly doubles the total bandwidth and time needed
(because most checks have to be processed twice, once on the sending shard and once on the receiving shard), but is very parallel,
so 4 shards should roughly half each server's workload, and 10 shards should cut it by roughly 5.

A more principled approach would be to both improve single server performance
and handle sharding in the server natively by having the servers talk directly to each other
using a custom interface. That is a bigger project than I wanted to take on immediately and alone.
This approach doesn't need to change the archipelago server at all, which is very nice for hacking something together quickly.

---

Current status:
- Strategy sketched out (see `notes.txt`)
- Started work on the program to split an `.archipelago` file
- Proxy client not yet started
  - Proxy client hint forwarding (get basic check forwarding working first)
