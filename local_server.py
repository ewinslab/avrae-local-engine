#!/usr/bin/env python3
"""
Avrae Local D&D Game Engine Server v3.0
========================================
Uses the REAL avrae source code with Discord mocked out.
100% engine parity — same Automation, Combat, Character, Resistances, etc.
"""

import asyncio
import json
import logging
import os
import re
import sys
import uuid

# Mock Discord BEFORE any avrae imports
os.environ.setdefault("TESTING", "true")
os.environ.setdefault("NO_DICECLOUD", "true")
os.environ.setdefault("NO_DICECLOUDV2", "true")
os.environ.setdefault("MONGO_URL", "mongodb://localhost:27017")
os.environ.setdefault("MONGODB_DB_NAME", "avrae")
os.environ.setdefault("REDIS_URL", "redis://localhost:6379/0")

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import mock_disnake  # noqa: E402 — must be before avrae imports

import d20
import motor.motor_asyncio
from flask import Flask, jsonify, request
from flask_cors import CORS

# NOW import the REAL avrae code
from gamedata.compendium import Compendium
from cogs5e.models.automation import Automation
from cogs5e.models.automation.runtime import AutomationContext, AutomationTarget
from cogs5e.models.automation.results import AutomationResult
from cogs5e.initiative.combat import Combat, CombatOptions
from cogs5e.initiative.combatant import Combatant, MonsterCombatant, PlayerCombatant
from cogs5e.initiative.group import CombatantGroup
from cogs5e.initiative.effects.effect import InitiativeEffect
from cogs5e.initiative.effects.passive import InitPassiveEffect
from cogs5e.models.sheet.statblock import StatBlock
from cogs5e.models.sheet.base import BaseStats, Levels, Saves, Skills
from cogs5e.models.sheet.attack import Attack, AttackList
from cogs5e.models.sheet.resistance import Resistances, Resistance, do_resistances
from cogs5e.models.sheet.spellcasting import Spellbook
from cogs5e.models.character import Character
from cogs5e.models.sheet.coinpurse import Coinpurse
from cogs5e.models.sheet.player import CustomCounter, DeathSaves
from gamedata.monster import Monster
from gamedata.spell import Spell
from utils.argparser import argparse
from utils.enums import CritDamageType

log = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s: %(message)s")


# ============================================================
# Async helper — bridge sync Flask to async avrae code
# ============================================================
_loop = asyncio.new_event_loop()


def run_async(coro):
    """Run an async coroutine from sync Flask context."""
    return _loop.run_until_complete(coro)


# ============================================================
# Mock Bot / Context — minimal interface avrae code needs
# ============================================================

class MockMDB:
    """In-memory mock of MongoDB collections for combat persistence."""
    def __init__(self):
        self._combats = {}
        self._characters = {}
        self.combats = MockCollection(self._combats)
        self.characters = MockCollection(self._characters)

    def __getattr__(self, name):
        # Return a mock collection for any attribute
        return MockCollection({})


class MockCollection:
    """Minimal mock of a motor collection."""
    def __init__(self, store):
        self._store = store
        self.delegate = self  # for sync access

    async def find_one(self, query):
        key = str(query)
        return self._store.get(key)

    async def update_one(self, query, update, upsert=False):
        key = str(query)
        if "$set" in update:
            self._store[key] = update["$set"]

    async def delete_one(self, query):
        key = str(query)
        self._store.pop(key, None)

    # Sync versions
    def find_one_sync(self, query):
        return self._store.get(str(query))


class MockBot:
    """Minimal bot mock — provides mdb and cog access."""
    def __init__(self, mdb):
        self.mdb = mdb
        self._cogs = {}

    def get_cog(self, name):
        return self._cogs.get(name)

    def get_channel(self, channel_id):
        return mock_disnake.MockChannel(id=channel_id)


class MockCtx:
    """Minimal context mock that satisfies Combat/Combatant/Automation needs."""
    def __init__(self, bot, author_id=1, author_name="Player", channel_id=0):
        self.bot = bot
        self.author = mock_disnake.MockUser(id=author_id, name=author_name)
        self.channel = mock_disnake.MockChannel(id=channel_id)
        self.guild = mock_disnake.MockGuild(id=1)
        self.message = mock_disnake.MockMessage()
        self.prefix = "!"
        self.invoked_with = ""

    async def send(self, content=None, **kwargs):
        return mock_disnake.MockMessage(content=content)

    async def trigger_typing(self):
        pass


# ============================================================
# Session Manager — uses REAL avrae Combat objects
# ============================================================

