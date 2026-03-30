#!/usr/bin/env python3
"""
Avrae-compatible D&D CLI Client
================================
Cross-platform CLI that uses the SAME commands as Avrae on Discord.

Usage:
    python dnd_cli.py [--server URL]

Commands are identical to Discord Avrae:
    !init begin          Start combat
    !init add 3 Goblin   Add combatant with +3 init
    !init madd Ogre      Add monster from compendium
    !init next / !init n Advance turn
    !r 1d20+5            Roll dice
    !init attack         Attack with current combatant
    !cast Fire Bolt -t Goblin
    ... and many more. Type !help for full list.

Works on Windows, macOS, Linux — just needs Python 3 + requests.
"""

import json
import os
import re
import readline
import shlex
import sys
from urllib.parse import quote

try:
    import requests
except ImportError:
    print("Installing 'requests' library...")
    import subprocess
    subprocess.check_call([sys.executable, "-m", "pip", "install", "requests", "-q"])
    import requests


# ============================================================
# Configuration
# ============================================================

DEFAULT_SERVER = os.environ.get("DND_SERVER", "http://localhost:5000")

# ANSI colors (disabled on Windows without colorama)
try:
    if sys.platform == "win32":
        os.system("color")  # Enable ANSI on Windows 10+
    BOLD = "\033[1m"
    DIM = "\033[2m"
    RED = "\033[91m"
    GREEN = "\033[92m"
    YELLOW = "\033[93m"
    BLUE = "\033[94m"
    CYAN = "\033[96m"
    RESET = "\033[0m"
except Exception:
    BOLD = DIM = RED = GREEN = YELLOW = BLUE = CYAN = RESET = ""


# ============================================================
# HTTP Client
# ============================================================

class APIClient:
    def __init__(self, base_url):
        self.base = base_url.rstrip("/")
        self.session_id = None

    def get(self, path, **kwargs):
        try:
            r = requests.get(f"{self.base}{path}", **kwargs)
            return r.json(), r.status_code
        except requests.ConnectionError:
            return {"error": f"Cannot connect to server at {self.base}"}, 0
        except Exception as e:
            return {"error": str(e)}, 0

    def post(self, path, data=None, **kwargs):
        try:
            r = requests.post(f"{self.base}{path}", json=data or {}, **kwargs)
            return r.json(), r.status_code
        except requests.ConnectionError:
            return {"error": f"Cannot connect to server at {self.base}"}, 0
        except Exception as e:
            return {"error": str(e)}, 0

    def delete(self, path, **kwargs):
        try:
            r = requests.delete(f"{self.base}{path}", **kwargs)
            return r.json(), r.status_code
        except requests.ConnectionError:
            return {"error": f"Cannot connect to server at {self.base}"}, 0
        except Exception as e:
            return {"error": str(e)}, 0

    def patch(self, path, data=None, **kwargs):
        try:
            r = requests.patch(f"{self.base}{path}", json=data or {}, **kwargs)
            return r.json(), r.status_code
        except requests.ConnectionError:
            return {"error": f"Cannot connect to server at {self.base}"}, 0
        except Exception as e:
            return {"error": str(e)}, 0


# ============================================================
# Argument Parser (Discord-style flags)
# ============================================================

def parse_args(arg_string):
    """Parse Discord-style arguments: -flag value -flag2 value2"""
    args = {}
    positional = []
    try:
        tokens = shlex.split(arg_string)
    except ValueError:
        tokens = arg_string.split()

    i = 0
    while i < len(tokens):
        token = tokens[i]
        if token.startswith("-") and not token[1:].isdigit():
            key = token.lstrip("-")
            # Check if next token is a value or another flag
            if i + 1 < len(tokens) and not tokens[i + 1].startswith("-"):
                args[key] = tokens[i + 1]
                i += 2
            else:
                args[key] = True
                i += 1
        elif token.lower() in ("adv", "advantage"):
            args["adv"] = True
            i += 1
        elif token.lower() in ("dis", "disadvantage"):
            args["dis"] = True
            i += 1
        elif token.lower() == "conc":
            args["conc"] = True
            i += 1
        elif token.lower() == "end":
            args["end"] = True
            i += 1
        elif token.lower() == "magical":
            args["magical"] = True
            i += 1
        elif token.lower() == "silvered":
            args["silvered"] = True
            i += 1
        else:
            positional.append(token)
            i += 1
    return positional, args


# ============================================================
# Output Formatting
# ============================================================

def print_error(msg):
    print(f"{RED}Error: {msg}{RESET}")


def print_success(msg):
    print(f"{GREEN}{msg}{RESET}")


def print_info(msg):
    print(f"{CYAN}{msg}{RESET}")


def print_roll(label, roll_str, total):
    print(f"{BOLD}{label}:{RESET} {roll_str}")
    print(f"  {BOLD}Total: {total}{RESET}")


def print_combat_summary(state):
    summary = state.get("summary", "")
    # Colorize the summary
    lines = summary.split("\n")
    for line in lines:
        if line.startswith(">>"):
            print(f"{YELLOW}{BOLD}{line}{RESET}")
        elif line.startswith("="):
            print(f"{DIM}{line}{RESET}")
        elif "HP" in line and "/" in line:
            # Color HP based on ratio
            print(f"  {line.strip()}")
        else:
            print(line)


def format_hp(hp, max_hp):
    if max_hp <= 0:
        return f"{hp} HP"
    ratio = hp / max_hp
    if ratio > 0.5:
        color = GREEN
    elif ratio > 0.15:
        color = YELLOW
    else:
        color = RED
    return f"{color}{hp}/{max_hp} HP{RESET}"


# ============================================================
# Command Handlers
# ============================================================

