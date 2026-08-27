"""How much of the card set does the simulator actually implement?

Three different questions, deliberately kept apart, because the flattering
answer and the honest one differ by a lot:

    parsed     the card's numbers load into a spec
    buildable  it can be put on the board and does something
    raw-key scan  no known top-level field is missing from this limited scan

A card can parse perfectly and still be wrong on the board. The Prince parsed
fine for months while the engine had no charge, so it was a slow Knight.

    python -m sim.coverage
"""

from __future__ import annotations

import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
for path in (str(ROOT), str(ROOT / "scripts")):
    if path not in sys.path:
        sys.path.insert(0, path)

# Raw keys whose behaviour the engine does not implement. Charge, shields,
# splash and projectiles are absent on purpose - those are modelled.
# Behaviour keys only. SpawnDeployBaseAnim used to be listed here and flagged
# the Battle Ram, which is fully modelled - it names a deploy *animation*, not
# a mechanic. An audit that counts cosmetic keys as gaps reports work that does
# not exist, which is the same failure as missing work that does.
UNMODELLED = {
    "VisibilityRange": "invisible until it strikes",
    "HealPerSecond": "heals nearby friendlies",
    "AbilityData": "champion ability on a button",
}

# Implemented, and listed so the report cannot quietly take credit twice or
# lose track of what was done. Each was a family, not a card: charge covers
# every Prince and Ram, death spawn covers every Golem and Barrel.
MODELLED = (
    "charge and its special hit", "dashes and their invulnerability",
    "shields", "splash", "projectile flight",
    "death damage", "death spawns", "periodic spawners",
    "timed buffs (freeze, slow, rage)", "kamikaze units", "lifetimes",
    "knockback and IgnorePushback", "burrowing and untargetability in transit",
    "sight-limited aggro", "solid buildings", "tower windup",
    "spell launch/impact timing and prediction", "multi-wave spells",
    "rolling and capture spells", "explicit evolution cycles",
    "on-hit evolution buffs and duplication", "shield-loss effects",
    "kill-triggered healing and overheal", "starting companion summons",
)

def report() -> dict:
    from sim.gamedata import load_gamedata
    from sim.spells import QUARANTINED_INTERNAL_SPELLS, load_spells

    cards = load_gamedata(level=11)
    spells = load_spells(level=11)

    # Some player actions are represented by a disposable client building
    # (Rage bottle, Royal Delivery) but resolve as spells in Match. Classify by
    # the actual resolver instead of by whether the raw card happened to carry
    # a unit row.
    resolves_as_spell = {
        name for name in cards
        if name in spells and (cards[name].unit is None
                               or spells[name].resolves_card_as_spell)
    }
    units = {n: c for n, c in cards.items()
             if (c.unit is not None or c.additional_summons)
             and n not in resolves_as_spell}
    spell_cards = {n: c for n, c in cards.items()
                   if (c.unit is None and not c.additional_summons)
                   or n in resolves_as_spell}
    resolvable = {n for n in spell_cards if n in spells}
    intentional_non_resolvers = {
        n for n in spell_cards
        if n == "mirror" or n in QUARANTINED_INTERNAL_SPELLS
    }
    unresolved_spells = set(spell_cards) - resolvable - intentional_non_resolvers

    unfaithful = {}
    for name, card in units.items():
        reasons = []
        unit_specs = ([card.unit] if card.unit is not None else []) + [
            spec for spec, _count, _delay in card.additional_summons]
        for unit_spec in unit_specs:
            raw = unit_spec.raw
            for key, why in UNMODELLED.items():
                value = raw.get(key)
                if value in (None, 0, "", False):
                    continue
                if key == "SpawnNumber" and int(value or 1) <= 1:
                    continue
                reasons.append(why)
        if reasons:
            unfaithful[name] = sorted(set(reasons))

    return {
        "parsed": len(cards),
        "units": len(units),
        "spell_cards": len(spell_cards),
        "spells_resolvable": sorted(resolvable),
        "spell_rows_intentionally_excluded": sorted(intentional_non_resolvers),
        "spells_unresolved": sorted(unresolved_spells),
        "unfaithful": unfaithful,
    }


def main() -> int:
    data = report()
    units, unfaithful = data["units"], data["unfaithful"]
    print(f"cards parsed:              {data['parsed']}")
    print(f"  deployable units:        {units}")
    print(f"  spell cards:             {data['spell_cards']}")
    print(f"    the sim can resolve:   {len(data['spells_resolvable'])} "
          f"{data['spells_resolvable']}")
    print("    intentional non-resolvers: "
          f"{data['spell_rows_intentionally_excluded']}")
    print(f"    unresolved public spells: {data['spells_unresolved']}")
    print()
    print(f"units with a known top-level raw-field gap: {len(unfaithful)}")
    for reason, count in Counter(r for rs in unfaithful.values()
                                 for r in rs).most_common():
        print(f"   {count:3d}  {reason}")
    print()
    print(f"units clear in this limited raw-field scan: {units - len(unfaithful)}/{units}")
    print("This is not a fidelity percentage: client ACTION/AEO graphs can add")
    print("behaviour that does not appear as a top-level unit field. Run")
    print("`python -m sim.action_audit` before treating the catalogue as complete.")
    print()
    print("mechanic families implemented:")
    for family in MODELLED:
        print(f"   {family}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
