# Mechanics rules the champion profiles use (reviewer-corrected 2026-11-19)

These are game-wide rules. A champion profile only tags its abilities; the coach combines the tags with these rules,
so a rule written once works for every champion. Source of truth for any single ability: Riot's own ability text
(in each champion file's `description`). When the text and these rules disagree, the text wins and the rule needs fixing.

## Crowd control types
| Type | Stops | Reduced by tenacity? | Removed by Cleanse / QSS? | Counts as immobilizing (Fiora W stuns)? |
|---|---|---|---|---|
| Stun | moving, attacking, casting | yes | yes / yes | yes |
| Root | moving (and dashing); can attack and cast | yes | yes / yes | yes |
| Airborne (knock-up, knock-back, pull, knock-aside) | everything, moves you | **no** (only its slow part, if any) | **no** / **no** | yes |
| Suppression | everything | **no** | no / yes | yes |
| Charm, fear/flee, taunt, sleep, berserk | control (walk to/away, attack) | yes | yes / yes | yes (charm, fear, taunt, sleep) |
| Silence | casting abilities (can still attack and walk) | yes | yes / yes | **no** (→ Fiora W slows instead) |
| Slow | move speed | yes | yes / yes | no |
| Blind | basic attacks miss (on-hit effects too) | yes | yes / yes | no |
| Disarm | basic attacks | yes | yes / yes | no |
| Grounded | dashes and blinks | yes | yes / yes | no |
| Polymorph | attacking, casting | yes | yes / yes | yes |

Tenacity (Garen W, Mercury's Treads, Legend: Tenacity...) shortens tenacity-affected crowd control only. Example
(reviewer): Darius E pulls and knocks up, so Garen W's tenacity only shortens the slow after it.

## Answers (abilities that beat other abilities)
| Answer | What it does | Example |
|---|---|---|
| **Parry** (Fiora W) | Blocks **all** incoming damage, disables and negative effects for 0.75 s, abilities included (e.g. Garen R's damage, Garen Q's damage and silence). If it blocked an immobilizing effect, her stab stuns 2 s; otherwise it slows. | Renekton W into Fiora W: blocked and Renekton is stunned. Garen Q while she's already parrying: blocked, Garen slowed. |
| **Dodge** (Jax E) | Dodges basic attacks and anything that is an attack (empowered next-attack abilities, on-hit effects); takes reduced area damage. | Garen Q, Darius W, Renekton W, Fiora E attacks: all dodged while Jax E is up. |
| **Spell shield** (Sivir E, Nocturne W, Banshee's Veil, Edge of Night) | Blocks the next enemy ability. Basic attacks go through. | A key crowd control into a spell shield is wasted. |
| **Projectile block / destroy** (Yasuo W, Braum E, Samira W) | Blocks or destroys missiles (most skillshots, ranged autos). | A skillshot into Yasuo W is wasted. |
| **Untargetable** (Vladimir W, Fizz E, Maokai? (check), Elise E in spider form...) | Point-and-click abilities can't target them; most damage misses. | Wait out the untargetable window. |
| **Unstoppable** (Malphite R, Olaf R, Sion R...) | Immune to crowd control (damage still applies). | Don't throw crowd control into it. |
| **Silence** | Stops them casting their answer (if they haven't already). | Garen Q before Fiora W. If the parry is already up, it's blocked. |
| **Grounded / root** | Stops their dash or escape. | Root before a dash champion uses it. |

Order matters: an answer only works if it's already active (or cast in reaction) when the ability lands; a silence only
works before the answer is cast.

## Windows
- An opponent's **key ability on cooldown** is the trade window. Cooldowns per rank are in the files; ability haste
  shortens them (cooldown × 100 / (100 + haste)).
- **Level curve matters more than "early/late":** some champions want all three basic abilities before they trade
  (reviewer: Renekton is an early-game champion but usually wants level 3, since his kit revolves around all three
  abilities and Fury is hard to build at level 1; Jax's level 1 is strong because of his passive and E). Each profile
  states its level 1 / 2 / 3 / 6 strength and when it wants to start trading.
