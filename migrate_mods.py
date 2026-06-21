#!/usr/bin/env python3
"""
Modrinth Mod Migrator for the Pandora Launcher
================================================

What this does
---------------
1. Asks you for the folder containing your installed mod .jar files
   (your Pandora instance's "mods" folder).
2. Asks which Minecraft version you're currently playing on, and which
   version you want to migrate to.
3. Identifies each installed mod by hashing the .jar file and looking
   it up on Modrinth (this works regardless of where you originally
   downloaded the jar from, as long as Modrinth hosts that exact file).
4. For every mod it recognizes, searches Modrinth for a build that
   matches your target Minecraft version and the same mod loader
   (Fabric/Forge/Quilt/NeoForge) as your current copy.
5. Downloads the matching files into a new "migrated_mods" folder
   (it never touches or deletes your existing mods folder) and writes
   a report of what worked and what needs your manual attention.

Requirements
------------
Python 3.8+. No third-party packages needed (uses only the standard
library), so you should be able to just run it directly:

    python3 migrate_mods.py        (macOS/Linux)
    py migrate_mods.py             (Windows)

Notes / limitations
--------------------
- Only mods that are hosted on Modrinth (i.e. Modrinth has the exact
  same .jar file) can be auto-identified. Mods that are CurseForge-only,
  or that you compiled/edited yourself, will be skipped and listed in
  the report.
- Modrinth doesn't always have a build for every Minecraft version.
  Anything without an exact match for your target version is also
  listed in the report instead of guessed.
- Resource packs, shader packs, etc. dropped into the mods folder
  (which Minecraft would ignore anyway) will simply fail to resolve
  and show up in the report.
"""

import hashlib
import json
import os
import platform
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

API_BASE = "https://api.modrinth.com/v2"
# Modrinth asks API consumers to identify themselves. Feel free to edit
# this if you fork the script.
USER_AGENT = "pandora-mod-migrator/1.0 (personal-use script; contact: none)"

REQUEST_DELAY = 0.15  # seconds between API calls, to be polite to Modrinth


# --------------------------------------------------------------------------
# Small HTTP helpers (stdlib only)
# --------------------------------------------------------------------------

def api_get(path_or_url, params=None):
    """GET a JSON endpoint from Modrinth, with basic retry on rate limiting."""
    if path_or_url.startswith("http"):
        url = path_or_url
    else:
        url = API_BASE + path_or_url
    if params:
        url += "?" + urllib.parse.urlencode(params)

    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})

    for attempt in range(4):
        try:
            with urllib.request.urlopen(req, timeout=20) as resp:
                data = resp.read()
                time.sleep(REQUEST_DELAY)
                return json.loads(data)
        except urllib.error.HTTPError as e:
            if e.code == 404:
                return None
            if e.code == 429:
                wait = 2 ** attempt
                print(f"  (rate limited, waiting {wait}s...)")
                time.sleep(wait)
                continue
            raise
        except urllib.error.URLError as e:
            if attempt == 3:
                raise
            time.sleep(1)
    return None


def download_file(url, dest_path, max_retries=3):
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    for attempt in range(max_retries):
        try:
            with urllib.request.urlopen(req, timeout=60) as resp:
                dest_path.parent.mkdir(parents=True, exist_ok=True)
                with open(dest_path, "wb") as f:
                    f.write(resp.read())
            return True
        except (urllib.error.HTTPError, urllib.error.URLError):
            if attempt == max_retries - 1:
                return False
            time.sleep(1)
    return False


# --------------------------------------------------------------------------
# Locating the mods folder
# --------------------------------------------------------------------------

def guess_pandora_base_dirs():
    """Best-effort guesses for where Pandora stores its instances.

    Pandora's exact on-disk layout isn't officially documented, so these
    are educated guesses based on common conventions for similar Rust/Tauri
    desktop apps. If none of these pan out, the script will just ask you
    to type/paste the path yourself.
    """
    home = Path.home()
    system = platform.system()
    candidates = []

    if system == "Windows":
        appdata = os.environ.get("APPDATA", str(home / "AppData" / "Roaming"))
        localappdata = os.environ.get("LOCALAPPDATA", str(home / "AppData" / "Local"))
        for base in (appdata, localappdata):
            candidates.append(Path(base) / "PandoraLauncher")
            candidates.append(Path(base) / "Pandora")
            candidates.append(Path(base) / "com.moulberry.pandora")
    elif system == "Darwin":
        support = home / "Library" / "Application Support"
        candidates.append(support / "PandoraLauncher")
        candidates.append(support / "Pandora")
        candidates.append(support / "com.moulberry.pandora")
    else:  # Linux and friends
        xdg_data = Path(os.environ.get("XDG_DATA_HOME", home / ".local" / "share"))
        xdg_config = Path(os.environ.get("XDG_CONFIG_HOME", home / ".config"))
        for base in (xdg_data, xdg_config):
            candidates.append(base / "PandoraLauncher")
            candidates.append(base / "pandora-launcher")
            candidates.append(base / "Pandora")

    return [c for c in candidates if c.exists()]


