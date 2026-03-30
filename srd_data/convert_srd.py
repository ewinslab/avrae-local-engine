#!/usr/bin/env python3
"""
Converts 5e-database JSON format → Avrae compendium format.
Reads from raw/ directory, writes to compendium/ directory.
"""

import json
import os
import re
import math

RAW_DIR = os.path.join(os.path.dirname(__file__), "raw")
OUT_DIR = os.path.join(os.path.dirname(__file__), "compendium")
os.makedirs(OUT_DIR, exist_ok=True)

ALL_SKILLS = [
    "acrobatics", "animalHandling", "arcana", "athletics", "deception",
    "history", "initiative", "insight", "intimidation", "investigation",
    "medicine", "nature", "perception", "performance", "persuasion",
    "religion", "sleightOfHand", "stealth", "survival",
    # Stat-based entries avrae also requires
    "strength", "dexterity", "constitution", "intelligence", "wisdom", "charisma",
]

SKILL_TO_STAT = {
    "acrobatics": "dexterity", "animalHandling": "wisdom", "arcana": "intelligence",
    "athletics": "strength", "deception": "charisma", "history": "intelligence",
    "insight": "wisdom", "intimidation": "charisma", "investigation": "intelligence",
    "medicine": "wisdom", "nature": "intelligence", "perception": "wisdom",
    "performance": "charisma", "persuasion": "charisma", "religion": "intelligence",
    "sleightOfHand": "dexterity", "stealth": "dexterity", "survival": "wisdom",
    "initiative": "dexterity",
    "strength": "strength", "dexterity": "dexterity", "constitution": "constitution",
    "intelligence": "intelligence", "wisdom": "wisdom", "charisma": "charisma",
}

SAVE_NAMES = ["strengthSave", "dexteritySave", "constitutionSave",
              "intelligenceSave", "wisdomSave", "charismaSave"]

# 5e-database skill index -> avrae skill name
SKILL_INDEX_MAP = {
    "skill-acrobatics": "acrobatics", "skill-animal-handling": "animalHandling",
    "skill-arcana": "arcana", "skill-athletics": "athletics",
    "skill-deception": "deception", "skill-history": "history",
    "skill-insight": "insight", "skill-intimidation": "intimidation",
    "skill-investigation": "investigation", "skill-medicine": "medicine",
    "skill-nature": "nature", "skill-perception": "perception",
    "skill-performance": "performance", "skill-persuasion": "persuasion",
    "skill-religion": "religion", "skill-sleight-of-hand": "sleightOfHand",
    "skill-stealth": "stealth", "skill-survival": "survival",
}

SAVE_INDEX_MAP = {
    "saving-throw-str": "strengthSave", "saving-throw-dex": "dexteritySave",
    "saving-throw-con": "constitutionSave", "saving-throw-int": "intelligenceSave",
    "saving-throw-wis": "wisdomSave", "saving-throw-cha": "charismaSave",
}


def mod(score):
    return (score - 10) // 2


