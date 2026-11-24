"""Engine unit name -> the unit name the model has a token for (2026-11-15).

The live reader (scripts/gamestate/live_bridge.py: UNIT_ALIASES, _fallback_unit) maps
bodies whose exact name RoyaleSim's unit list lacks to a known unit; realsim did so
only for the Hero Ice Wizard. So in every engine-collected row these were not in the
model's input at all, while live showed them: Goblin Barrel's goblins (BarrelGoblin),
the evolved Witch's skeletons, the evolved Giant, Electro Giant and Goblin Giant's
spear goblins, Hero Electro Wizard, the Berserker hero's bear form, the Tombstone
hero's skeletons. Found by comparing card_battery.py unit names with the vocabulary.

Same rules as the live reader, kept equal by tools/league/controls/unitmap_check.py.
realsim uses it when HASTY_UNIT_FALLBACK=1; rows made with and without it differ.
"""
ALIASES = {"BerserkerHero_BearForm": "BerserkerHero", "TombstoneHeroSkeleton": "Skeleton",
           "BarrelGoblin": "Goblin", "GoblinCurseGoblin": "Goblin", "IceWizardHero": "IceWizard",
           "IceWizardHero_IceCube": "IceWizard", "IceWizardHeroFloatingCube": "IceWizard"}


def resolve(name, ut_index):
    """Index in `ut_index` (name -> index) for an engine body, or -1."""
    if name in ut_index:
        return ut_index[name]
    a = ALIASES.get(name)
    if a in ut_index:
        return ut_index[a]
    if not name or any(k in name.lower() for k in ("projectile", "container", "dummy")):
        return -1
    for part in reversed(name.split("_")):
        for cand in (part, *(part[:-len(suf)] for suf in ("EvoGhost", "Hero", "EV1", "EV2")
                             if part.endswith(suf) and len(part) > len(suf))):
            if cand in ut_index:
                return ut_index[cand]
    return -1