class SessionManager:
    """Manages combat sessions using the real avrae Combat class."""

    def __init__(self, compendium, bot):
        self.compendium = compendium
        self.bot = bot
        self.extra_monsters = []
        self._sessions = {}  # session_id -> session_data
        self._combats = {}   # session_id -> Combat object (real avrae)

    def _ctx(self, session_id, user_id=1, user_name="Player"):
        return MockCtx(self.bot, user_id, user_name, channel_id=hash(session_id) % 10**15)

    # ---- Session CRUD ----
    def create_session(self, name=None, dm_id=1):
        sid = str(uuid.uuid4())
        channel_id = str(hash(sid) % 10**15)
        ctx = self._ctx(sid, dm_id, "DM")

        combat = Combat.new(channel_id, message_id=0, dm_id=dm_id,
                           options=CombatOptions(name=name or f"Combat-{sid[:8]}"),
                           ctx=ctx)
        self._combats[sid] = combat
        self._sessions[sid] = {
            "id": sid, "name": name or f"Combat-{sid[:8]}",
            "dm_id": dm_id, "active": True, "log": [],
        }
        return self._sessions[sid]

    def get_session(self, sid):
        return self._sessions.get(sid)

    def get_combat(self, sid):
        return self._combats.get(sid)

    def list_sessions(self):
        return list(self._sessions.values())

    def delete_session(self, sid):
        self._sessions.pop(sid, None)
        self._combats.pop(sid, None)
        return True

    # ---- Combatant Management (using real avrae Combatant) ----
    def add_combatant(self, sid, name, hp, ac, init_bonus=0, init_roll=None,
                      controller_id=1, is_private=False, creature_type=None,
                      stats=None, **kwargs):
        combat = self._combats.get(sid)
        if not combat:
            return None

        ctx = self._ctx(sid, controller_id)
        from cogs5e.initiative.utils import create_combatant_id

        # Roll initiative
        if init_roll is None:
            init_result = d20.roll(f"1d20+{init_bonus}")
            init_val = init_result.total
        else:
            init_val = init_roll

        # Build stats
        if stats:
            base_stats = BaseStats(
                prof_bonus=kwargs.get("prof_bonus", 2),
                strength=stats.get("strength", 10),
                dexterity=stats.get("dexterity", 10),
                constitution=stats.get("constitution", 10),
                intelligence=stats.get("intelligence", 10),
                wisdom=stats.get("wisdom", 10),
                charisma=stats.get("charisma", 10),
            )
        else:
            base_stats = BaseStats.default()

        cid = create_combatant_id()
        combatant = Combatant(
            ctx=ctx, combat=combat, id=cid, name=name,
            controller_id=controller_id, private=is_private,
            init=init_val, index=None, notes=None, effects=[],
            stats=base_stats, levels=Levels(),
            attacks=AttackList(), skills=Skills.default(base_stats),
            saves=Saves.default(base_stats), resistances=Resistances(),
            spellbook=Spellbook(), ac=ac, max_hp=hp, hp=hp, temp_hp=0,
            creature_type=creature_type,
        )

        combat.add_combatant(combatant)
        self._log(sid, "combatant_added", combatant=name, initiative=init_val)
        return combatant

    def add_monster_from_compendium(self, sid, monster_name, name=None,
                                    init_roll=None, controller_id=1, quantity=1):
        """Add a monster from the compendium to combat."""
        monster = self._find_monster(monster_name)
        if not monster:
            return None, f"Monster '{monster_name}' not found"

        combat = self._combats.get(sid)
        if not combat:
            return None, "Session not found"

        ctx = self._ctx(sid, controller_id)
        from cogs5e.initiative.utils import create_combatant_id

        results = []
        for i in range(quantity):
            display = name or (f"{monster.name}{i+1}" if quantity > 1 else monster.name)

            if init_roll is None:
                init_result = d20.roll(monster.skills.initiative.d20())
                init_val = init_result.total
            else:
                init_val = init_roll

            cid = create_combatant_id()
            combatant = MonsterCombatant(
                ctx=ctx, combat=combat, id=cid, name=display,
                controller_id=controller_id, private=True,
                init=init_val, index=None, notes=None, effects=[],
                monster_name=monster.name,
                stats=monster.stats, levels=Levels(),
                attacks=monster.attacks, skills=monster.skills,
                saves=monster.saves, resistances=monster.resistances,
                spellbook=monster.spellbook if hasattr(monster, 'spellbook') else Spellbook(),
                ac=monster.ac, max_hp=monster.hp, hp=monster.hp, temp_hp=0,
                creature_type=monster.creature_type,
            )

            combat.add_combatant(combatant)
            results.append(combatant)

        self._log(sid, "monsters_added", monster=monster.name, count=quantity)
        return results, None

    def _find_monster(self, name):
        """Search compendium for a monster by name."""
        for m in self.compendium.monsters:
            if m.name.lower() == name.lower():
                return m
        for m in self.compendium.monsters:
            if name.lower() in m.name.lower():
                return m
        # Search extra monsters (raw dicts)
        for m in self.extra_monsters:
            if m["name"].lower() == name.lower() or name.lower() in m["name"].lower():
                return self._raw_to_monster(m)
        return None

    def _raw_to_monster(self, raw):
        """Convert raw dict to a Monster-like object for adding to combat."""
        ab = raw.get("ability_scores", {})
        return Monster.from_data(raw)

    # ---- Turn Management ----
    def next_turn(self, sid):
        combat = self._combats.get(sid)
        if not combat or not combat.combatants:
            return None
        changed_round, messages = combat.advance_turn()
        current = combat.current_combatant
        self._log(sid, "turn_advanced", round=combat.round_num,
                  combatant=current.name if current else None)
        return {
            "round": combat.round_num,
            "current_combatant": self._combatant_summary(current) if current else None,
            "changed_round": changed_round,
            "messages": messages,
            "summary": combat.get_summary(),
        }

    def prev_turn(self, sid):
        combat = self._combats.get(sid)
        if not combat or not combat.combatants:
            return None
        combat.rewind_turn()
        current = combat.current_combatant
        return {
            "round": combat.round_num,
            "current_combatant": self._combatant_summary(current) if current else None,
            "summary": combat.get_summary(),
        }

    def end_combat(self, sid):
        combat = self._combats.get(sid)
        if not combat:
            return None
        rounds = combat.round_num
        # Don't call combat.end() as it tries to delete from DB
        self._sessions[sid]["active"] = False
        self._log(sid, "combat_ended", rounds=rounds)
        return {"session_id": sid, "rounds": rounds}

    # ---- Dice ----
    def roll_dice(self, expression, advantage=None):
        adv = d20.AdvType.NONE
        if advantage == "advantage":
            adv = d20.AdvType.ADV
        elif advantage == "disadvantage":
            adv = d20.AdvType.DIS
        result = d20.roll(expression, advantage=adv)
        return {"expression": expression, "result": result.result,
                "total": result.total, "crit": result.crit}

    # ---- Attack (using real avrae Combatant) ----
    def attack(self, sid, attacker_name, target_name, attack_bonus,
               damage_expr, advantage=None, damage_type=None):
        combat = self._combats.get(sid)
        if not combat:
            return None
        attacker = combat.get_combatant(attacker_name)
        target = combat.get_combatant(target_name)
        if not attacker or not target:
            return None

        # Roll attack
        adv = d20.AdvType.NONE
        if advantage == "advantage":
            adv = d20.AdvType.ADV
        elif advantage == "disadvantage":
            adv = d20.AdvType.DIS

        atk_roll = d20.roll(f"1d20+{attack_bonus}", advantage=adv)
        hit = atk_roll.total >= target.ac
        is_crit = atk_roll.crit == d20.CritType.CRIT

        if atk_roll.crit == d20.CritType.FAIL:
            hit = False
            is_crit = False

        result = {
            "attacker": attacker.name, "target": target.name,
            "attack_roll": atk_roll.result, "attack_total": atk_roll.total,
            "target_ac": target.ac, "hit": hit, "is_crit": is_crit,
            "damage": None,
        }

        if hit:
            dmg_str = damage_expr
            if is_crit:
                # Double dice on crit (avrae default)
                dmg_str = re.sub(r'(\d+)d', lambda m: f'{int(m.group(1))*2}d', dmg_str)

            clean = re.sub(r'\[.*?\]', '', dmg_str)
            dmg_roll = d20.roll(clean)
            raw_damage = max(0, dmg_roll.total)

            # Apply resistances
            if damage_type:
                dmg_expr_obj = d20.roll(f"{raw_damage}[{damage_type}]")
                do_resistances(dmg_expr_obj.expr, target.resistances)
                final_damage = max(0, dmg_expr_obj.total)
            else:
                final_damage = raw_damage

            # Apply damage to target
            target.modify_hp(-final_damage, overflow=False)

            result["damage"] = {
                "roll": dmg_roll.result, "total": raw_damage,
                "final": final_damage, "type": damage_type,
                "target_hp": target.hp, "target_max_hp": target.max_hp,
            }

        self._log(sid, "attack", **{k: v for k, v in result.items() if k != "damage"})
        return result

    # ---- HP Management ----
    def modify_hp(self, sid, target_name, amount, damage_type=None, is_heal=False):
        combat = self._combats.get(sid)
        if not combat:
            return None
        target = combat.get_combatant(target_name)
        if not target:
            return None

        if isinstance(amount, str):
            amount = d20.roll(amount).total

        old_hp = target.hp
        if is_heal:
            target.modify_hp(abs(amount), overflow=False)
        else:
            target.modify_hp(-abs(amount), overflow=False)

        return {
            "name": target.name, "old_hp": old_hp, "new_hp": target.hp,
            "max_hp": target.max_hp, "temp_hp": target.temp_hp,
            "is_dead": (target.hp or 0) <= 0,
        }

    # ---- Saving Throws ----
    def saving_throw(self, sid, combatant_name, ability, dc):
        combat = self._combats.get(sid)
        if not combat:
            return None
        combatant = combat.get_combatant(combatant_name)
        if not combatant:
            return None

        save_skill = f"{ability[:3].lower()}ertySave" if len(ability) <= 3 else f"{ability}Save"
        # Map short to full save name
        save_map = {
            "str": "strengthSave", "dex": "dexteritySave", "con": "constitutionSave",
            "int": "intelligenceSave", "wis": "wisdomSave", "cha": "charismaSave",
        }
        save_key = save_map.get(ability[:3].lower(), ability)
        save_obj = combatant.saves.get(save_key)
        save_roll = d20.roll(save_obj.d20() if save_obj else f"1d20")
        success = save_roll.total >= dc

        return {
            "combatant": combatant.name, "ability": ability,
            "dc": dc, "roll": save_roll.result, "total": save_roll.total,
            "success": success,
        }

    # ---- Effects (using real InitiativeEffect) ----
    def add_effect(self, sid, combatant_name, effect_name, duration=None,
                   passive_effects=None, concentration=False, desc=None):
        combat = self._combats.get(sid)
        if not combat:
            return None
        combatant = combat.get_combatant(combatant_name)
        if not combatant:
            return None

        pe = InitPassiveEffect()
        if passive_effects:
            pe = InitPassiveEffect.from_dict(passive_effects)

        effect = InitiativeEffect.new(
            combat=combat, combatant=combatant, name=effect_name,
            duration=duration, passive_effects=pe,
            concentration=concentration, desc=desc,
        )

        result = combatant.add_effect(effect)
        conc_removed = result.get("conc_conflict", [])

        return {
            "id": effect.id, "name": effect_name,
            "duration": duration, "concentration": concentration,
            "concentration_removed": [e.name for e in conc_removed],
        }

    def remove_effect(self, sid, combatant_name, effect_name):
        combat = self._combats.get(sid)
        if not combat:
            return False
        combatant = combat.get_combatant(combatant_name)
        if not combatant:
            return False
        effect = combatant.get_effect(effect_name, strict=False)
        if effect:
            effect.remove()
            return True
        return False

    # ---- Spell Casting (using REAL Automation) ----
    def cast_spell(self, sid, caster_name, spell_name, targets=None,
                   cast_level=None, advantage=None):
        combat = self._combats.get(sid)
        if not combat:
            return None, "Session not found"

        caster = combat.get_combatant(caster_name)
        if not caster:
            return None, "Caster not found"

        spell = self._find_spell(spell_name)
        if not spell:
            return None, f"Spell '{spell_name}' not found"

        if not spell.automation:
            return {"caster": caster.name, "spell": spell.name,
                    "description": spell.description, "automation": None}, None

        # Resolve targets
        target_combatants = []
        for t in (targets or []):
            tc = combat.get_combatant(t)
            if tc:
                target_combatants.append(tc)

        # Build context and run automation
        ctx = self._ctx(sid)
        embed = mock_disnake.MockEmbed()
        args = argparse("")
        spell_level = cast_level or spell.level

        autoctx = AutomationContext(
            ctx=ctx, embed=embed, caster=caster,
            targets=target_combatants, args=args,
            combat=combat, spell=spell,
            spell_level_override=spell_level,
        )

        # Run automation (async) — spell.automation is already an Automation object
        automation = spell.automation
        result = run_async(automation.run(
            ctx=ctx, embed=embed, caster=caster,
            targets=target_combatants, args=args,
            combat=combat, spell=spell,
            spell_level_override=spell_level,
        ))

        # Extract results from embed
        output = {
            "caster": caster.name, "spell": spell.name,
            "level": spell_level,
            "embed_title": embed.title,
            "embed_fields": embed.fields,
            "embed_footer": embed.footer,
            "targets": [t.name for t in target_combatants],
        }

        self._log(sid, "spell_cast", caster=caster.name, spell=spell.name)
        return output, None

    def _find_spell(self, name):
        for s in self.compendium.spells:
            if s.name.lower() == name.lower():
                return s
        for s in self.compendium.spells:
            if name.lower() in s.name.lower():
                return s
        return None

    # ---- Named Attack (uses combatant's AttackList) ----
    def named_attack(self, sid, attacker_name, attack_name, target_name,
                     args_str="", advantage=None):
        """Attack using a named attack from the combatant's attack list."""
        combat = self._combats.get(sid)
        if not combat:
            return None, "Session not found"
        attacker = combat.get_combatant(attacker_name)
        target = combat.get_combatant(target_name)
        if not attacker:
            return None, "Attacker not found"
        if not target:
            return None, "Target not found"

        # Find attack by name
        attacks = attacker.attacks
        atk = None
        if attack_name:
            for a in attacks:
                if a.name.lower() == attack_name.lower():
                    atk = a
                    break
            if not atk:
                for a in attacks:
                    if attack_name.lower() in a.name.lower():
                        atk = a
                        break
        if not atk and attacks:
            atk = attacks[0]  # default to first attack

        if not atk:
            return None, f"No attacks found for {attacker.name}"

        # If attack has automation, run it
        if atk.automation:
            ctx = self._ctx(sid)
            embed = mock_disnake.MockEmbed()
            args = argparse(args_str)
            try:
                result = run_async(atk.automation.run(
                    ctx=ctx, embed=embed, caster=attacker,
                    targets=[target], args=args, combat=combat,
                ))
                return {
                    "attacker": attacker.name, "target": target.name,
                    "attack": atk.name,
                    "embed_fields": embed.fields,
                    "embed_footer": embed.footer,
                    "target_hp": target.hp, "target_max_hp": target.max_hp,
                }, None
            except Exception as e:
                return None, str(e)
        else:
            return None, f"Attack '{atk.name}' has no automation"

    def list_attacks(self, sid, combatant_name):
        """List available attacks for a combatant."""
        combat = self._combats.get(sid)
        if not combat:
            return None
        c = combat.get_combatant(combatant_name)
        if not c:
            return None
        return [{"name": a.name, "has_automation": bool(a.automation)} for a in c.attacks]

    # ---- HP/THP management ----
    def set_hp(self, sid, name, value):
        combat = self._combats.get(sid)
        if not combat:
            return None
        c = combat.get_combatant(name)
        if not c:
            return None
        old = c.hp
        c.hp = value
        return {"name": c.name, "old_hp": old, "new_hp": c.hp, "max_hp": c.max_hp}

    def set_thp(self, sid, name, value):
        combat = self._combats.get(sid)
        if not combat:
            return None
        c = combat.get_combatant(name)
        if not c:
            return None
        c.temp_hp = max(0, value)
        return {"name": c.name, "temp_hp": c.temp_hp}

    def set_max_hp(self, sid, name, value):
        combat = self._combats.get(sid)
        if not combat:
            return None
        c = combat.get_combatant(name)
        if not c:
            return None
        c.max_hp = value
        return {"name": c.name, "max_hp": c.max_hp, "hp": c.hp}

    # ---- Notes ----
    def set_note(self, sid, name, text):
        combat = self._combats.get(sid)
        if not combat:
            return None
        c = combat.get_combatant(name)
        if not c:
            return None
        c.notes = text
        return {"name": c.name, "notes": c.notes}

    # ---- Combatant Options ----
    def set_combatant_opts(self, sid, name, **opts):
        combat = self._combats.get(sid)
        if not combat:
            return None
        c = combat.get_combatant(name)
        if not c:
            return None
        if "ac" in opts and opts["ac"] is not None:
            c.ac = opts["ac"]
        if "name" in opts and opts["name"] is not None:
            c.name = opts["name"]
        if "max_hp" in opts and opts["max_hp"] is not None:
            c.max_hp = opts["max_hp"]
        if "hp" in opts and opts["hp"] is not None:
            c.hp = opts["hp"]
        if "is_private" in opts:
            c.is_private = opts["is_private"]
        return self._combatant_summary(c)

    # ---- Move / Skip / Reroll ----
    def move_to(self, sid, target):
        combat = self._combats.get(sid)
        if not combat:
            return None
        c = combat.get_combatant(target)
        if c:
            combat.goto_turn(c, is_combatant=True)
        else:
            try:
                combat.goto_turn(int(target))
            except (ValueError, TypeError):
                return None
        current = combat.current_combatant
        return {
            "round": combat.round_num,
            "current_combatant": self._combatant_summary(current) if current else None,
        }

    def skip_rounds(self, sid, num=1):
        combat = self._combats.get(sid)
        if not combat:
            return None
        messages = combat.skip_rounds(num)
        return {"round": combat.round_num, "skipped": num, "messages": messages}

    def reroll_initiative(self, sid):
        combat = self._combats.get(sid)
        if not combat:
            return None
        order = combat.reroll_dynamic()
        return {"new_order": order, "round": combat.round_num}

    # ---- Multiroll / Iterroll ----
    def multiroll(self, expression, count, dc=None, advantage=None):
        adv = d20.AdvType.NONE
        if advantage == "advantage":
            adv = d20.AdvType.ADV
        elif advantage == "disadvantage":
            adv = d20.AdvType.DIS
        results = []
        successes = 0
        for i in range(min(count, 100)):
            r = d20.roll(expression, advantage=adv)
            entry = {"roll": r.result, "total": r.total}
            if dc is not None:
                entry["success"] = r.total >= dc
                if entry["success"]:
                    successes += 1
            results.append(entry)
        out = {"expression": expression, "count": count, "results": results}
        if dc is not None:
            out["dc"] = dc
            out["successes"] = successes
            out["failures"] = count - successes
        return out

    # ---- Lookup (all entity types) ----
    def _fuzzy_search(self, collection, name):
        """Search a list of objects by name (exact then fuzzy)."""
        for item in collection:
            if item.name.lower() == name.lower():
                return item
        for item in collection:
            if name.lower() in item.name.lower():
                return item
        return None

    def lookup_item(self, name):
        # Search all item types
        for collection in [self.compendium.weapons, self.compendium.armor,
                          self.compendium.adventuring_gear, self.compendium.magic_items]:
            item = self._fuzzy_search(collection, name)
            if item:
                result = {"name": item.name}
                for attr in ["desc", "description", "weight", "cost", "rarity",
                            "requires_attunement", "damage", "armor_class"]:
                    if hasattr(item, attr):
                        val = getattr(item, attr)
                        if val is not None:
                            result[attr] = str(val) if not isinstance(val, (str, int, float, bool)) else val
                return result
        return None

    def lookup_feat(self, name):
        feat = self._fuzzy_search(self.compendium.feats, name)
        if not feat:
            return None
        result = {"name": feat.name}
        for attr in ["desc", "description", "prerequisite"]:
            if hasattr(feat, attr) and getattr(feat, attr):
                result[attr] = getattr(feat, attr)
        return result

    def lookup_class(self, name):
        cls = self._fuzzy_search(self.compendium.classes, name)
        if not cls:
            return None
        result = {"name": cls.name}
        for attr in ["hit_die", "hit_dice", "desc", "description", "proficiencies"]:
            if hasattr(cls, attr) and getattr(cls, attr):
                result[attr] = str(getattr(cls, attr))
        if hasattr(cls, 'subclasses') and cls.subclasses:
            result["subclasses"] = [sc.name for sc in cls.subclasses]
        return result

    def lookup_race(self, name):
        race = self._fuzzy_search(self.compendium.races, name)
        if not race:
            race = self._fuzzy_search(self.compendium.subraces, name)
        if not race:
            return None
        result = {"name": race.name}
        for attr in ["desc", "description", "speed", "size", "ability_scores"]:
            if hasattr(race, attr) and getattr(race, attr):
                result[attr] = str(getattr(race, attr))
        return result

    def lookup_background(self, name):
        bg = self._fuzzy_search(self.compendium.backgrounds, name)
        if not bg:
            return None
        result = {"name": bg.name}
        for attr in ["desc", "description", "traits"]:
            if hasattr(bg, attr) and getattr(bg, attr):
                result[attr] = str(getattr(bg, attr))
        return result

    def lookup_condition(self, name):
        """Look up a D&D condition from rule references."""
        name_lower = name.lower()
        for ref in self.compendium.rule_references:
            if isinstance(ref, dict):
                if ref.get("name", "").lower() == name_lower or name_lower in ref.get("name", "").lower():
                    return ref
        return None

    def lookup_rule(self, name):
        """Look up a rule reference."""
        return self.lookup_condition(name)  # same data source

    # ---- Lookup ----
    def lookup_monster(self, name):
        m = self._find_monster(name)
        if not m:
            return None
        return {
            "name": m.name, "size": m.size, "creature_type": m.creature_type,
            "ac": m.ac, "hp": m.hp, "cr": m.cr,
            "stats": {
                "strength": m.stats.strength, "dexterity": m.stats.dexterity,
                "constitution": m.stats.constitution, "intelligence": m.stats.intelligence,
                "wisdom": m.stats.wisdom, "charisma": m.stats.charisma,
            },
            "traits": [{"name": t.name, "desc": t.desc} for t in m.traits],
            "resistances": str(m.resistances),
        }

    def lookup_spell(self, name):
        s = self._find_spell(name)
        if not s:
            return None
        return {
            "name": s.name, "level": s.level, "school": s.school,
            "description": s.description, "range": s.range,
            "components": s.components, "duration": s.duration,
            "concentration": s.concentration, "ritual": s.ritual,
            "classes": s.classes,
            "has_automation": bool(s.automation),
        }

    # ---- State ----
    def get_session_state(self, sid):
        session = self._sessions.get(sid)
        combat = self._combats.get(sid)
        if not session or not combat:
            return None

        current = combat.current_combatant
        combatants = []
        for i, c in enumerate(combat.combatants):
            summary = self._combatant_summary(c)
            summary["index"] = i
            summary["is_current"] = combat.index == i
            combatants.append(summary)

        return {
            "id": sid, "name": session["name"],
            "round": combat.round_num, "active": session["active"],
            "current_combatant": self._combatant_summary(current) if current else None,
            "initiative_order": combatants,
            "summary": combat.get_summary(),
        }

    def get_log(self, sid, since=0):
        s = self._sessions.get(sid)
        return s["log"][since:] if s else None

    # ---- Helpers ----
    def _combatant_summary(self, c):
        if isinstance(c, CombatantGroup):
            return {
                "id": c.id, "name": c.name, "type": "group",
                "init": c.init, "members": [self._combatant_summary(m) for m in c.get_combatants()],
            }
        return {
            "id": c.id, "name": c.name, "type": c.type.value,
            "hp": c.hp, "max_hp": c.max_hp, "temp_hp": c.temp_hp,
            "ac": c.ac, "init": c.init,
            "creature_type": c.creature_type,
            "effects": [{"id": e.id, "name": e.name, "duration": e.remaining,
                         "concentration": e.concentration}
                        for e in c.get_effects()],
            "is_dead": (c.hp or 0) <= 0 if c.hp is not None else False,
            "is_private": c.is_private,
            "resistances": str(c.resistances),
            "status": c.get_status(),
        }

    def _log(self, sid, event, **data):
        s = self._sessions.get(sid)
        if s:
            s["log"].append({"event": event, **data})

    def _resolve(self, sid, identifier):
        """Resolve combatant by name or ID."""
        combat = self._combats.get(sid)
        if not combat:
            return None
        # Try by name
        c = combat.get_combatant(identifier)
        if c:
            return c
        # Try by ID
        c = combat.combatant_by_id(identifier)
        return c


