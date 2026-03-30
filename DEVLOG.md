# Avrae Local D&D Engine — Development Log

## Project Goal
Train Reinforcement Learning agents on D&D 5e combat locally, without Discord.

---

## How Avrae Works (Important Context)

Avrae is a **rule executor**, not a player. It makes **zero decisions**.

On Discord, **humans** type every command:
- **DM (human)** controls all monsters — decides who they attack, when they use abilities
- **Players (humans)** each control their own character — decide what to do on their turn
- **Avrae (bot)** only rolls dice, tracks HP, applies damage/effects

```
DM types:      !a Bite -t Fighter     → bot rolls dice, applies damage
Player types:  !cast Fireball -t Troll → bot rolls saves, applies damage
```

The bot never chooses a target, selects a spell, or makes any tactical decision. It is a calculator.

Our local engine works identically — same calculator, just without Discord.

**Sources:**
- [DM Combat Guide — Avrae Docs](https://avrae.readthedocs.io/en/latest/cheatsheets/dm_combat.html)
- [Avrae Official Site](https://avrae.io/)
- [Avrae GitHub](https://github.com/avrae/avrae)

---

## 2026-03-18: SRD Free Content Loaded

Downloaded D&D 5e SRD data from [5e-bits/5e-database](https://github.com/5e-bits/5e-database) (Open Gaming License) and converted to avrae format.

| Data | SRD (free, what we have) | Full D&D Beyond (paid, what Discord Avrae uses) |
|------|---|---|
| Monsters | **334** (CR 0–30) | ~2,700 |
| Spells | **319** (115 with automation) | ~500 |
| Conditions | **15** | 15 |

The full ~2,700 monsters come from paid D&D Beyond books (Monster Manual, Volo's Guide, etc.) and are copyrighted. Avrae on Discord accesses them through an official partnership with D&D Beyond, checking each user's purchase entitlements. We cannot use that content offline.

The SRD (System Reference Document) is the free subset released by Wizards of the Coast under the Open Gaming License. It covers the core rules and is sufficient for RL training.

324 of 334 monsters have named attacks with automation (e.g. Troll: Bite/Claw, Dragon: Bite/Claw/Tail).

---

## 2026-03-18: Engine Setup

Cloned [avrae/avrae](https://github.com/avrae/avrae) and made it run without Discord.

**Key file:** `mock_disnake.py` — injects a fake Discord module so all real avrae code imports and runs locally. No engine rewriting needed.

```
mock_disnake.py  →  fakes Discord dependency
local_server.py  →  Flask API using real avrae classes
dnd_cli.py       →  CLI with same commands as Discord (!init, !a, !cast, etc.)
```

Server runs as systemd service on `0.0.0.0:5000`, accessible from any machine on LAN.

---

## Concurrency & Storage

**Sessions are fully in-memory.** No database is used at runtime. MongoDB and Redis are installed but not needed — the engine uses Python dicts only. Sessions disappear on delete or server restart. SRD compendium data (monsters/spells) is read-only from disk at startup.

**Benchmarked at 50 concurrent sessions:**

| Metric | Result |
|--------|--------|
| Session creation | 6ms each |
| 50 simultaneous attacks | All succeeded, 1ms each |
| Sequential throughput | 611 requests/second |
| Memory per session | ~few KB |

At 611 req/s with ~5 API calls per training step, this supports ~120 training steps/second across 50 sessions. Could likely handle hundreds of sessions — limit is RAM, not CPU.

---

## File Index

| File | Purpose |
|------|---------|
| `mock_disnake.py` | Fakes Discord so real avrae code runs locally |
| `local_server.py` | REST API wrapping real avrae engine |
| `dnd_cli.py` | CLI client — same commands as Discord Avrae |
| `srd_data/compendium/` | 334 monsters, 319 spells, 15 conditions (SRD) |
| `srd_data/convert_srd.py` | Converts raw SRD JSON → avrae format |
| `DEMO.md` | 1-minute demo script |

## Quick Reference

```bash
# Start server
sudo systemctl start avrae-engine

# Connect CLI
python dnd_cli.py --server http://192.168.96.131:5000

# From Windows
pip install requests
python dnd_cli.py --server http://<VM_IP>:5000
```
