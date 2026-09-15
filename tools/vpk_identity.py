"""Identify each VPK: which hero it replaces (vmdl path + panorama codename),
what it likely is (from texture names), and cross-ref GameBanana titles."""
import json
import os
import re

import vpk

OUT = os.path.join(os.environ["LOCALAPPDATA"], "Temp", "awa3d-vpks")

# Deadlock internal hero codenames — GROUND TRUTH from the game's own
# localization file (resource/localization/citadel_gc_hero_names/
# citadel_gc_hero_names_english.txt, loose files next to the VPKs).
# Model-dir names can differ from loc tokens (e.g. Pocket's model dir is
# "pocket", loc token "synth"); both are kept.
CODENAMES = {
    "atlas": "Abrams", 
    "bebop": "Bebop",
    "nano": "Calico",
    "yamato": "Yamato",
    "ghost": "Lady Geist",
    "doorman": "The Doorman",
    "magician": "Sinclair",
    "fencer": "Apollo",
    "tengu": "Ivy",
    "orion": "Grey Talon",
    "synth": "Pocket",
    "viper": "Vyper",
    "unicorn": "Celeste",
    "sumo": "Dynamo",
    "chrono": "Paradox",
    "hornet": "Vindicta",
    "inferno": "Infernus",
    "lash": "Lash",
    "kelvin": "Kelvin",
    "mirage": "Mirage",
    "bookworm": "Paige",
    "shiv": "Shiv",
    "haze": "Haze",
    "astro": "Holliday",
    "trapper": "Trapper",
    "wraith": "Wraith",
    "gigawatt": "Seven",
    "slork": "Fathom",
    "krill": "Mo & Krill",
    "priest": "Venator",
    "vampirebat": "Mina",
    "frank": "Victor",
    "drifter": "Drifter",
    "operative": "Raven",
    "yakuza": "The Boss",
    "punkgoat": "Billy",
    "wrecker": "Wrecker",
    "kali": "Kali",
    "warden": "Warden",
    "forge": "McGinnis",
    "werewolf": "Silver",
    "familiar": "Rem",
    "necro": "Graves",
    "graf": "Graf",
    "viscous": "Viscous",
    "cadence": "Cadence",
    # unreleased/internal slots kept as-is (unknown heroes)
    "archer": "archer (unreleased slot)",
    "moth": "moth (unreleased slot)",
    "hijack": "Hijack",
    "mechaguy": "Mecha Guy",
    "tempest": "Tempest",
    "ballista": "Ballista",
    "akimbo": "Akimbo",
    "skymonk": "Sky Monk",
    "gunslinger": "Gunslinger",
    "spade": "Spade",
    "apocalypse": "Apocalypse",
    "architect": "Architect",
    "clawdril": "Clawdril",
    "coldmetal": "Cold Metal",
    "slingshot": "Slingshot",
    "tokamak": "Tokamak",
    "rutger": "Rutger",
    "bomber": "Bomber",
    "shieldguy": "Shield Guy",
    "vandal": "Vandal",
    "opera": "Opera",
    "swan": "Swan",
    "skyrunner": "Skyrunner",
    "druid": "Druid",
    "fortuna": "Fortuna",
    "phalanx": "Phalanx",
    "revenant": "Revenant",
    "glider": "Glider",
    "sapper": "Sapper",
    "gunner": "Gunner",
    "cowboy": "Cowboy",
    "phoenix": "Phoenix",
    "gadgetman": "Gadget Man",
    "assassin": "Assassin",
    "duo": "Duo",
}


def heroes_in(entries):
    """Hero dirs referenced (replaced hero) — vmdl paths carry the target."""
    found = set()
    for e in entries:
        m = re.search(r"heroes(?:_wip)?[/\\]([a-z_0-9]+)", e)
        if m:
            found.add(m.group(1))
    return sorted(found)


def analyze(path):
    p = vpk.open(path)
    ents = list(p)
    hero_dirs = heroes_in(ents)
    vmdls = [e for e in ents if e.endswith(".vmdl_c")]
    # texture hints — the identity of the skin (source character)
    tex_hints = sorted({
        os.path.basename(e).split("_base")[0].split("_normal")[0].split("_vmat")[0]
        for e in ents
        if ".vtex_c" in e and ("basecolor" in e or "base_color" in e)
    })[:8]
    # panorama card psds = hero whose portrait changes
    cards = sorted({
        m.group(1)
        for m in (re.search(r"heroes[/\\]([a-z_0-9]+)_card", e) for e in ents)
        if m
    })
    return {
        "file": os.path.basename(path),
        "n_entries": len(ents),
        "hero_dirs": hero_dirs,
        "heroes": [CODENAMES.get(h, h) for h in hero_dirs],
        "cards": [CODENAMES.get(c, c) for c in cards],
        "vmdl": [v.rsplit("/", 1)[-1].rsplit("\\", 1)[-1] for v in vmdls][:3],
        "tex_hints": tex_hints,
    }


if __name__ == "__main__":
    targets = json.load(open(os.path.join(os.path.dirname(__file__), "vpk_targets.json")))
    rows = []
    for fname in targets:
        path = os.path.join(OUT, fname)
        if os.path.exists(path) and open(path, "rb").read(4) == b"\x34\x12\xaa\x55":
            rows.append(analyze(path))
        else:
            rows.append({"file": fname, "missing": True})
    outp = os.path.join(OUT, "identity.json")
    json.dump(rows, open(outp, "w"), indent=1)
    for r in rows:
        if r.get("missing"):
            print(f"{r['file']:42} MISSING")
            continue
        hs = ", ".join(r["heroes"]) or "-"
        th = ", ".join(r["tex_hints"])[:60] or "-"
        print(f"{r['file']:42} hero: {hs:22} tex: {th}")
    print("->", outp)