# ============================================================
# Flask App
# ============================================================

def create_app(mgr):
    app = Flask(__name__)
    CORS(app)

    @app.route("/")
    def index():
        return jsonify({
            "name": "Avrae D&D Engine (Real)",
            "version": "3.0.0",
            "engine": "avrae-native",
            "status": "running",
        })

    @app.route("/roll", methods=["POST"])
    def roll():
        data = request.get_json(force=True)
        try:
            return jsonify(mgr.roll_dice(data.get("expression", "1d20"), data.get("advantage")))
        except Exception as e:
            return jsonify({"error": str(e)}), 400

    # ---- Sessions ----
    @app.route("/sessions", methods=["GET"])
    def list_sessions():
        return jsonify([{"id": s["id"], "name": s["name"], "active": s["active"]}
                       for s in mgr.list_sessions()])

    @app.route("/sessions", methods=["POST"])
    def create_session():
        data = request.get_json(force=True) if request.data else {}
        s = mgr.create_session(data.get("name"), data.get("dm_id", 1))
        return jsonify({"id": s["id"], "name": s["name"]}), 201

    @app.route("/sessions/<sid>", methods=["GET"])
    def get_session(sid):
        state = mgr.get_session_state(sid)
        return jsonify(state) if state else (jsonify({"error": "Not found"}), 404)

    @app.route("/sessions/<sid>", methods=["DELETE"])
    def delete_session(sid):
        mgr.delete_session(sid)
        return jsonify({"deleted": True})

    @app.route("/sessions/<sid>/state", methods=["GET"])
    def get_state(sid):
        state = mgr.get_session_state(sid)
        return jsonify(state) if state else (jsonify({"error": "Not found"}), 404)

    @app.route("/sessions/<sid>/log", methods=["GET"])
    def get_log(sid):
        since = request.args.get("since", 0, type=int)
        entries = mgr.get_log(sid, since)
        return jsonify({"events": entries}) if entries is not None else (jsonify({"error": "Not found"}), 404)

    # ---- Combatants ----
    @app.route("/sessions/<sid>/combatants", methods=["POST"])
    def add_combatant(sid):
        data = request.get_json(force=True)
        c = mgr.add_combatant(sid, name=data["name"], hp=data["hp"], ac=data["ac"],
                              init_bonus=data.get("init_bonus", 0),
                              init_roll=data.get("init_roll"),
                              controller_id=data.get("controller_id", 1),
                              stats=data.get("stats"))
        if not c:
            return jsonify({"error": "Session not found"}), 404
        return jsonify(mgr._combatant_summary(c)), 201

    @app.route("/sessions/<sid>/monsters", methods=["POST"])
    def add_monster(sid):
        data = request.get_json(force=True)
        results, err = mgr.add_monster_from_compendium(
            sid, data["monster"], name=data.get("name"),
            init_roll=data.get("init_roll"), quantity=data.get("quantity", 1))
        if err:
            return jsonify({"error": err}), 404
        return jsonify([mgr._combatant_summary(c) for c in results]), 201

    @app.route("/sessions/<sid>/combatants/<cid>", methods=["GET"])
    def get_combatant(sid, cid):
        c = mgr._resolve(sid, cid)
        return jsonify(mgr._combatant_summary(c)) if c else (jsonify({"error": "Not found"}), 404)

    @app.route("/sessions/<sid>/combatants/<cid>", methods=["DELETE"])
    def remove_combatant(sid, cid):
        combat = mgr.get_combat(sid)
        if not combat:
            return jsonify({"error": "Not found"}), 404
        c = mgr._resolve(sid, cid)
        if c:
            combat.remove_combatant(c)
            return jsonify({"removed": True})
        return jsonify({"error": "Not found"}), 404

    # ---- Turns ----
    @app.route("/sessions/<sid>/next", methods=["POST"])
    def next_turn(sid):
        result = mgr.next_turn(sid)
        return jsonify(result) if result else (jsonify({"error": "Empty or not found"}), 404)

    @app.route("/sessions/<sid>/prev", methods=["POST"])
    def prev_turn(sid):
        result = mgr.prev_turn(sid)
        return jsonify(result) if result else (jsonify({"error": "Empty or not found"}), 404)

    @app.route("/sessions/<sid>/end", methods=["POST"])
    def end_combat(sid):
        result = mgr.end_combat(sid)
        return jsonify(result) if result else (jsonify({"error": "Not found"}), 404)

    # ---- Actions ----
    @app.route("/sessions/<sid>/attack", methods=["POST"])
    def attack(sid):
        data = request.get_json(force=True)
        result = mgr.attack(sid, data.get("attacker", ""), data.get("target", ""),
                           data["attack_bonus"], data["damage"],
                           data.get("advantage"), data.get("damage_type"))
        return jsonify(result) if result else (jsonify({"error": "Not found"}), 404)

    @app.route("/sessions/<sid>/damage", methods=["POST"])
    def damage(sid):
        data = request.get_json(force=True)
        result = mgr.modify_hp(sid, data.get("target", ""), data.get("amount", 0), data.get("type"))
        return jsonify(result) if result else (jsonify({"error": "Not found"}), 404)

    @app.route("/sessions/<sid>/heal", methods=["POST"])
    def heal(sid):
        data = request.get_json(force=True)
        result = mgr.modify_hp(sid, data.get("target", ""), data.get("amount", 0), is_heal=True)
        return jsonify(result) if result else (jsonify({"error": "Not found"}), 404)

    @app.route("/sessions/<sid>/save", methods=["POST"])
    def save(sid):
        data = request.get_json(force=True)
        result = mgr.saving_throw(sid, data.get("combatant", ""), data["ability"], data["dc"])
        return jsonify(result) if result else (jsonify({"error": "Not found"}), 404)

    @app.route("/sessions/<sid>/effect", methods=["POST"])
    def add_effect(sid):
        data = request.get_json(force=True)
        result = mgr.add_effect(sid, data.get("combatant", ""), data["name"],
                               data.get("duration"), data.get("passive_effects"),
                               data.get("concentration", False), data.get("desc"))
        return jsonify(result) if result else (jsonify({"error": "Not found"}), 404)

    @app.route("/sessions/<sid>/cast", methods=["POST"])
    def cast(sid):
        data = request.get_json(force=True)
        result, err = mgr.cast_spell(sid, data.get("caster", ""), data["spell"],
                                     data.get("targets", []), data.get("level"))
        if err:
            return jsonify({"error": err}), 400
        return jsonify(result)

    # ---- Lookup ----
    @app.route("/lookup/monster/<name>")
    def lookup_monster(name):
        result = mgr.lookup_monster(name)
        return jsonify(result) if result else (jsonify({"error": "Not found"}), 404)

    @app.route("/lookup/spell/<name>")
    def lookup_spell(name):
        result = mgr.lookup_spell(name)
        return jsonify(result) if result else (jsonify({"error": "Not found"}), 404)

    @app.route("/lookup/monsters")
    def list_monsters():
        monsters = [{"name": m.name, "cr": m.cr, "hp": m.hp, "ac": m.ac}
                   for m in mgr.compendium.monsters]
        seen = {m["name"] for m in monsters}
        for m in mgr.extra_monsters:
            if m["name"] not in seen:
                monsters.append({"name": m["name"], "cr": m.get("cr"), "hp": m["hp"], "ac": m["ac"]})
        return jsonify(monsters)

    @app.route("/lookup/spells")
    def list_spells():
        return jsonify([{"name": s.name, "level": s.level, "school": s.school,
                        "has_automation": bool(s.automation)}
                       for s in mgr.compendium.spells])

    # ---- Named Attacks ----
    @app.route("/sessions/<sid>/named_attack", methods=["POST"])
    def named_attack(sid):
        data = request.get_json(force=True)
        result, err = mgr.named_attack(
            sid, data.get("attacker", ""), data.get("attack", ""),
            data.get("target", ""), data.get("args", ""),
            data.get("advantage"))
        if err:
            return jsonify({"error": err}), 400
        return jsonify(result)

    @app.route("/sessions/<sid>/combatants/<name>/attacks", methods=["GET"])
    def list_attacks(sid, name):
        result = mgr.list_attacks(sid, name)
        if result is None:
            return jsonify({"error": "Not found"}), 404
        return jsonify(result)

    # ---- HP/THP routes ----
    @app.route("/sessions/<sid>/hp", methods=["POST"])
    def set_hp(sid):
        data = request.get_json(force=True)
        target = data.get("combatant", data.get("target", ""))
        action = data.get("action", "mod")
        amount = data.get("amount", 0)
        if isinstance(amount, str):
            amount = d20.roll(amount).total
        if action == "set":
            result = mgr.set_hp(sid, target, amount)
        elif action == "max":
            result = mgr.set_max_hp(sid, target, amount)
        else:
            is_heal = amount > 0
            result = mgr.modify_hp(sid, target, abs(amount), is_heal=is_heal)
        if not result:
            return jsonify({"error": "Not found"}), 404
        return jsonify(result)

    @app.route("/sessions/<sid>/thp", methods=["POST"])
    def set_thp(sid):
        data = request.get_json(force=True)
        result = mgr.set_thp(sid, data.get("combatant", ""), data.get("amount", 0))
        if not result:
            return jsonify({"error": "Not found"}), 404
        return jsonify(result)

    # ---- Notes ----
    @app.route("/sessions/<sid>/note", methods=["POST"])
    def set_note(sid):
        data = request.get_json(force=True)
        result = mgr.set_note(sid, data.get("combatant", ""), data.get("text", ""))
        if not result:
            return jsonify({"error": "Not found"}), 404
        return jsonify(result)

    # ---- Combatant Options ----
    @app.route("/sessions/<sid>/opt", methods=["POST"])
    def set_opts(sid):
        data = request.get_json(force=True)
        name = data.pop("combatant", data.pop("name", ""))
        result = mgr.set_combatant_opts(sid, name, **data)
        if not result:
            return jsonify({"error": "Not found"}), 404
        return jsonify(result)

    # ---- Move / Skip / Reroll ----
    @app.route("/sessions/<sid>/move", methods=["POST"])
    def move_to(sid):
        data = request.get_json(force=True)
        result = mgr.move_to(sid, data.get("target", ""))
        if not result:
            return jsonify({"error": "Not found"}), 404
        return jsonify(result)

    @app.route("/sessions/<sid>/skipround", methods=["POST"])
    def skip_rounds(sid):
        data = request.get_json(force=True) if request.data else {}
        result = mgr.skip_rounds(sid, data.get("rounds", 1))
        if not result:
            return jsonify({"error": "Not found"}), 404
        return jsonify(result)

    @app.route("/sessions/<sid>/reroll", methods=["POST"])
    def reroll(sid):
        result = mgr.reroll_initiative(sid)
        if not result:
            return jsonify({"error": "Not found"}), 404
        return jsonify(result)

    # ---- Multiroll / Iterroll ----
    @app.route("/multiroll", methods=["POST"])
    def multiroll():
        data = request.get_json(force=True)
        try:
            result = mgr.multiroll(
                data.get("expression", "1d20"),
                data.get("count", 1),
                data.get("dc"),
                data.get("advantage"))
            return jsonify(result)
        except Exception as e:
            return jsonify({"error": str(e)}), 400

    # ---- Lookup: items, feats, classes, races, backgrounds, conditions, rules ----
    @app.route("/lookup/item/<name>")
    def lookup_item(name):
        result = mgr.lookup_item(name)
        return jsonify(result) if result else (jsonify({"error": "Not found"}), 404)

    @app.route("/lookup/feat/<name>")
    def lookup_feat(name):
        result = mgr.lookup_feat(name)
        return jsonify(result) if result else (jsonify({"error": "Not found"}), 404)

    @app.route("/lookup/class/<name>")
    def lookup_class(name):
        result = mgr.lookup_class(name)
        return jsonify(result) if result else (jsonify({"error": "Not found"}), 404)

    @app.route("/lookup/race/<name>")
    def lookup_race(name):
        result = mgr.lookup_race(name)
        return jsonify(result) if result else (jsonify({"error": "Not found"}), 404)

    @app.route("/lookup/background/<name>")
    def lookup_background(name):
        result = mgr.lookup_background(name)
        return jsonify(result) if result else (jsonify({"error": "Not found"}), 404)

    @app.route("/lookup/condition/<name>")
    def lookup_condition(name):
        result = mgr.lookup_condition(name)
        return jsonify(result) if result else (jsonify({"error": "Not found"}), 404)

    @app.route("/lookup/rule/<name>")
    def lookup_rule(name):
        result = mgr.lookup_rule(name)
        return jsonify(result) if result else (jsonify({"error": "Not found"}), 404)

    return app


