# Avrae Local Engine

Run the [Avrae](https://github.com/avrae/avrae) D&D 5e game engine locally without Discord.

## What This Is

[Avrae](https://avrae.io/) is an open-source D&D 5e Discord bot. It handles dice, combat, spells, and character tracking, but requires Discord to run. This project makes it run as a local REST API instead, by replacing the Discord dependency with a lightweight mock layer (`mock_disnake.py`). The game engine code is unchanged.

All game data included is from the [D&D 5e SRD](https://dnd.wizards.com/resources/systems-reference-document) (free, Open Gaming License). No paid or copyrighted content is included.

## Setup

Follow the [original Avrae setup instructions](https://github.com/avrae/avrae#running-avrae-locally) to install Python 3.10+ and dependencies, then:

```bash
pip install flask flask-cors
```

The only difference from the original setup: **you do not need a Discord bot token, MongoDB, or Redis.** Everything runs in-memory.

## Minimum Example

**Start the server:**
```bash
python local_server.py
```

**Open another terminal and connect the CLI:**
```bash
python dnd_cli.py --server http://localhost:5000
```

**Play a combat:**
```
!init begin -name Quick Fight
!init add 3 Fighter -hp 52 -ac 18
!init madd Troll
!init next
!a Bite -t Fighter
!init next
!a -t Troll -b 7 -d 1d8+4 -dtype slashing
!init list
!init end
```

Commands are the same as [Discord Avrae](https://avrae.readthedocs.io/en/latest/cheatsheets/dm_combat.html). Type `!help` for the full list.

## Game Data

The included SRD data (334 monsters, 319 spells) is free content from Wizards of the Coast under the [Open Gaming License](https://dnd.wizards.com/resources/systems-reference-document). It was sourced from [5e-bits/5e-database](https://github.com/5e-bits/5e-database) and converted to Avrae's format using `srd_data/convert_srd.py`.

## How It Works

`mock_disnake.py` provides a local stand-in for the Discord module via `sys.modules`, allowing the real engine code (`cogs5e/`, `gamedata/`, `aliasing/`) to import and run without modification. `local_server.py` wraps it as a REST API. `dnd_cli.py` is a CLI client.

## Credits

- [avrae/avrae](https://github.com/avrae/avrae) - Original engine
- [5e-bits/5e-database](https://github.com/5e-bits/5e-database) - SRD data
- [D&D 5e SRD](https://dnd.wizards.com/resources/systems-reference-document) - Game content (OGL)
