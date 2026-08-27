You are producing a machine-readable Clash Royale unit-properties table for a Hog 2.6 bot.

CRITICAL: Your training data about Clash Royale is likely outdated. Use web search to verify
current (2026) card stats before writing each entry. In particular verify elixir costs,
hitpoints, and whether Fireball / The Log kill the card at tournament standard (level 11)
or at equal level.

Write the result to this exact file path, and nothing else:
  C:\Users\aksha\Downloads\HastyCR\scripts\brain\units.json

Format: a single JSON object mapping unit name -> properties object. Use EXACTLY these unit
name keys (they come from the bot's detector and must not be renamed, invented, or omitted):

archer, archer_queen, baby_dragon, balloon, bandit, barbarian, barbarian_hut, bat,
battle_healer, battle_ram, bomb_tower, bomber, bowler, brawler, cannon, cannon_cart,
dark_prince, dart_goblin, electro_dragon, electro_giant, electro_spirit, electro_wizard,
elite_barbarian, elixir_collector, elixir_golem_large, elixir_golem_medium,
elixir_golem_small, executioner, fire_spirit, firecracker, fisherman, flying_machine,
furnace, giant, giant_skeleton, giant_snowball, goblin, goblin_cage, goblin_drill,
goblin_hut, golden_knight, golem, golemite, guard, heal_spirit, hog, hog_rider, hunter,
ice_golem, ice_spirit, ice_wizard, inferno_dragon, inferno_tower, knight, lava_hound,
lava_pup, little_prince, lumberjack, magic_archer, mega_knight, mega_minion, mighty_miner,
miner, minion, minipekka, monk, mortar, mother_witch, musketeer, night_witch, pekka,
phoenix_egg, phoenix_large, phoenix_small, prince, princess, ram_rider, rascal_boy,
rascal_girl, royal_ghost, royal_giant, royal_guardian, royal_hog, royal_recruit, skeleton,
skeleton_dragon, skeleton_king, sparky, spear_goblin, tesla, tombstone, valkyrie,
wall_breaker, witch, wizard, x_bow, zappy

Each value must be an object with EXACTLY these keys:

  "cost":          integer elixir cost of the card that spawns it (best estimate; 0 for
                   spawned-only units such as golemite, lava_pup, skeleton, phoenix_egg)
  "air":           true if the unit itself flies
  "hits_air":      true if it can attack air units
  "ranged":        true if it attacks at range (not melee)
  "building":      true if it is a building (cannon, tesla, tombstone, x_bow, ...)
  "win_con":       true if it is a win condition that ignores troops and runs at buildings
                   or towers (hog_rider, royal_giant, giant, golem, balloon, ram_rider,
                   battle_ram, wall_breaker, goblin_drill, miner, x_bow, mortar, royal_hog,
                   electro_giant, lava_hound, elixir_golem_*, giant_skeleton)
  "tank":          true if it is a high-hitpoint unit meant to soak damage
                   (giant, golem, pekka, mega_knight, lava_hound, electro_giant,
                    royal_giant, giant_skeleton, elixir_golem_large, ice_golem, knight,
                    valkyrie, ...)
  "swarm":         true if the card deploys 3 or more units, or the unit is a low-hitpoint
                   swarm member (skeleton, bat, goblin, spear_goblin, minion, ...)
  "threat":        integer 0-10, how dangerous this unit is to a 2.6 player's tower if it
                   is left completely unanswered. 0 = harmless (elixir_collector),
                   10 = will take a tower alone (pekka, mega_knight, royal_giant, balloon,
                   sparky, golem).
  "dies_to_log":   true if The Log alone kills it at equal level
  "dies_to_fireball": true if Fireball alone kills it at equal level
  "melee_kitable": true if it is a ground melee unit that will change target and chase an
                   Ice Golem placed across the arena (this is the key 2.6 kiting property).
                   False for ranged units, air units, and buildings-only-targeting units
                   such as hog_rider, royal_giant, balloon, battle_ram, ram_rider.

Rules:
- Output ONLY valid JSON in that file. No markdown fences, no commentary, no trailing commas.
- Every one of the listed names must be present. Do not add names that are not listed.
- Prefer being conservative on "dies_to_fireball" / "dies_to_log": only true when you
  verified it, otherwise false.
- Do not modify any other file in the repository.

When you are done, print a one-line summary: UNITS_TABLE_DONE <number of keys written>