class DnDCLI:
    def __init__(self, server_url):
        self.api = APIClient(server_url)
        self.session_id = None
        self.session_name = None
        self._current_combatant = None

    def _sid(self):
        if not self.session_id:
            print_error("No active session. Use !init begin to start combat.")
            return None
        return self.session_id

    # ---- !init begin ----
    def cmd_init_begin(self, pos, flags):
        name = flags.get("name", " ".join(pos) if pos else None)
        data, code = self.api.post("/sessions", {"name": name or "Combat"})
        if code == 201:
            self.session_id = data["id"]
            self.session_name = data["name"]
            print_success(f"Combat started: {data['name']}")
            print_info(f"Session ID: {data['id']}")
        else:
            print_error(data.get("error", "Failed to create session"))

    # ---- !init add ----
    def cmd_init_add(self, pos, flags):
        sid = self._sid()
        if not sid or len(pos) < 2:
            print_error("Usage: !init add <modifier> <name> [-hp HP] [-ac AC]")
            return

        modifier = int(pos[0])
        name = " ".join(pos[1:])
        hp = int(flags.get("hp", 0))
        ac = int(flags.get("ac", 10))

        stats = {}
        for stat in ("strength", "dexterity", "constitution", "intelligence", "wisdom", "charisma"):
            short = stat[:3]
            if short in flags:
                stats[stat] = int(flags[short])
            elif stat in flags:
                stats[stat] = int(flags[stat])

        body = {
            "name": name, "hp": hp, "ac": ac, "init_bonus": modifier,
            "stats": stats if stats else None,
            "is_private": "h" in flags,
        }

        # Optional init roll
        if "p" in flags:
            body["init_roll"] = int(flags["p"])

        # Resistances
        resistances = {"resist": [], "immune": [], "vuln": [], "neutral": []}
        for key in ("resist", "immune", "vuln", "neutral"):
            if key in flags:
                resistances[key].append({"dtype": flags[key]})
        if any(resistances.values()):
            body["resistances"] = resistances

        # Level, prof, spellcasting
        if "level" in flags:
            body["level"] = int(flags["level"])
        if "pb" in flags:
            body["prof_bonus"] = int(flags["pb"])

        data, code = self.api.post(f"/sessions/{sid}/combatants", body)
        if code == 201:
            init = data.get("init", "?")
            print_success(f"{name} was added to combat with initiative {init}.")
            if hp:
                print(f"  HP: {format_hp(hp, hp)} | AC: {ac}")
        else:
            print_error(data.get("error", "Failed"))

    # ---- !init madd ----
    def cmd_init_madd(self, pos, flags):
        sid = self._sid()
        if not sid or not pos:
            print_error("Usage: !init madd <monster_name> [-n NUMBER] [-name CUSTOM_NAME]")
            return

        monster_name = " ".join(pos)
        quantity = int(flags.get("n", 1))
        custom_name = flags.get("name")

        body = {"monster": monster_name, "quantity": quantity}
        if custom_name:
            body["name"] = custom_name

        data, code = self.api.post(f"/sessions/{sid}/monsters", body)
        if code == 201:
            for c in data:
                print_success(f"{c['name']} was added to combat with initiative {c['init']}.")
                print(f"  HP: {format_hp(c['hp'], c['max_hp'])} | AC: {c['ac']} | {c['creature_type']}")
        else:
            print_error(data.get("error", "Failed"))

    # ---- !init next / !init n ----
    def cmd_init_next(self, pos, flags):
        sid = self._sid()
        if not sid:
            return
        data, code = self.api.post(f"/sessions/{sid}/next")
        if code != 200:
            print_error(data.get("error", "Failed"))
            return

        cc = data.get("current_combatant", {})
        self._current_combatant = cc
        round_num = data["round"]

        if data.get("changed_round"):
            print(f"\n{BOLD}{'='*40}{RESET}")
            print(f"{BOLD}Round {round_num}{RESET}")
            print(f"{BOLD}{'='*40}{RESET}")

        if cc:
            print(f"\n{YELLOW}{BOLD}Initiative {cc.get('init', '?')} (round {round_num}): "
                  f"{cc['name']}{RESET}")
            print(f"  {format_hp(cc['hp'], cc['max_hp'])} | AC: {cc['ac']}")
            if cc.get("effects"):
                effs = ", ".join(e["name"] for e in cc["effects"])
                print(f"  Effects: {CYAN}{effs}{RESET}")

        # Show expired effects
        expired = data.get("expired_effects", {})
        for cname, effects in expired.items():
            for eff in effects:
                print(f"  {DIM}Effect expired: {eff} on {cname}{RESET}")

    # ---- !init prev ----
    def cmd_init_prev(self, pos, flags):
        sid = self._sid()
        if not sid:
            return
        data, code = self.api.post(f"/sessions/{sid}/prev")
        if code == 200:
            cc = data.get("current_combatant", {})
            self._current_combatant = cc
            if cc:
                print_info(f"Rewound to: {cc['name']} (Initiative {cc.get('init', '?')}, Round {data['round']})")
        else:
            print_error(data.get("error", "Failed"))

    # ---- !init list / !init summary ----
    def cmd_init_list(self, pos, flags):
        sid = self._sid()
        if not sid:
            return
        data, code = self.api.get(f"/sessions/{sid}/state")
        if code == 200:
            print_combat_summary(data)
        else:
            print_error(data.get("error", "Failed"))

    # ---- !init status ----
    def cmd_init_status(self, pos, flags):
        sid = self._sid()
        if not sid:
            return
        name = " ".join(pos) if pos else None
        if name:
            data, code = self.api.get(f"/sessions/{sid}")
            if code != 200:
                print_error(data.get("error", "Failed"))
                return
            # Find combatant by name
            for c in data.get("initiative_order", []):
                if name.lower() in c["name"].lower():
                    self._print_combatant_status(c)
                    return
            print_error(f"Combatant '{name}' not found")
        else:
            # Show current combatant
            if self._current_combatant:
                self._print_combatant_status(self._current_combatant)
            else:
                print_error("No current combatant")

    def _print_combatant_status(self, c):
        print(f"{BOLD}{c['name']}{RESET}")
        print(f"  {format_hp(c['hp'], c['max_hp'])} | AC: {c['ac']} | Init: {c.get('init', '?')}")
        if c.get("stats"):
            s = c["stats"]
            print(f"  STR {s.get('strength',10)} DEX {s.get('dexterity',10)} "
                  f"CON {s.get('constitution',10)} INT {s.get('intelligence',10)} "
                  f"WIS {s.get('wisdom',10)} CHA {s.get('charisma',10)}")
        if c.get("effects"):
            for e in c["effects"]:
                dur = f" ({e['duration']} rounds)" if e.get("duration") else ""
                conc = " [C]" if e.get("concentration") else ""
                pe = f" - {e['passive_effects']}" if e.get("passive_effects") else ""
                print(f"  {CYAN}* {e['name']}{dur}{conc}{pe}{RESET}")
        if c.get("resistances"):
            res = c["resistances"]
            if res.get("resist"):
                print(f"  Resist: {', '.join(r.get('dtype', str(r)) for r in res['resist'])}")
            if res.get("immune"):
                print(f"  Immune: {', '.join(r.get('dtype', str(r)) for r in res['immune'])}")
            if res.get("vuln"):
                print(f"  Vuln: {', '.join(r.get('dtype', str(r)) for r in res['vuln'])}")

    # ---- !init hp ----
    def cmd_init_hp(self, pos, flags):
        sid = self._sid()
        if not sid:
            return
        if not pos:
            print_error("Usage: !init hp <name> [amount] [set|max]")
            return

        # Find where name ends and amount begins
        name_parts = []
        amount = None
        action = "mod"
        for p in pos:
            if p.lstrip("-").isdigit() and amount is None:
                amount = int(p)
            elif p in ("set", "max", "mod"):
                action = p
            else:
                name_parts.append(p)

        name = " ".join(name_parts)
        if not name:
            print_error("Usage: !init hp <name> [amount]")
            return

        if amount is None:
            # Just show HP
            c = self._find_combatant(name)
            if c:
                print(f"{c['name']}: {format_hp(c['hp'], c['max_hp'])}")
                if c.get("temp_hp", 0) > 0:
                    print(f"  Temp HP: {c['temp_hp']}")
            return

        if action == "set":
            self.api.patch(f"/sessions/{sid}/combatants/{self._find_combatant_id(name)}",
                          {"hp": amount})
            print_success(f"{name}: HP set to {amount}")
        elif action == "max":
            self.api.patch(f"/sessions/{sid}/combatants/{self._find_combatant_id(name)}",
                          {"max_hp": amount})
            print_success(f"{name}: Max HP set to {amount}")
        else:
            # Positive = heal, negative = damage (Avrae convention)
            if amount > 0:
                data, _ = self.api.post(f"/sessions/{sid}/heal",
                                       {"combatant": name, "amount": amount})
            else:
                data, _ = self.api.post(f"/sessions/{sid}/damage",
                                       {"combatant": name, "amount": abs(amount)})
            if data and "new_hp" in data:
                delta = data["new_hp"] - data["old_hp"]
                if delta > 0:
                    print_success(f"{name}: healed {delta} HP ({format_hp(data['new_hp'], data['max_hp'])})")
                else:
                    print(f"{name}: took {abs(delta)} damage ({format_hp(data['new_hp'], data['max_hp'])})")
                if data.get("resistance_modifiers"):
                    print(f"  ({', '.join(data['resistance_modifiers'])})")

    # ---- !init thp ----
    def cmd_init_thp(self, pos, flags):
        sid = self._sid()
        if not sid or len(pos) < 2:
            print_error("Usage: !init thp <name> <amount>")
            return
        name = " ".join(pos[:-1])
        amount = int(pos[-1])
        data, _ = self.api.post(f"/sessions/{sid}/temp_hp",
                               {"combatant": name, "amount": amount})
        if data and "temp_hp" in data:
            print_success(f"{name}: Temp HP set to {data['temp_hp']}")

    # ---- !init effect ----
    def cmd_init_effect(self, pos, flags):
        sid = self._sid()
        if not sid or len(pos) < 2:
            print_error('Usage: !init effect <target> <effect_name> [-dur N] [conc] [-b BONUS] [-d DAMAGE] ...')
            return

        target = pos[0]
        effect_name = " ".join(pos[1:])
        duration = int(flags["dur"]) if "dur" in flags else None

        # Build passive effects from flags
        pe = {}
        if "b" in flags:
            pe["to_hit_bonus"] = str(flags["b"])
        if "d" in flags:
            pe["damage_bonus"] = str(flags["d"])
        if "ac" in flags:
            val = flags["ac"]
            if str(val).startswith(("+", "-")):
                pe["ac_bonus"] = int(val)
            else:
                pe["ac_value"] = int(val)
        if "maxhp" in flags:
            val = flags["maxhp"]
            if str(val).startswith(("+", "-")):
                pe["max_hp_bonus"] = int(val)
            else:
                pe["max_hp_value"] = int(val)
        if "sb" in flags:
            pe["save_bonus"] = str(flags["sb"])
        if "cb" in flags:
            pe["check_bonus"] = str(flags["cb"])
        if "dc" in flags:
            pe["dc_bonus"] = int(flags["dc"])
        if "magical" in flags:
            pe["magical_damage"] = True
        if "silvered" in flags:
            pe["silvered_damage"] = True
        if "adv" in flags:
            pe["attack_advantage"] = 1
        if "dis" in flags:
            pe["attack_advantage"] = -1
        if "sadv" in flags:
            pe["save_adv"] = [flags["sadv"]] if flags["sadv"] is not True else ["str","dex","con","int","wis","cha"]
        if "sdis" in flags:
            pe["save_dis"] = [flags["sdis"]] if flags["sdis"] is not True else ["str","dex","con","int","wis","cha"]

        # Resistances
        for rtype in ("resist", "immune", "vuln", "neutral"):
            if rtype in flags:
                pe.setdefault(f"{rtype}ances" if rtype != "neutral" else "ignored_resistances",
                             []).append({"dtype": flags[rtype]})
        # Fix key names
        if "resistances" not in pe and "resist" in flags:
            pe["resistances"] = [{"dtype": flags["resist"]}]
        if "immunities" not in pe and "immune" in flags:
            pe["immunities"] = [{"dtype": flags["immune"]}]
        if "vulnerabilities" not in pe and "vuln" in flags:
            pe["vulnerabilities"] = [{"dtype": flags["vuln"]}]

        body = {
            "combatant": target,
            "name": effect_name,
            "duration": duration,
            "concentration": "conc" in flags,
            "end_on_turn_end": "end" in flags,
            "passive_effects": pe if pe else None,
        }

        data, code = self.api.post(f"/sessions/{sid}/effect", body)
        if code in (200, 201) and data and "name" in data:
            dur_str = f" for {duration} rounds" if duration else ""
            conc_str = " [Concentration]" if "conc" in flags else ""
            print_success(f"Added {effect_name} to {target}{dur_str}{conc_str}")
            if data.get("concentration_removed"):
                for removed in data["concentration_removed"]:
                    print(f"  {DIM}Dropped concentration: {removed}{RESET}")
            if pe:
                print(f"  {DIM}{json.dumps(pe)}{RESET}")
        else:
            print_error(data.get("error", "Failed"))

    # ---- !init re (remove effect) ----
    def cmd_init_re(self, pos, flags):
        sid = self._sid()
        if not sid or not pos:
            print_error("Usage: !init re <combatant> [effect_name]")
            return
        combatant = pos[0]
        effect_name = " ".join(pos[1:]) if len(pos) > 1 else None
        if effect_name:
            # Try to remove by name via effect endpoint
            data, _ = self.api.post(f"/sessions/{sid}/effect",
                                   {"combatant": combatant, "name": f"__remove__{effect_name}"})
            # Actually need a proper DELETE — let's use the status to get effect ID
            c = self._find_combatant(combatant)
            if c:
                for e in c.get("effects", []):
                    if effect_name.lower() in e["name"].lower():
                        self.api.delete(f"/sessions/{sid}/combatants/{c['id']}/effects/{e['id']}")
                        print_success(f"Removed {e['name']} from {combatant}")
                        return
            print_error(f"Effect '{effect_name}' not found on {combatant}")
        else:
            print_error("Usage: !init re <combatant> <effect_name>")

    # ---- !init attack / !a ----
    def cmd_init_attack(self, pos, flags):
        sid = self._sid()
        if not sid:
            return

        attacker = None
        if self._current_combatant:
            attacker = self._current_combatant.get("name")

        target = flags.get("t")
        attack_bonus = flags.get("b")
        damage = flags.get("d")
        damage_type = flags.get("dtype")
        attack_name = None

        # Parse: !a <attack_name> -t <target> or !a -t <target> -b <bonus> -d <damage>
        if pos and not attack_bonus:
            attack_name = pos[0]
        if not target and pos:
            target = pos[-1] if len(pos) > 1 else (pos[0] if attack_name is None else None)

        if not target:
            print_error("Usage: !a [attack_name] -t <target> [-b BONUS] [-d DAMAGE]")
            return

        advantage = None
        if "adv" in flags:
            advantage = "advantage"
        elif "dis" in flags:
            advantage = "disadvantage"

        # If no bonus/damage specified, try NAMED ATTACK via the real AttackList
        if (not attack_bonus or not damage) and attacker:
            body = {
                "attacker": attacker,
                "attack": attack_name or "",
                "target": target,
                "args": "",
                "advantage": advantage,
            }
            data, code = self.api.post(f"/sessions/{sid}/named_attack", body)
            if code == 200 and data:
                print(f"\n{BOLD}{data['attacker']}{RESET} attacks {BOLD}{data['target']}{RESET} "
                      f"with {CYAN}{data.get('attack', 'attack')}{RESET}!")
                if data.get("embed_fields"):
                    for field in data["embed_fields"]:
                        print(f"  {BOLD}{field['name']}:{RESET} {field['value'][:200]}")
                if data.get("target_hp") is not None:
                    print(f"  Target HP: {data['target_hp']}/{data.get('target_max_hp', '?')}")
                return
            elif code == 400 and "No attacks found" in data.get("error", ""):
                if not attack_bonus or not damage:
                    print_error("No named attacks. Use: !a -t <target> -b <bonus> -d <damage>")
                    return
            # Fall through to manual attack if named attack fails

        body = {
            "attacker": attacker,
            "target": target,
            "attack_bonus": int(attack_bonus),
            "damage": damage,
            "damage_type": damage_type,
            "advantage": advantage,
        }

        data, code = self.api.post(f"/sessions/{sid}/attack", body)
        if code != 200:
            print_error(data.get("error", "Attack failed"))
            return

        # Format like Avrae
        hit_str = f"{GREEN}HIT!{RESET}" if data["hit"] else f"{RED}MISS!{RESET}"
        if data.get("is_crit"):
            hit_str = f"{YELLOW}{BOLD}CRITICAL HIT!{RESET}"

        print(f"\n{BOLD}{data['attacker']}{RESET} attacks {BOLD}{data['target']}{RESET}!")
        print(f"  {BOLD}To Hit:{RESET} {data['attack_roll']} (AC {data['target_ac']}) {hit_str}")

        if data.get("damage"):
            dmg = data["damage"]
            dtype_str = f" [{dmg.get('type', 'untyped')}]" if dmg.get("type") else ""
            print(f"  {BOLD}Damage:{RESET} {dmg['roll']}{dtype_str}")
            if dmg.get("resistance_modifiers"):
                print(f"  ({', '.join(dmg['resistance_modifiers'])})")
            if dmg.get("final") != dmg.get("total"):
                print(f"  Raw: {dmg['total']} → Final: {dmg['final']}")
            hr = dmg.get("hp_result", {})
            if hr:
                print(f"  {data['target']}: {format_hp(hr['new_hp'], hr['max_hp'])}")
                if hr.get("concentration_check_dc"):
                    print(f"  {YELLOW}Concentration check: DC {hr['concentration_check_dc']}{RESET}")

    # ---- !r / !roll ----
    def cmd_roll(self, pos, flags):
        expr = " ".join(pos) if pos else "1d20"
        advantage = None
        if "adv" in flags:
            advantage = "advantage"
        elif "dis" in flags:
            advantage = "disadvantage"
        data, code = self.api.post("/roll", {"expression": expr, "advantage": advantage})
        if code == 200:
            print_roll("Roll", data["result"], data["total"])
        else:
            print_error(data.get("error", "Roll failed"))

    # ---- !cast ----
    def cmd_cast(self, pos, flags):
        sid = self._sid()
        if not sid or not pos:
            print_error("Usage: !cast <spell_name> [-t TARGET] [-l LEVEL]")
            return

        caster = self._current_combatant.get("name") if self._current_combatant else None
        if not caster:
            print_error("No current combatant. Use !init next first.")
            return

        spell_name = " ".join(pos)
        targets = []
        if "t" in flags:
            targets = [flags["t"]]

        body = {
            "caster": caster,
            "spell": spell_name,
            "targets": targets,
            "level": int(flags["l"]) if "l" in flags else None,
        }

        advantage = None
        if "adv" in flags:
            body["advantage"] = "advantage"
        elif "dis" in flags:
            body["advantage"] = "disadvantage"

        data, code = self.api.post(f"/sessions/{sid}/cast", body)
        if code != 200:
            print_error(data.get("error", "Cast failed"))
            return

        print(f"\n{BOLD}{data['caster']}{RESET} casts {CYAN}{BOLD}{data['spell']}{RESET}!")
        if data.get("slot_used"):
            print(f"  {DIM}Used level {data['slot_used']} spell slot{RESET}")

        # Print automation results
        results = data.get("results", {}).get("automation_results", [])
        self._print_automation_results(results, indent=2)

    def _print_automation_results(self, results, indent=0):
        pad = " " * indent
        for r in results:
            rtype = r.get("type", "")
            if rtype == "target":
                for tr in r.get("results", []):
                    target_name = tr.get("target", "?")
                    print(f"{pad}{BOLD}Target: {target_name}{RESET}")
                    self._print_automation_results(tr.get("results", []), indent + 2)
            elif rtype == "attack":
                hit_str = f"{GREEN}HIT{RESET}" if r["did_hit"] else f"{RED}MISS{RESET}"
                if r.get("did_crit"):
                    hit_str = f"{YELLOW}{BOLD}CRIT{RESET}"
                print(f"{pad}Attack: {r['attack_roll']} vs AC {r.get('target_ac', '?')} → {hit_str}")
                self._print_automation_results(r.get("children", []), indent + 2)
            elif rtype == "damage":
                dtype = f" [{r.get('damage_type', '')}]" if r.get("damage_type") else ""
                print(f"{pad}Damage: {r['damage_roll']}{dtype}")
                if r.get("resistance_modifiers"):
                    print(f"{pad}  ({', '.join(r['resistance_modifiers'])})")
                hr = r.get("hp_result")
                if hr:
                    print(f"{pad}  → {hr['name']}: {format_hp(hr['new_hp'], hr['max_hp'])}")
            elif rtype == "save":
                result = f"{GREEN}PASS{RESET}" if r["did_save"] else f"{RED}FAIL{RESET}"
                print(f"{pad}Save: {r['ability'].upper()} DC {r['dc']}: {r['save_roll']} → {result}")
                self._print_automation_results(r.get("children", []), indent + 2)
            elif rtype == "temphp":
                print(f"{pad}Temp HP: {r.get('amount', 0)}")
            elif rtype == "ieffect":
                if r.get("applied"):
                    dur = f" ({r['duration']} rounds)" if r.get("duration") else ""
                    print(f"{pad}{CYAN}Effect applied: {r['effect_name']}{dur}{RESET}")
            elif rtype == "text":
                if r.get("text"):
                    print(f"{pad}{DIM}{r['text']}{RESET}")

    # ---- !init save / !init s ----
    def cmd_init_save(self, pos, flags):
        sid = self._sid()
        if not sid or not pos:
            print_error("Usage: !init save <ability> [-dc DC]")
            return

        combatant = self._current_combatant.get("name") if self._current_combatant else None
        if not combatant:
            print_error("No current combatant")
            return

        ability = pos[0].lower()
        dc = int(flags.get("dc", 10))

        data, code = self.api.post(f"/sessions/{sid}/save",
                                  {"combatant": combatant, "ability": ability, "dc": dc})
        if code == 200:
            result = f"{GREEN}SUCCESS{RESET}" if data["success"] else f"{RED}FAILURE{RESET}"
            print(f"{BOLD}{data['combatant']}{RESET} {data['ability'].title()} Save (DC {dc})")
            print(f"  {data['roll']} → {result}")
        else:
            print_error(data.get("error", "Failed"))

    # ---- !init check / !init c ----
    def cmd_init_check(self, pos, flags):
        sid = self._sid()
        if not sid or not pos:
            print_error("Usage: !init check <ability> [-dc DC]")
            return

        combatant = self._current_combatant.get("name") if self._current_combatant else None
        if not combatant:
            print_error("No current combatant")
            return

        ability = pos[0].lower()
        dc = int(flags["dc"]) if "dc" in flags else None

        data, code = self.api.post(f"/sessions/{sid}/check",
                                  {"combatant": combatant, "ability": ability, "dc": dc})
        if code == 200:
            result_str = ""
            if "success" in data:
                result_str = f" → {GREEN}SUCCESS{RESET}" if data["success"] else f" → {RED}FAILURE{RESET}"
            print(f"{BOLD}{data['combatant']}{RESET} {data['ability'].title()} Check")
            print(f"  {data['roll']}{result_str}")
        else:
            print_error(data.get("error", "Failed"))

    # ---- !init end ----
    def cmd_init_end(self, pos, flags):
        sid = self._sid()
        if not sid:
            return
        data, code = self.api.post(f"/sessions/{sid}/end")
        if code == 200:
            print_success(f"Combat ended after {data.get('rounds', 0)} rounds.")
            self.session_id = None
            self._current_combatant = None
        else:
            print_error(data.get("error", "Failed"))

    # ---- !init remove ----
    def cmd_init_remove(self, pos, flags):
        sid = self._sid()
        if not sid or not pos:
            print_error("Usage: !init remove <name>")
            return
        name = " ".join(pos)
        cid = self._find_combatant_id(name)
        if cid:
            self.api.delete(f"/sessions/{sid}/combatants/{cid}")
            print_success(f"{name} removed from combat.")
        else:
            print_error(f"Combatant '{name}' not found")

    # ---- !game lr / !game longrest ----
    def cmd_game_longrest(self, pos, flags):
        sid = self._sid()
        if not sid:
            return
        combatant = self._current_combatant.get("name") if self._current_combatant else (pos[0] if pos else None)
        if not combatant:
            print_error("No combatant specified")
            return
        data, _ = self.api.post(f"/sessions/{sid}/long_rest", {"combatant": combatant})
        if data:
            print_success(f"{data.get('combatant', combatant)} takes a long rest.")
            print(f"  HP restored to {data.get('hp', '?')}")

    # ---- !game sr / !game shortrest ----
    def cmd_game_shortrest(self, pos, flags):
        sid = self._sid()
        if not sid:
            return
        combatant = self._current_combatant.get("name") if self._current_combatant else (pos[0] if pos else None)
        if not combatant:
            print_error("No combatant specified")
            return
        data, _ = self.api.post(f"/sessions/{sid}/short_rest", {"combatant": combatant})
        if data:
            print_success(f"{data.get('combatant', combatant)} takes a short rest.")

    # ---- !game ss / !game spellslot ----
    def cmd_game_spellslot(self, pos, flags):
        sid = self._sid()
        if not sid:
            return
        combatant = self._current_combatant.get("name") if self._current_combatant else None
        if not combatant:
            print_error("No current combatant")
            return

        if not pos:
            # Show all slots
            c = self._find_combatant(combatant)
            if c and c.get("spell_slots"):
                ss = c["spell_slots"]
                print(f"{BOLD}Spell Slots:{RESET}")
                for lvl in range(1, 10):
                    max_s = ss.get("max_slots", {}).get(str(lvl), 0)
                    cur_s = ss.get("slots", {}).get(str(lvl), 0)
                    if max_s > 0:
                        filled = "●" * cur_s + "○" * (max_s - cur_s)
                        print(f"  Level {lvl}: {filled} ({cur_s}/{max_s})")
            return

        level = int(pos[0])
        modifier = int(pos[1]) if len(pos) > 1 else -1

        if modifier < 0:
            data, _ = self.api.post(f"/sessions/{sid}/spell_slot",
                                  {"combatant": combatant, "level": level, "action": "use"})
        else:
            data, _ = self.api.post(f"/sessions/{sid}/spell_slot",
                                  {"combatant": combatant, "level": level, "action": "restore"})
        if data:
            print(f"  Level {level}: {data.get('remaining', 0)}/{data.get('max', 0)}")

    # ---- !game ds / !game deathsave ----
    def cmd_game_deathsave(self, pos, flags):
        sid = self._sid()
        if not sid:
            return
        combatant = self._current_combatant.get("name") if self._current_combatant else (pos[0] if pos else None)
        if not combatant:
            print_error("No combatant specified")
            return
        data, _ = self.api.post(f"/sessions/{sid}/death_save", {"combatant": combatant})
        if data:
            if data.get("nat20"):
                print(f"{YELLOW}{BOLD}Natural 20!{RESET} {combatant} regains 1 HP!")
            else:
                result = f"{GREEN}Success{RESET}" if data.get("success") else f"{RED}Failure{RESET}"
                print(f"{BOLD}Death Save:{RESET} {data.get('roll', '?')} → {result}")
            ds = data.get("death_saves", {})
            succ = "●" * ds.get("successes", 0) + "○" * (3 - ds.get("successes", 0))
            fail = "●" * ds.get("failures", 0) + "○" * (3 - ds.get("failures", 0))
            print(f"  Successes: {GREEN}{succ}{RESET} | Failures: {RED}{fail}{RESET}")
            if data.get("is_stable"):
                print(f"  {GREEN}{BOLD}Stabilized!{RESET}")
            if data.get("is_dead"):
                print(f"  {RED}{BOLD}Dead.{RESET}")

    # ---- Lookup ----
    def cmd_lookup_monster(self, pos, flags):
        name = " ".join(pos)
        data, code = self.api.get(f"/lookup/monster/{quote(name)}")
        if code == 200:
            print(f"\n{BOLD}{data['name']}{RESET}")
            print(f"  {data.get('size', '?')} {data.get('creature_type', '?')}, CR {data.get('cr', '?')}")
            print(f"  AC: {data['ac']} | HP: {data['hp']}")
            if data.get("stats"):
                s = data["stats"]
                print(f"  STR {s['strength']} DEX {s['dexterity']} CON {s['constitution']} "
                      f"INT {s['intelligence']} WIS {s['wisdom']} CHA {s['charisma']}")
            for t in data.get("traits", []):
                print(f"  {BOLD}{t['name']}:{RESET} {t['desc'][:100]}...")
            for a in data.get("actions", []):
                print(f"  {BOLD}{a['name']}:{RESET} {a['desc'][:100]}...")
        else:
            print_error(data.get("error", "Not found"))

    def cmd_lookup_spell(self, pos, flags):
        name = " ".join(pos)
        data, code = self.api.get(f"/lookup/spell/{quote(name)}")
        if code == 200:
            lvl = f"Level {data['level']}" if data['level'] > 0 else "Cantrip"
            print(f"\n{BOLD}{data['name']}{RESET} ({lvl} {data.get('school', '')})")
            print(f"  Cast: {data.get('casttime', '?')} | Range: {data.get('range', '?')}")
            print(f"  Components: {data.get('components', '?')} | Duration: {data.get('duration', '?')}")
            if data.get("concentration"):
                print(f"  {YELLOW}Concentration{RESET}")
            if data.get("description"):
                desc = data["description"][:300]
                print(f"  {desc}{'...' if len(data['description']) > 300 else ''}")
            if data.get("automation"):
                print(f"  {GREEN}Has automation ✓{RESET}")
        else:
            print_error(data.get("error", "Not found"))

    # ---- !init aoo (off-turn attack) ----
    def cmd_init_aoo(self, pos, flags):
        sid = self._sid()
        if not sid or not pos:
            print_error("Usage: !init aoo <combatant> [attack_name] -t <target>")
            return
        # First pos is the combatant name, rest is attack
        old_current = self._current_combatant
        self._current_combatant = {"name": pos[0]}
        self.cmd_init_attack(pos[1:], flags)
        self._current_combatant = old_current

    # ---- !init opt ----
    def cmd_init_opt(self, pos, flags):
        sid = self._sid()
        if not sid or not pos:
            print_error("Usage: !init opt <name> [-ac N] [-hp N] [-name NEW] [-h]")
            return
        name = pos[0]
        body = {"combatant": name}
        if "ac" in flags: body["ac"] = int(flags["ac"])
        if "hp" in flags: body["hp"] = int(flags["hp"])
        if "max" in flags: body["max_hp"] = int(flags["max"])
        if "name" in flags: body["name"] = flags["name"]
        if "h" in flags: body["is_private"] = True
        data, code = self.api.post(f"/sessions/{sid}/opt", body)
        if code == 200:
            print_success(f"Updated {name}")
            self._print_combatant_status(data)
        else:
            print_error(data.get("error", "Failed"))

    # ---- !init note ----
    def cmd_init_note(self, pos, flags):
        sid = self._sid()
        if not sid or not pos:
            print_error("Usage: !init note <name> [text]")
            return
        name = pos[0]
        text = " ".join(pos[1:]) if len(pos) > 1 else ""
        if text:
            data, _ = self.api.post(f"/sessions/{sid}/note", {"combatant": name, "text": text})
            if data:
                print_success(f"{name}: note set to '{text}'")
        else:
            c = self._find_combatant(name)
            if c:
                print(f"{BOLD}{name}{RESET} note: {c.get('notes') or '(none)'}")

    # ---- !init move ----
    def cmd_init_move(self, pos, flags):
        sid = self._sid()
        if not sid or not pos:
            print_error("Usage: !init move <target_name_or_init>")
            return
        data, code = self.api.post(f"/sessions/{sid}/move", {"target": pos[0]})
        if code == 200:
            cc = data.get("current_combatant", {})
            print_info(f"Moved to: {cc.get('name', '?')} (Round {data.get('round', '?')})")
        else:
            print_error(data.get("error", "Failed"))

    # ---- !init skipround ----
    def cmd_init_skipround(self, pos, flags):
        sid = self._sid()
        if not sid:
            return
        n = int(pos[0]) if pos else 1
        data, code = self.api.post(f"/sessions/{sid}/skipround", {"rounds": n})
        if code == 200:
            print_success(f"Skipped {data.get('skipped', n)} rounds. Now round {data.get('round', '?')}")
        else:
            print_error(data.get("error", "Failed"))

    # ---- !init reroll ----
    def cmd_init_reroll(self, pos, flags):
        sid = self._sid()
        if not sid:
            return
        data, code = self.api.post(f"/sessions/{sid}/reroll")
        if code == 200:
            print_success("Initiative rerolled!")
            if data.get("new_order"):
                print(data["new_order"])
        else:
            print_error(data.get("error", "Failed"))

    # ---- Generic lookup ----
    def cmd_lookup_generic(self, entity_type, pos):
        if not pos:
            print_error(f"Usage: !{entity_type} <name>")
            return
        name = " ".join(pos)
        data, code = self.api.get(f"/lookup/{entity_type}/{quote(name)}")
        if code == 200:
            print(f"\n{BOLD}{data.get('name', name)}{RESET}")
            for key, val in data.items():
                if key != "name" and val:
                    val_str = str(val)[:300]
                    print(f"  {BOLD}{key}:{RESET} {val_str}")
        else:
            print_error(f"{entity_type.title()} '{name}' not found")

    # ---- Helpers ----
    def _find_combatant(self, name):
        sid = self._sid()
        if not sid:
            return None
        data, code = self.api.get(f"/sessions/{sid}")
        if code != 200:
            return None
        for c in data.get("initiative_order", []):
            if name.lower() in c["name"].lower():
                return c
        return None

    def _find_combatant_id(self, name):
        c = self._find_combatant(name)
        return c["id"] if c else None


