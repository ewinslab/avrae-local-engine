# 1-Minute Demo: Local D&D Engine

## Pre-demo Setup (do before audience arrives)
```bash
# On the VM (Ubuntu) — ensure server is running
sudo systemctl start avrae-engine
```

---

## DEMO SCRIPT (60 seconds)

### [0:00] Start — Open Windows Terminal

> "This is a D&D combat engine running entirely on our local network — no Discord, no internet."

```
python dnd_cli.py --server http://192.168.96.131:5000
```

Output shows:
```
Connected to Avrae D&D Engine (Real) v3.0.0
```

---

### [0:10] Show the data

> "We have 334 monsters and 319 spells from the SRD loaded."

```
!monster Troll
```

Output shows Troll stats: HP 84, AC 15, regeneration trait, Bite/Claw attacks.

---

### [0:15] Start combat

> "Let's fight. A level 5 party versus a Troll."

```
!init begin -name Troll Hunt
!init add 3 Fighter -hp 52 -ac 18
!init madd Troll
!init next
```

Output shows initiative order and whose turn it is.

---

### [0:25] Attack with named attacks

> "The Troll attacks using its actual stat block — Bite and Claw from the Monster Manual."

```
!a Bite -t Fighter
```

Output shows real attack roll, damage with type, HP change.

---

### [0:30] Fighter's turn — attack back

```
!init next
!a -t Troll -b 7 -d 1d8+4 -dtype slashing
```

Output shows attack roll vs AC 15, damage dealt, Troll HP drops.

---

### [0:35] Cast a spell

> "We can cast spells with full automation — attack rolls, damage, scaling."

```
!cast Fire Bolt -t Troll
```

Output shows the spell automation running through the real avrae engine.

---

### [0:40] Add an effect

> "Buffs and debuffs work — this adds +2 AC, tracked across rounds."

```
!init effect Fighter Shield -dur 5 -ac +2
!init status Fighter
```

Output shows Fighter with AC 20, Shield effect with 5 rounds duration.

---

### [0:48] Check combat state

> "Full initiative tracker, just like Discord."

```
!init list
```

Output shows:
```
Troll Hunt: Round 1
====================
  16: Troll <Injured>
#  8: Fighter <45/52 HP> (AC 20, Shield [5 rounds])
```

---

### [0:53] End

> "334 monsters, 319 spells, full D&D 5e rules — running locally for RL training."

```
!init end
!quit
```

---

## Quick Copy-Paste Version (all commands)

```
python dnd_cli.py --server http://192.168.96.131:5000
!monster Troll
!init begin -name Troll Hunt
!init add 3 Fighter -hp 52 -ac 18
!init madd Troll
!init next
!a Bite -t Fighter
!init next
!a -t Troll -b 7 -d 1d8+4 -dtype slashing
!cast Fire Bolt -t Troll
!init effect Fighter Shield -dur 5 -ac +2
!init status Fighter
!init list
!init end
!quit
```

## Windows Setup (one-time)

```cmd
pip install requests
curl -O http://192.168.96.131:5000/static/dnd_cli.py
python dnd_cli.py --server http://192.168.96.131:5000
```

Or just copy `dnd_cli.py` to any machine via USB/network share.