def find_instance_mod_folders(base_dirs):
    """Look for sub-folders named 'mods' a couple of levels deep."""
    found = []
    for base in base_dirs:
        try:
            for path in base.rglob("mods"):
                if path.is_dir():
                    # Use the parent folder name as a guess for the instance name
                    instance_name = path.parent.name
                    found.append((instance_name, path))
        except (PermissionError, OSError):
            continue
    return found


def prompt_for_mods_folder():
    print("Looking for Pandora instances on this machine...")
    base_dirs = guess_pandora_base_dirs()
    candidates = find_instance_mod_folders(base_dirs) if base_dirs else []

    if candidates:
        print("\nFound the following possible mods folders:")
        for i, (name, path) in enumerate(candidates, 1):
            print(f"  {i}. {name}  ->  {path}")
        print(f"  {len(candidates) + 1}. None of these / enter a path manually")

        choice = input(f"\nPick an option [1-{len(candidates) + 1}]: ").strip()
        if choice.isdigit() and 1 <= int(choice) <= len(candidates):
            return candidates[int(choice) - 1][1]
    else:
        print("Couldn't auto-detect Pandora's data folder on this system.")

    print(
        "\nPlease enter the full path to your instance's 'mods' folder.\n"
        "In Pandora, open the instance, look for an 'Open Folder' / "
        "'Open Instance Folder' option, then navigate into the 'mods' "
        "subfolder and copy that path."
    )
    while True:
        raw = input("Mods folder path: ").strip().strip('"').strip("'")
        path = Path(raw).expanduser()
        if path.is_dir():
            return path
        print(f"  '{path}' doesn't look like a valid folder. Try again.")


# --------------------------------------------------------------------------
# Modrinth lookups
# --------------------------------------------------------------------------

def sha1_of_file(path):
    h = hashlib.sha1()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 16), b""):
            h.update(chunk)
    return h.hexdigest()


def lookup_version_by_hash(file_hash):
    """Identify a mod jar via Modrinth's version-file-hash lookup."""
    return api_get(f"/version_file/{file_hash}", params={"algorithm": "sha1"})


def get_project_versions(project_id, loaders, game_version):
    params = {
        "loaders": json.dumps(loaders),
        "game_versions": json.dumps([game_version]),
    }
    result = api_get(f"/project/{project_id}/version", params=params)
    return result or []


def get_projects_meta(project_ids):
    """Batch-fetch project titles for nicer reporting."""
    if not project_ids:
        return {}
    result = api_get("/projects", params={"ids": json.dumps(list(project_ids))})
    if not result:
        return {}
    return {p["id"]: p.get("title", p["id"]) for p in result}


def pick_best_version(versions):
    if not versions:
        return None
    type_rank = {"release": 0, "beta": 1, "alpha": 2}
    versions_sorted = sorted(
        versions,
        key=lambda v: (type_rank.get(v.get("version_type"), 3), v.get("date_published", "")),
        reverse=False,
    )
    # Among the best version_type, pick the most recently published
    best_type = versions_sorted[0].get("version_type")
    same_type = [v for v in versions if v.get("version_type") == best_type]
    same_type.sort(key=lambda v: v.get("date_published", ""), reverse=True)
    return same_type[0]


def pick_primary_file(version):
    files = version.get("files", [])
    for f in files:
        if f.get("primary"):
            return f
    return files[0] if files else None


# --------------------------------------------------------------------------
# Main flow
# --------------------------------------------------------------------------