# ============================================================
# Command Router
# ============================================================

HELP_TEXT = f"""
{BOLD}Avrae-Compatible D&D CLI{RESET}
{DIM}Same commands as Discord Avrae — running locally{RESET}

{BOLD}Initiative:{RESET}
  !init begin [-name NAME]       Start combat
  !init add <MOD> <NAME> [-hp N] [-ac N] [-resist TYPE] [-immune TYPE]
  !init madd <MONSTER> [-n NUM]  Add monster from compendium
  !init next  / !init n          Next turn
  !init prev                     Previous turn
  !init list                     Show initiative order
  !init status [NAME]            Combatant status
  !init hp <NAME> <±AMOUNT>      Modify HP (positive=heal, negative=damage)
  !init thp <NAME> <AMOUNT>      Set temp HP
  !init effect <NAME> <EFFECT> [-dur N] [conc] [-b BONUS] [-d DMG] [-ac N]
  !init re <NAME> [EFFECT]       Remove effect
  !a [ATTACK_NAME] -t <TARGET>   Named attack (uses combatant's attacks)
  !a -t <TARGET> -b <BONUS> -d <DAMAGE>  Manual attack
  !init aoo <NAME> -t <TARGET>   Off-turn attack
  !init save <ABILITY> [-dc N]   Saving throw
  !init check <ABILITY> [-dc N]  Ability check
  !init opt <NAME> [-ac N] [-hp N] [-name NEW]  Modify combatant
  !init note <NAME> [TEXT]       Set/view note
  !init move <TARGET>            Jump to combatant/init
  !init skipround [N]            Skip N rounds
  !init reroll                   Reroll all initiative
  !init remove <NAME>            Remove combatant
  !init end                      End combat

{BOLD}Dice:{RESET}
  !r <EXPRESSION>                Roll dice (e.g. !r 1d20+5)
  !rr <N> <EXPRESSION>           Roll N times
  !rrr <N> <EXPRESSION> <DC>     Roll N times vs DC

{BOLD}Spells:{RESET}
  !cast <SPELL> -t <TARGET> [-l LEVEL]  Cast a spell with automation

{BOLD}Game Tracking:{RESET}
  !game lr / !game longrest      Long rest
  !game sr / !game shortrest     Short rest
  !game ss [LEVEL] [±N]          View/use spell slots
  !game ds                       Death save

{BOLD}Lookup:{RESET}
  !monster <NAME>                Monster stats & traits
  !spell <NAME>                  Spell details & automation
  !item <NAME>                   Item details
  !feat <NAME>                   Feat details
  !class <NAME>                  Class details
  !race <NAME>                   Race details
  !background <NAME>             Background details
  !condition <NAME>              D&D condition rules
  !rule <NAME>                   Rule reference

{BOLD}Other:{RESET}
  !help                          This help
  !connect <URL>                 Connect to different server
  !quit / !exit                  Exit
"""