def convert_monster(m):
    """Convert 5e-database monster → avrae monster format."""
    stats = {
        "strength": m["strength"], "dexterity": m["dexterity"],
        "constitution": m["constitution"], "intelligence": m["intelligence"],
        "wisdom": m["wisdom"], "charisma": m["charisma"],
    }
    prof_bonus = m.get("proficiency_bonus", 2)

    # Build proficiency maps from proficiencies array
    skill_profs = {}  # skill_name -> value
    save_profs = {}   # saveName -> value
    for p in m.get("proficiencies", []):
        idx = p["proficiency"]["index"]
        val = p["value"]
        if idx in SKILL_INDEX_MAP:
            skill_profs[SKILL_INDEX_MAP[idx]] = val
        elif idx in SAVE_INDEX_MAP:
            save_profs[SAVE_INDEX_MAP[idx]] = val

    # Build full skill map (avrae requires ALL skills)
    skills = {}
    for skill_name in ALL_SKILLS:
        stat_name = SKILL_TO_STAT[skill_name]
        base_mod = mod(stats[stat_name])
        if skill_name in skill_profs:
            skills[skill_name] = {"value": skill_profs[skill_name], "prof": 1}
        else:
            skills[skill_name] = {"value": base_mod}

    # Build full saves map
    saves = {}
    for save_name in SAVE_NAMES:
        stat_short = save_name.replace("Save", "")
        base_mod = mod(stats[stat_short])
        if save_name in save_profs:
            saves[save_name] = {"value": save_profs[save_name], "prof": 1}
        else:
            saves[save_name] = {"value": base_mod}

    # AC
    ac_data = m.get("armor_class", [{}])
    ac = ac_data[0].get("value", 10) if ac_data else 10
    armortype = ac_data[0].get("type", "") if ac_data else ""

    # Speed
    speed_parts = []
    speed_data = m.get("speed", {})
    for k, v in speed_data.items():
        if k == "walk":
            speed_parts.insert(0, v)
        else:
            speed_parts.append(f"{k} {v}")
    speed = ", ".join(speed_parts) if speed_parts else "30 ft."

    # Senses
    senses_data = m.get("senses", {})
    senses_parts = []
    for k, v in senses_data.items():
        if k == "passive_perception":
            senses_parts.append(f"passive Perception {v}")
        else:
            senses_parts.append(f"{k.replace('_', ' ')} {v}")
    senses = ", ".join(senses_parts)

    # Resistances
    def make_resist_list(items):
        result = []
        for item in items:
            if isinstance(item, str):
                result.append({"dtype": item.lower()})
            elif isinstance(item, dict):
                result.append({"dtype": item.get("type", str(item)).lower()})
        return result

    display_resists = {
        "resist": make_resist_list(m.get("damage_resistances", [])),
        "immune": make_resist_list(m.get("damage_immunities", [])),
        "vuln": make_resist_list(m.get("damage_vulnerabilities", [])),
        "neutral": [],
    }

    # Condition immunities
    condition_immune = [ci.get("name", ci.get("index", "")) for ci in m.get("condition_immunities", [])]

    # Traits (special abilities)
    traits = [{"name": sa["name"], "desc": sa.get("desc", "")}
              for sa in m.get("special_abilities", [])]

    # Actions
    actions = [{"name": a["name"], "desc": a.get("desc", "")}
               for a in m.get("actions", [])]

    # Reactions
    reactions = [{"name": r["name"], "desc": r.get("desc", "")}
                 for r in m.get("reactions", [])]

    # Legendary actions
    legactions = [{"name": la["name"], "desc": la.get("desc", "")}
                  for la in m.get("legendary_actions", [])]

    # Build attack automation from actions
    attacks = []
    for action in m.get("actions", []):
        if action.get("attack_bonus") is not None:
            atk_bonus = action["attack_bonus"]
            # Parse damage from action description or damage array
            damage_parts = []
            for dmg in action.get("damage", []):
                dice = dmg.get("damage_dice", "")
                dtype = ""
                if dmg.get("damage_type"):
                    dtype = dmg["damage_type"].get("name", "").lower()
                if dice:
                    if dtype:
                        damage_parts.append(f"{dice}[{dtype}]")
                    else:
                        damage_parts.append(dice)

            if damage_parts:
                damage_str = "+".join(damage_parts)
                attacks.append({
                    "name": action["name"],
                    "_v": 2,
                    "automation": [{
                        "type": "target",
                        "target": "each",
                        "effects": [{
                            "type": "attack",
                            "attackBonus": str(atk_bonus),
                            "hit": [{"type": "damage", "damage": damage_str}],
                            "miss": [],
                        }],
                    }],
                })

    # CR
    cr = m.get("challenge_rating", 0)
    cr_str = str(cr)
    if cr == 0.125:
        cr_str = "1/8"
    elif cr == 0.25:
        cr_str = "1/4"
    elif cr == 0.5:
        cr_str = "1/2"
    elif isinstance(cr, float):
        cr_str = str(int(cr)) if cr == int(cr) else str(cr)

    return {
        "name": m["name"],
        "size": m.get("size", "Medium"),
        "race": m.get("type", "humanoid"),
        "alignment": m.get("alignment", "unaligned"),
        "ac": ac,
        "armortype": armortype,
        "hp": m.get("hit_points", 10),
        "hitdice": m.get("hit_points_roll", m.get("hit_dice", "1d8")),
        "speed": speed,
        "ability_scores": {"prof_bonus": prof_bonus, **stats},
        "saves": saves,
        "skills": skills,
        "senses": senses,
        "display_resists": display_resists,
        "condition_immune": condition_immune,
        "languages": m.get("languages", "").split(", ") if m.get("languages") else [],
        "cr": cr_str,
        "xp": m.get("xp", 0),
        "traits": traits,
        "actions": actions,
        "reactions": reactions,
        "legactions": legactions,
        "attacks": attacks,
        "bonus_actions": [],
        "mythic_actions": [],
        "la_per_round": 3,
        "passiveperc": senses_data.get("passive_perception", 10),
        "resistances": display_resists,
        "spellbook": None,
        "proper": False,
        "image_url": None,
        "token_free": None,
        "token_sub": None,
        "source": "SRD",
        "id": 0,
        "page": 0,
        "url": "",
        "isFree": True,
        "isLegacy": False,
    }


