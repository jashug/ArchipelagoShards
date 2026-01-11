from worlds.LauncherComponents import Component, Type, components, launch

def generate_shards(*args: str) -> None:
    from .generate import main as generate_main
    launch(generate_main, "Shard Generator", args=args)

components.append(
    Component(
        "Generate Shards",
        func=generate_shards,
        component_type=Type.MISC,
        cli=True,
        description="Split a .archipelago file into multiple shards that can be hosted separately.",
    )
)