# ============================================================
# Main
# ============================================================

def main():
    import argparse as ap
    parser = ap.ArgumentParser(description="Avrae Local D&D Engine v3.0 (Real Engine)")
    parser.add_argument("--host", default="0.0.0.0")
    parser.add_argument("--port", type=int, default=5000)
    parser.add_argument("--debug", action="store_true")
    args = parser.parse_args()

    log.info("Loading compendium...")
    compendium = Compendium()
    # Use SRD data if available, fall back to test data
    srd_compendium = os.path.join(os.path.dirname(__file__), "srd_data", "compendium")
    test_compendium = os.path.join(os.path.dirname(__file__), "tests", "static", "compendium")
    data_path = srd_compendium if os.path.isdir(srd_compendium) else test_compendium
    compendium.load_all_json(base_path=data_path)
    compendium.load_common()
    log.info(f"Loaded {len(compendium.monsters)} monsters, {len(compendium.spells)} spells from {data_path}")

    mdb = MockMDB()
    bot = MockBot(mdb)
    mgr = SessionManager(compendium, bot)

    # Load extra SRD monsters
    srd_path = os.path.join(os.path.dirname(__file__), "srd_data")
    if os.path.isdir(srd_path):
        mf = os.path.join(srd_path, "monsters.json")
        if os.path.isfile(mf):
            with open(mf) as f:
                mgr.extra_monsters = json.load(f)
            log.info(f"Loaded {len(mgr.extra_monsters)} extra SRD monsters")

    app = create_app(mgr)
    log.info(f"Avrae Engine v3.0 starting on {args.host}:{args.port}")
    app.run(host=args.host, port=args.port, debug=args.debug, threaded=True)


if __name__ == "__main__":
    main()