def convert_spell(s):
    """Convert 5e-database spell → avrae spell format."""
    # Build components string
    components = []
    for c in s.get("components", []):
        components.append(c)
    comp_str = ", ".join(components)
    if s.get("material"):
        comp_str += f" ({s['material']})"

    # Classes
    classes = [c.get("name", c.get("index", "")) for c in s.get("classes", [])]

    # Subclasses
    subclasses = [sc.get("name", "") for sc in s.get("subclasses", [])]

    # Build automation for attack/damage spells
    automation = build_spell_automation(s)

    # Duration — can be string or list depending on data version
    raw_dur = s.get("duration", "Instantaneous")
    if isinstance(raw_dur, str):
        duration = raw_dur
    elif isinstance(raw_dur, list):
        parts = []
        for d in raw_dur:
            if isinstance(d, str):
                parts.append(d)
            elif isinstance(d, dict):
                parts.append(d.get("type", str(d)))
            else:
                parts.append(str(d))
        duration = ", ".join(parts)
    else:
        duration = str(raw_dur)

    # Casting time
    cast_time = "1 action"
    if s.get("casting_time"):
        cast_time = s["casting_time"]

    result = {
        "name": s["name"],
        "level": s.get("level", 0),
        "school": s.get("school", {}).get("name", "Evocation"),
        "classes": classes,
        "subclasses": subclasses,
        "casttime": cast_time,
        "range": s.get("range", "Self"),
        "components": comp_str,
        "duration": duration,
        "description": "\n\n".join(s.get("desc", [])),
        "higherlevels": "\n\n".join(s.get("higher_level", [])) if s.get("higher_level") else None,
        "ritual": s.get("ritual", False),
        "concentration": s.get("concentration", False),
        "automation": automation,
        "rulesVersion": "2014",
        "source": "SRD",
        "id": 0,
        "page": 0,
        "url": "",
        "isFree": True,
    }
    return result