def main():
    print("=" * 70)
    print("  Pandora Launcher Mod Migrator  (via Modrinth)")
    print("=" * 70)

    mods_folder = prompt_for_mods_folder()
    print(f"\nUsing mods folder: {mods_folder}")

    current_version = input("\nWhich Minecraft version are you currently on? (e.g. 1.20.1): ").strip()
    target_version = input("Which Minecraft version do you want to migrate TO? (e.g. 1.21.1): ").strip()

    if not current_version or not target_version:
        print("Both versions are required. Exiting.")
        sys.exit(1)

    out_dir = input(
        "\nWhere should migrated mods be saved? "
        "[default: ./migrated_mods]: "
    ).strip()
    out_dir = Path(out_dir).expanduser() if out_dir else Path("migrated_mods")
    out_dir.mkdir(parents=True, exist_ok=True)

    jar_files = sorted(
        p for p in mods_folder.iterdir()
        if p.is_file() and p.suffix.lower() in (".jar",)
    )
    disabled_files = sorted(
        p for p in mods_folder.iterdir()
        if p.is_file() and p.name.lower().endswith(".jar.disabled")
    )

    if not jar_files and not disabled_files:
        print(f"\nNo .jar files found in {mods_folder}. Nothing to do.")
        sys.exit(0)

    if disabled_files:
        print(
            f"\nNote: {len(disabled_files)} disabled mod(s) found "
            f"(*.jar.disabled). These will be skipped — re-enable them in "
            f"Pandora first if you want them migrated."
        )

    print(f"\nFound {len(jar_files)} mod jar(s). Looking each one up on Modrinth...\n")

    migrated = []      # (original_name, project_title, new_filename)
    not_on_modrinth = []   # original_name
    no_target_version = [] # (original_name, project_title)
    failed_download = []   # (original_name, project_title)

    project_ids_seen = set()
    resolved_cache = {}  # sha1 -> version json, in case of duplicate jars

    for jar_path in jar_files:
        name = jar_path.name
        print(f"- {name}")

        file_hash = sha1_of_file(jar_path)
        version_info = resolved_cache.get(file_hash)
        if version_info is None:
            version_info = lookup_version_by_hash(file_hash)
            resolved_cache[file_hash] = version_info

        if not version_info:
            print("    not found on Modrinth (skipping)")
            not_on_modrinth.append(name)
            continue

        project_id = version_info["project_id"]
        loaders = version_info.get("loaders") or []
        project_ids_seen.add(project_id)

        candidates = get_project_versions(project_id, loaders, target_version)
        best = pick_best_version(candidates)

        if not best:
            print(f"    no build found for Minecraft {target_version}")
            no_target_version.append((name, project_id))
            continue

        file_entry = pick_primary_file(best)
        if not file_entry:
            print("    found a matching version but it has no downloadable file")
            failed_download.append((name, project_id))
            continue

        dest_path = out_dir / file_entry["filename"]
        print(f"    -> {best.get('version_number', '?')} for {target_version}: downloading...")
        ok = download_file(file_entry["url"], dest_path)
        if ok:
            migrated.append((name, project_id, file_entry["filename"]))
        else:
            print("    download failed")
            failed_download.append((name, project_id))

    # Resolve project titles for the report
    titles = get_projects_meta(project_ids_seen)

    # ---------------------------------------------------------------
    # Report
    # ---------------------------------------------------------------
    report_lines = []
    report_lines.append(f"Mod migration report: {current_version} -> {target_version}")
    report_lines.append(f"Source folder: {mods_folder}")
    report_lines.append(f"Output folder: {out_dir.resolve()}")
    report_lines.append("")

    report_lines.append(f"MIGRATED ({len(migrated)})")
    for original, proj_id, new_name in migrated:
        title = titles.get(proj_id, proj_id)
        report_lines.append(f"  [{title}] {original}  ->  {new_name}")
    report_lines.append("")

    report_lines.append(f"NO BUILD FOR {target_version} YET ({len(no_target_version)})")
    for original, proj_id in no_target_version:
        title = titles.get(proj_id, proj_id)
        report_lines.append(f"  [{title}] {original}")
    report_lines.append("")

    report_lines.append(f"NOT FOUND ON MODRINTH ({len(not_on_modrinth)})")
    for original in not_on_modrinth:
        report_lines.append(f"  {original}")
    report_lines.append("")

    if failed_download:
        report_lines.append(f"DOWNLOAD FAILED ({len(failed_download)})")
        for original, proj_id in failed_download:
            title = titles.get(proj_id, proj_id)
            report_lines.append(f"  [{title}] {original}")
        report_lines.append("")

    if disabled_files:
        report_lines.append(f"SKIPPED (disabled in Pandora) ({len(disabled_files)})")
        for p in disabled_files:
            report_lines.append(f"  {p.name}")
        report_lines.append("")

    report_text = "\n".join(report_lines)
    report_path = out_dir / "migration_report.txt"
    report_path.write_text(report_text, encoding="utf-8")

    print("\n" + "=" * 70)
    print(report_text)
    print("=" * 70)
    print(f"\nDownloaded files and this report are in: {out_dir.resolve()}")
    print(
        "Nothing in your original mods folder was changed. Review the "
        "report, then copy the new jars into your instance's mods folder "
        "(and remove the old versions) once you're happy with the results."
    )


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\nCancelled.")
        sys.exit(1)