def run_cli(server_url):
    cli = DnDCLI(server_url)

    # Check connection
    data, code = cli.api.get("/")
    if code == 0:
        print_error(f"Cannot connect to server at {server_url}")
        print_info("Start the server first, or use !connect <url> to change server.")
    else:
        print(f"{GREEN}Connected to {data.get('name', 'D&D Engine')} v{data.get('version', '?')}{RESET}")
        features = data.get("features", [])
        if features:
            print(f"{DIM}Features: {', '.join(features)}{RESET}")

    print(f"\nType {BOLD}!help{RESET} for commands. Commands work like Avrae on Discord.\n")

    while True:
        try:
            prompt = f"{BOLD}>{RESET} "
            if cli.session_name:
                prompt = f"{CYAN}{cli.session_name}{RESET} {BOLD}>{RESET} "
            raw = input(prompt).strip()
        except (EOFError, KeyboardInterrupt):
            print("\nGoodbye!")
            break

        if not raw:
            continue

        # Strip leading ! if present
        if raw.startswith("!"):
            raw = raw[1:]
        elif raw.startswith("/"):
            raw = raw[1:]

        # Split command
        parts = raw.split(None, 1)
        cmd = parts[0].lower()
        rest = parts[1] if len(parts) > 1 else ""
        pos, flags = parse_args(rest)

        # Route commands
        if cmd in ("help", "h"):
            print(HELP_TEXT)
        elif cmd in ("quit", "exit", "q"):
            print("Goodbye!")
            break
        elif cmd == "connect":
            if pos:
                cli.api.base = pos[0].rstrip("/")
                data, code = cli.api.get("/")
                if code > 0:
                    print_success(f"Connected to {data.get('name', 'server')}")
                else:
                    print_error("Connection failed")
            else:
                print(f"Current server: {cli.api.base}")

        # !r / !roll
        elif cmd in ("r", "roll"):
            cli.cmd_roll(pos, flags)

        # !init subcommands
        elif cmd in ("init", "i"):
            if not pos:
                cli.cmd_init_list([], flags)
                continue
            subcmd = pos[0].lower()
            subpos = pos[1:]

            if subcmd in ("begin", "start"):
                cli.cmd_init_begin(subpos, flags)
            elif subcmd == "add":
                cli.cmd_init_add(subpos, flags)
            elif subcmd == "madd":
                cli.cmd_init_madd(subpos, flags)
            elif subcmd in ("next", "n"):
                cli.cmd_init_next(subpos, flags)
            elif subcmd in ("prev", "previous", "rewind"):
                cli.cmd_init_prev(subpos, flags)
            elif subcmd in ("list", "summary"):
                cli.cmd_init_list(subpos, flags)
            elif subcmd == "status":
                cli.cmd_init_status(subpos, flags)
            elif subcmd in ("hp", "HP"):
                cli.cmd_init_hp(subpos, flags)
            elif subcmd == "thp":
                cli.cmd_init_thp(subpos, flags)
            elif subcmd == "effect":
                cli.cmd_init_effect(subpos, flags)
            elif subcmd == "re":
                cli.cmd_init_re(subpos, flags)
            elif subcmd in ("attack", "a", "action"):
                cli.cmd_init_attack(subpos, flags)
            elif subcmd in ("save", "s"):
                cli.cmd_init_save(subpos, flags)
            elif subcmd in ("check", "c"):
                cli.cmd_init_check(subpos, flags)
            elif subcmd in ("cast",):
                # !init cast <spell> -t <target>
                cli.cmd_cast(subpos, flags)
            elif subcmd == "remove":
                cli.cmd_init_remove(subpos, flags)
            elif subcmd == "end":
                cli.cmd_init_end(subpos, flags)
            elif subcmd in ("opt", "opts"):
                cli.cmd_init_opt(subpos, flags)
            elif subcmd == "note":
                cli.cmd_init_note(subpos, flags)
            elif subcmd in ("aoo", "offturnattack", "oa"):
                cli.cmd_init_aoo(subpos, flags)
            elif subcmd in ("move", "goto"):
                cli.cmd_init_move(subpos, flags)
            elif subcmd in ("skipround", "round", "skiprounds"):
                cli.cmd_init_skipround(subpos, flags)
            elif subcmd in ("reroll", "shuffle"):
                cli.cmd_init_reroll(subpos, flags)
            else:
                print_error(f"Unknown init command: {subcmd}")

        # !a (shortcut for !init attack)
        elif cmd in ("a", "attack"):
            cli.cmd_init_attack(pos, flags)

        # !cast
        elif cmd == "cast":
            cli.cmd_cast(pos, flags)

        # !game subcommands
        elif cmd in ("game", "g"):
            if not pos:
                print_error("Usage: !game <subcommand>")
                continue
            subcmd = pos[0].lower()
            subpos = pos[1:]

            if subcmd in ("lr", "longrest"):
                cli.cmd_game_longrest(subpos, flags)
            elif subcmd in ("sr", "shortrest"):
                cli.cmd_game_shortrest(subpos, flags)
            elif subcmd in ("ss", "spellslot"):
                cli.cmd_game_spellslot(subpos, flags)
            elif subcmd in ("ds", "deathsave"):
                cli.cmd_game_deathsave(subpos, flags)
            elif subcmd in ("hp",):
                cli.cmd_init_hp(subpos, flags)
            else:
                print_error(f"Unknown game command: {subcmd}")

        # !rr (multiroll)
        elif cmd == "rr":
            if len(pos) >= 2:
                try:
                    count = int(pos[0])
                    expr = " ".join(pos[1:])
                    data, _ = cli.api.post("/multiroll", {"expression": expr, "count": count})
                    if data and "results" in data:
                        for r in data["results"]:
                            print(f"  {r['roll']}")
                        print(f"  {BOLD}Total rolls: {len(data['results'])}{RESET}")
                except (ValueError, TypeError):
                    print_error("Usage: !rr <count> <expression>")
            else:
                print_error("Usage: !rr <count> <expression>")

        # !rrr (iterroll)
        elif cmd == "rrr":
            if len(pos) >= 3:
                try:
                    count = int(pos[0])
                    expr = pos[1]
                    dc = int(pos[2])
                    data, _ = cli.api.post("/multiroll", {"expression": expr, "count": count, "dc": dc})
                    if data and "results" in data:
                        for r in data["results"]:
                            result = f"{GREEN}PASS{RESET}" if r.get("success") else f"{RED}FAIL{RESET}"
                            print(f"  {r['roll']} → {result}")
                        print(f"  {BOLD}Successes: {data.get('successes', 0)}/{count}{RESET}")
                except (ValueError, TypeError):
                    print_error("Usage: !rrr <count> <expression> <DC>")
            else:
                print_error("Usage: !rrr <count> <expression> <DC>")

        # Lookup shortcuts
        elif cmd in ("monster", "mon"):
            cli.cmd_lookup_monster(pos, flags)
        elif cmd in ("spell",):
            cli.cmd_lookup_spell(pos, flags)
        elif cmd in ("item",):
            cli.cmd_lookup_generic("item", pos)
        elif cmd in ("feat",):
            cli.cmd_lookup_generic("feat", pos)
        elif cmd in ("class", "classfeat"):
            cli.cmd_lookup_generic("class", pos)
        elif cmd in ("race",):
            cli.cmd_lookup_generic("race", pos)
        elif cmd in ("background", "bg"):
            cli.cmd_lookup_generic("background", pos)
        elif cmd in ("condition",):
            cli.cmd_lookup_generic("condition", pos)
        elif cmd in ("rule",):
            cli.cmd_lookup_generic("rule", pos)

        else:
            print_error(f"Unknown command: {cmd}. Type !help for commands.")


# ============================================================
# Entry Point
# ============================================================

if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="Avrae-compatible D&D CLI")
    parser.add_argument("--server", default=DEFAULT_SERVER,
                        help=f"Server URL (default: {DEFAULT_SERVER})")
    args = parser.parse_args()
    run_cli(args.server)