def build_spell_automation(s):
    """Build automation chain from spell data."""
    damage = s.get("damage", {})
    dc_data = s.get("dc", {})
    attack_type = s.get("attack_type")
    heal = s.get("heal_at_slot_level")

    if not damage and not dc_data and not attack_type and not heal:
        return None

    effects = []

    # Attack spell (Fire Bolt, Scorching Ray, etc.)
    if attack_type in ("ranged", "melee"):
        dmg_type = damage.get("damage_type", {}).get("name", "").lower()
        dmg_at_level = damage.get("damage_at_slot_level") or damage.get("damage_at_character_level", {})

        if dmg_at_level:
            # Get base damage
            base_level = min(dmg_at_level.keys(), key=lambda x: int(x))
            base_dmg = dmg_at_level[base_level]
        else:
            base_dmg = "1d6"

        dmg_str = f"{base_dmg}[{dmg_type}]" if dmg_type else base_dmg

        is_cantrip = s.get("level", 0) == 0
        hit_effects = [{"type": "damage", "damage": dmg_str, "cantripScale": is_cantrip}]

        # Higher level scaling for leveled spells
        if not is_cantrip and damage.get("damage_at_slot_level"):
            higher = {}
            base_level_int = int(base_level)
            for lvl_str, dmg_val in dmg_at_level.items():
                if int(lvl_str) > base_level_int:
                    higher[lvl_str] = dmg_val
            if higher:
                hit_effects[0]["higher"] = higher

        effects.append({
            "type": "target", "target": "each",
            "effects": [{
                "type": "attack",
                "attackBonus": "",
                "hit": hit_effects,
                "miss": [],
            }],
        })

    # Save spell (Fireball, Hold Person, etc.)
    elif dc_data:
        save_type = dc_data.get("dc_type", {}).get("index", "dex").replace("saving-throw-", "")[:3]
        success_type = dc_data.get("dc_success", "none")

        dmg_type = damage.get("damage_type", {}).get("name", "").lower()
        dmg_at_level = damage.get("damage_at_slot_level") or damage.get("damage_at_character_level", {})

        if dmg_at_level:
            base_level = min(dmg_at_level.keys(), key=lambda x: int(x))
            base_dmg = dmg_at_level[base_level]
        else:
            base_dmg = "1d6"

        dmg_str = f"{base_dmg}[{dmg_type}]" if dmg_type else base_dmg
        is_cantrip = s.get("level", 0) == 0

        fail_effects = [{"type": "damage", "damage": dmg_str, "cantripScale": is_cantrip}]
        success_effects = []

        if success_type == "half":
            success_effects = [{"type": "damage", "damage": dmg_str, "cantripScale": is_cantrip}]
            # Half damage handled by avrae's save system

        # Higher level scaling
        if not is_cantrip and damage.get("damage_at_slot_level"):
            higher = {}
            base_level_int = int(base_level)
            for lvl_str, dmg_val in dmg_at_level.items():
                if int(lvl_str) > base_level_int:
                    higher[lvl_str] = dmg_val
            if higher:
                fail_effects[0]["higher"] = higher
                if success_effects:
                    success_effects[0]["higher"] = higher

        effects.append({
            "type": "target", "target": "each",
            "effects": [{
                "type": "save",
                "stat": save_type,
                "fail": fail_effects,
                "success": success_effects,
            }],
        })

    # Healing spell
    elif heal:
        base_level = min(heal.keys(), key=lambda x: int(x))
        base_heal = heal[base_level]
        higher = {}
        for lvl, val in heal.items():
            if int(lvl) > int(base_level):
                higher[lvl] = val

        heal_effect = {"type": "damage", "damage": base_heal, "overheal": True}
        if higher:
            heal_effect["higher"] = higher

        effects.append({
            "type": "target", "target": "each",
            "effects": [heal_effect],
        })

    return effects if effects else None


def main():
    print("=== Converting SRD Data to Avrae Format ===\n")

    # Convert Monsters
    monsters_file = os.path.join(RAW_DIR, "5e-SRD-Monsters.json")
    if os.path.exists(monsters_file):
        raw = json.load(open(monsters_file))
        converted = [convert_monster(m) for m in raw]
        out_file = os.path.join(OUT_DIR, "monsters.json")
        json.dump(converted, open(out_file, "w"), indent=2)
        print(f"Monsters: {len(converted)} converted -> {out_file}")

    # Convert Spells
    spells_file = os.path.join(RAW_DIR, "5e-SRD-Spells.json")
    if os.path.exists(spells_file):
        raw = json.load(open(spells_file))
        converted = [convert_spell(s) for s in raw]
        with_auto = sum(1 for s in converted if s.get("automation"))
        out_file = os.path.join(OUT_DIR, "spells.json")
        json.dump(converted, open(out_file, "w"), indent=2)
        print(f"Spells: {len(converted)} converted ({with_auto} with automation) -> {out_file}")

    # Copy conditions (simple format)
    cond_file = os.path.join(RAW_DIR, "5e-SRD-Conditions.json")
    if os.path.exists(cond_file):
        raw = json.load(open(cond_file))
        converted = [{"name": c["name"], "desc": "\n".join(c.get("desc", []))} for c in raw]
        out_file = os.path.join(OUT_DIR, "conditions.json")
        json.dump(converted, open(out_file, "w"), indent=2)
        print(f"Conditions: {len(converted)} converted -> {out_file}")

    # Empty files for required compendium entries
    for fname in ["classes.json", "races.json", "subraces.json", "feats.json",
                  "backgrounds.json", "adventuring-gear.json", "armor.json",
                  "weapons.json", "magic-items.json", "actions.json", "names.json"]:
        path = os.path.join(OUT_DIR, fname)
        if not os.path.exists(path):
            json.dump([], open(path, "w"))
            print(f"{fname}: empty placeholder created")

    print("\n=== Conversion Complete ===")


if __name__ == "__main__":
    main()
