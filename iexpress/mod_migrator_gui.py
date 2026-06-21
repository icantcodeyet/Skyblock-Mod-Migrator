#!/usr/bin/env python3
"""
Mod Migrator — GUI edition
===========================

A desktop GUI (Tkinter, no extra dependencies) for migrating your Minecraft
mods to a new Minecraft version using Modrinth. Works with several popular
launchers — Prism Launcher, MultiMC, the Modrinth App, Pandora, ATLauncher,
GDLauncher, CurseForge, Technic, and a plain `.minecraft` — or any launcher
at all via the Browse button.

1. Pick the folder containing your installed mod .jar files. Click
   Auto-detect to scan your installed launchers, or Browse to point at any
   instance's "mods" folder manually.
2. Choose the Minecraft version you're currently on and the one you want to
   migrate to, from dropdowns populated live from Modrinth (you can also
   type a version if you prefer, or if the list can't be fetched).
3. Each mod is identified by hashing its .jar and looking it up on
   Modrinth (works regardless of where you originally downloaded it,
   as long as Modrinth hosts that exact file).
4. For every mod it recognizes, it searches Modrinth for a build that
   matches your target Minecraft version and the same mod loader
   (Fabric/Forge/Quilt/NeoForge) as your current copy.
5. Before keeping any downloaded file, it verifies it's legitimate:
   - the download URL must point at Modrinth's real CDN
     (cdn.modrinth.com) over HTTPS - anything else is refused.
   - the downloaded bytes must hash (sha512/sha1) to exactly what
     Modrinth's API said the file should be - anything that doesn't
     match is deleted immediately rather than kept.
6. Downloads the verified files into your chosen output folder (it
   never touches or deletes your existing mods folder) and writes a
   report of what worked and what needs your manual attention.

Requirements to run from source: Python 3.8+ with Tk support (this
ships with the standard python.org installers for Windows/macOS; on
Linux you may need to `sudo apt install python3-tk` or your distro's
equivalent). No other third-party packages are needed.
"""

import hashlib
import json
import os
import platform
import queue
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

import tkinter as tk
from tkinter import ttk, filedialog, messagebox

APP_NAME = "Mod Migrator"

API_BASE = "https://api.modrinth.com/v2"
USER_AGENT = "pandora-mod-migrator-gui/1.0 (personal-use desktop app; contact: none)"
REQUEST_DELAY = 0.15  # seconds between API calls, to be polite to Modrinth

# Security: only ever download from Modrinth's real CDN, and only ever
# trust a downloaded file if its hash matches what Modrinth's API said it
# should be. See README for details.
TRUSTED_DOWNLOAD_HOSTS = {"cdn.modrinth.com"}


# ==========================================================================
# Core logic (no UI code below this point until the GUI section) - this is
# the same engine used by the command-line version of this tool.
# ==========================================================================

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
                time.sleep(2 ** attempt)
                continue
            raise
        except urllib.error.URLError:
            if attempt == 3:
                raise
            time.sleep(1)
    return None


def hash_file(path, algorithm):
    h = hashlib.new(algorithm)
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 16), b""):
            h.update(chunk)
    return h.hexdigest()


def sha1_of_file(path):
    return hash_file(path, "sha1")


def is_trusted_download_url(url):
    """Only allow downloads from Modrinth's actual file CDN, over HTTPS."""
    try:
        parsed = urllib.parse.urlparse(url)
    except ValueError:
        return False
    return parsed.scheme == "https" and parsed.hostname in TRUSTED_DOWNLOAD_HOSTS


def download_and_verify(url, dest_path, expected_hashes, max_retries=3):
    """Download a file and confirm it's legitimate before keeping it.

    Returns a (status, detail) tuple where status is one of:
      "ok", "untrusted_host", "hash_mismatch", "network_error"
    """
    if not is_trusted_download_url(url):
        host = urllib.parse.urlparse(url).hostname
        return "untrusted_host", host or url

    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    last_error = None
    for attempt in range(max_retries):
        try:
            with urllib.request.urlopen(req, timeout=60) as resp:
                dest_path.parent.mkdir(parents=True, exist_ok=True)
                with open(dest_path, "wb") as f:
                    f.write(resp.read())
            break
        except (urllib.error.HTTPError, urllib.error.URLError) as e:
            last_error = e
            if attempt == max_retries - 1:
                return "network_error", str(last_error)
            time.sleep(1)

    for algorithm in ("sha512", "sha1"):
        expected = expected_hashes.get(algorithm)
        if not expected:
            continue
        actual = hash_file(dest_path, algorithm)
        if actual.lower() != expected.lower():
            dest_path.unlink(missing_ok=True)
            return "hash_mismatch", algorithm
        return "ok", algorithm

    dest_path.unlink(missing_ok=True)
    return "hash_mismatch", "no hashes provided by API"


def lookup_version_by_hash(file_hash):
    return api_get(f"/version_file/{file_hash}", params={"algorithm": "sha1"})


def response_matches_queried_hash(version_info, queried_sha1):
    for f in version_info.get("files", []):
        if f.get("hashes", {}).get("sha1", "").lower() == queried_sha1.lower():
            return True
    return False


def get_project_versions(project_id, loaders, game_version):
    params = {
        "loaders": json.dumps(loaders),
        "game_versions": json.dumps([game_version]),
    }
    result = api_get(f"/project/{project_id}/version", params=params)
    return result or []


def get_projects_meta(project_ids):
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
    best_type = sorted(
        versions, key=lambda v: type_rank.get(v.get("version_type"), 3)
    )[0].get("version_type")
    same_type = [v for v in versions if v.get("version_type") == best_type]
    same_type.sort(key=lambda v: v.get("date_published", ""), reverse=True)
    return same_type[0]


def pick_primary_file(version):
    files = version.get("files", [])
    for f in files:
        if f.get("primary"):
            return f
    return files[0] if files else None


def _platform_base_dirs():
    """Return the OS-appropriate base directories where launchers tend to
    live, as a dict so each launcher entry can pick the ones it needs."""
    home = Path.home()
    system = platform.system()
    if system == "Windows":
        appdata = Path(os.environ.get("APPDATA", home / "AppData" / "Roaming"))
        localappdata = Path(os.environ.get("LOCALAPPDATA", home / "AppData" / "Local"))
        return {
            "system": system,
            "appdata": appdata,
            "localappdata": localappdata,
            "home": home,
            "documents": home / "Documents",
        }
    if system == "Darwin":
        return {
            "system": system,
            "support": home / "Library" / "Application Support",
            "home": home,
        }
    # Linux / other
    xdg_data = Path(os.environ.get("XDG_DATA_HOME", home / ".local" / "share"))
    xdg_config = Path(os.environ.get("XDG_CONFIG_HOME", home / ".config"))
    return {
        "system": system,
        "xdg_data": xdg_data,
        "xdg_config": xdg_config,
        "home": home,
    }


def launcher_registry():
    """A list of known launchers and where to find their instance roots.

    Each entry yields the directories that *contain* per-instance folders.
    From each instance folder, mods live either directly in `mods/` or one
    level down in `.minecraft/mods` or `minecraft/mods` (handled later by
    find_mod_folders). Folders that don't exist on this machine are simply
    skipped, so listing many launchers here is harmless.
    """
    b = _platform_base_dirs()
    system = b["system"]
    reg = []  # (launcher_name, [instance_root_dirs])

    def w(base_key, *sub):
        """Helper: build a path from a base key + sub-parts, if base exists."""
        base = b.get(base_key)
        if base is None:
            return None
        p = base
        for s in sub:
            p = p / s
        return p

    if system == "Windows":
        reg.append(("Prism Launcher", [w("appdata", "PrismLauncher", "instances")]))
        reg.append(("MultiMC", [w("home", "MultiMC", "instances")]))
        reg.append(("Modrinth App", [
            w("appdata", "ModrinthApp", "profiles"),
            w("appdata", "com.modrinth.theseus", "profiles"),  # older versions
        ]))
        reg.append(("Pandora", [
            w("appdata", "PandoraLauncher", "instances"),
            w("appdata", "Pandora", "instances"),
            w("localappdata", "PandoraLauncher", "instances"),
        ]))
        reg.append(("ATLauncher", [w("appdata", "ATLauncher", "instances")]))
        reg.append(("GDLauncher", [w("appdata", "gdlauncher_next", "instances")]))
        reg.append(("CurseForge", [w("documents", "curseforge", "minecraft", "Instances")]))
        reg.append(("Technic", [w("appdata", ".technic", "modpacks")]))
        reg.append(("Vanilla (.minecraft)", [w("appdata", ".minecraft")]))
    elif system == "Darwin":
        reg.append(("Prism Launcher", [w("support", "PrismLauncher", "instances")]))
        reg.append(("MultiMC", [w("support", "MultiMC", "instances")]))
        reg.append(("Modrinth App", [
            w("support", "ModrinthApp", "profiles"),
            w("support", "com.modrinth.theseus", "profiles"),
        ]))
        reg.append(("Pandora", [
            w("support", "PandoraLauncher", "instances"),
            w("support", "Pandora", "instances"),
        ]))
        reg.append(("ATLauncher", [w("support", "ATLauncher", "instances")]))
        reg.append(("Technic", [w("support", "technic", "modpacks")]))
        reg.append(("Vanilla (minecraft)", [w("support", "minecraft")]))
    else:  # Linux
        reg.append(("Prism Launcher", [
            w("xdg_data", "PrismLauncher", "instances"),
            w("home", ".var", "app", "org.prismlauncher.PrismLauncher",
              "data", "PrismLauncher", "instances"),  # Flatpak
        ]))
        reg.append(("MultiMC", [w("home", ".local", "share", "multimc", "instances")]))
        reg.append(("Modrinth App", [
            w("xdg_data", "ModrinthApp", "profiles"),
            w("xdg_config", "com.modrinth.theseus", "profiles"),
            w("xdg_data", "com.modrinth.theseus", "profiles"),
        ]))
        reg.append(("Pandora", [
            w("xdg_data", "PandoraLauncher", "instances"),
            w("xdg_data", "pandora-launcher", "instances"),
            w("xdg_config", "PandoraLauncher", "instances"),
        ]))
        reg.append(("ATLauncher", [w("home", ".local", "share", "ATLauncher", "instances")]))
        reg.append(("Vanilla (.minecraft)", [w("home", ".minecraft")]))

    # Filter out None entries and keep only existing roots
    cleaned = []
    for name, roots in reg:
        existing = [r for r in roots if r is not None and r.exists()]
        if existing:
            cleaned.append((name, existing))
    return cleaned


def find_mod_folders():
    """Scan all known launchers and return a list of
    (launcher_name, instance_name, mods_path) for every mods folder found.

    A 'mods' folder is recognized either directly inside an instance folder
    or under that instance's '.minecraft' / 'minecraft' subfolder (which is
    how Prism, MultiMC, ATLauncher and similar lay things out).
    """
    results = []
    for launcher_name, roots in launcher_registry():
        for root in roots:
            # Case 1: the root itself is a .minecraft-style folder with mods
            direct = root / "mods"
            if direct.is_dir():
                results.append((launcher_name, root.name, direct))

            # Case 2: root contains per-instance subfolders
            try:
                instance_dirs = [p for p in root.iterdir() if p.is_dir()]
            except (PermissionError, OSError):
                instance_dirs = []

            for inst in instance_dirs:
                for candidate in (
                    inst / "mods",
                    inst / ".minecraft" / "mods",
                    inst / "minecraft" / "mods",
                ):
                    if candidate.is_dir():
                        results.append((launcher_name, inst.name, candidate))
                        break

    # De-duplicate while preserving order (same path can match twice)
    seen = set()
    unique = []
    for entry in results:
        key = str(entry[2])
        if key not in seen:
            seen.add(key)
            unique.append(entry)
    return unique


# ---- Minecraft version list (for the dropdowns) ----------------------

def fetch_minecraft_versions(releases_only=True):
    """Fetch the list of Minecraft versions from Modrinth, newest first.

    Returns a list of version strings, or an empty list on any failure
    (so the UI can fall back to free-text entry without crashing).
    """
    try:
        data = api_get("/tag/game_version")
    except Exception:
        return []
    if not data:
        return []
    versions = []
    for entry in data:
        if releases_only and entry.get("version_type") != "release":
            continue
        v = entry.get("version")
        if v:
            versions.append(v)
    # Modrinth returns newest first already; keep that order.
    return versions


def build_report(current_version, target_version, mods_folder, out_dir,
                  migrated, no_target_version, not_on_modrinth,
                  failed_download, security_blocked, disabled_files, titles):
    lines = []
    lines.append(f"Mod migration report: {current_version} -> {target_version}")
    lines.append(f"Source folder: {mods_folder}")
    lines.append(f"Output folder: {out_dir.resolve()}")
    lines.append("")

    lines.append(f"MIGRATED ({len(migrated)})")
    for original, proj_id, new_name in migrated:
        lines.append(f"  [{titles.get(proj_id, proj_id)}] {original}  ->  {new_name}")
    lines.append("")

    lines.append(f"NO BUILD FOR {target_version} YET ({len(no_target_version)})")
    for original, proj_id in no_target_version:
        lines.append(f"  [{titles.get(proj_id, proj_id)}] {original}")
    lines.append("")

    lines.append(f"NOT FOUND ON MODRINTH ({len(not_on_modrinth)})")
    for original in not_on_modrinth:
        lines.append(f"  {original}")
    lines.append("")

    if failed_download:
        lines.append(f"DOWNLOAD FAILED ({len(failed_download)})")
        for original, proj_id in failed_download:
            lines.append(f"  [{titles.get(proj_id, proj_id)}] {original}")
        lines.append("")

    if security_blocked:
        lines.append(f"BLOCKED BY SECURITY CHECK ({len(security_blocked)})")
        lines.append(
            "  These were NOT downloaded because something about the source "
            "didn't check out (wrong host, or the file's hash didn't match "
            "Modrinth's records)."
        )
        for original, reason in security_blocked:
            lines.append(f"  {original}: {reason}")
        lines.append("")

    if disabled_files:
        lines.append(f"SKIPPED (disabled in Pandora) ({len(disabled_files)})")
        for p in disabled_files:
            lines.append(f"  {p.name}")
        lines.append("")

    return "\n".join(lines)


def run_migration(mods_folder, current_version, target_version, out_dir,
                   log, set_progress, cancel_event):
    """Run the full migration. `log(msg, tag)` and `set_progress(done, total)`
    are callbacks; `cancel_event` is a threading.Event checked between mods.
    Returns a dict of result lists plus the report text and path.
    """
    out_dir.mkdir(parents=True, exist_ok=True)

    jar_files = sorted(
        p for p in mods_folder.iterdir()
        if p.is_file() and p.suffix.lower() == ".jar"
    )
    disabled_files = sorted(
        p for p in mods_folder.iterdir()
        if p.is_file() and p.name.lower().endswith(".jar.disabled")
    )

    migrated, not_on_modrinth, no_target_version = [], [], []
    failed_download, security_blocked = [], []
    project_ids_seen = set()
    resolved_cache = {}

    total = len(jar_files)
    log(f"Found {total} mod jar(s) in {mods_folder}", "info")
    if disabled_files:
        log(f"Note: {len(disabled_files)} disabled mod(s) will be skipped.", "info")
    set_progress(0, max(total, 1))

    for i, jar_path in enumerate(jar_files, 1):
        if cancel_event.is_set():
            log("Cancelled.", "warn")
            break

        name = jar_path.name
        log(f"{name}")

        file_hash = sha1_of_file(jar_path)
        version_info = resolved_cache.get(file_hash)
        if version_info is None:
            version_info = lookup_version_by_hash(file_hash)
            resolved_cache[file_hash] = version_info

        if not version_info:
            log("    not found on Modrinth (skipping)", "skip")
            not_on_modrinth.append(name)
            set_progress(i, total)
            continue

        if not response_matches_queried_hash(version_info, file_hash):
            log("    blocked: Modrinth's response didn't match this file's hash", "error")
            security_blocked.append((name, "API response did not match file hash"))
            set_progress(i, total)
            continue

        project_id = version_info["project_id"]
        loaders = version_info.get("loaders") or []
        project_ids_seen.add(project_id)

        candidates = get_project_versions(project_id, loaders, target_version)
        best = pick_best_version(candidates)

        if not best:
            log(f"    no build found for Minecraft {target_version}", "warn")
            no_target_version.append((name, project_id))
            set_progress(i, total)
            continue

        file_entry = pick_primary_file(best)
        if not file_entry:
            log("    matching version has no downloadable file", "warn")
            failed_download.append((name, project_id))
            set_progress(i, total)
            continue

        dest_path = out_dir / file_entry["filename"]
        log(f"    -> {best.get('version_number', '?')} for {target_version}: downloading...", "info")
        status, detail = download_and_verify(
            file_entry["url"], dest_path, file_entry.get("hashes", {})
        )
        if status == "ok":
            log(f"    done -> {file_entry['filename']}", "ok")
            migrated.append((name, project_id, file_entry["filename"]))
        elif status == "untrusted_host":
            log(f"    blocked: untrusted host ({detail}), not cdn.modrinth.com", "error")
            security_blocked.append((name, f"untrusted host: {detail}"))
        elif status == "hash_mismatch":
            log(f"    blocked: downloaded file's hash didn't match Modrinth's records ({detail})", "error")
            security_blocked.append((name, f"hash mismatch ({detail})"))
        else:
            log(f"    download failed: {detail}", "warn")
            failed_download.append((name, project_id))

        set_progress(i, total)

    titles = get_projects_meta(project_ids_seen)
    report_text = build_report(
        current_version, target_version, mods_folder, out_dir,
        migrated, no_target_version, not_on_modrinth,
        failed_download, security_blocked, disabled_files, titles,
    )
    report_path = out_dir / "migration_report.txt"
    report_path.write_text(report_text, encoding="utf-8")

    return {
        "migrated": migrated,
        "no_target_version": no_target_version,
        "not_on_modrinth": not_on_modrinth,
        "failed_download": failed_download,
        "security_blocked": security_blocked,
        "disabled_files": disabled_files,
        "report_text": report_text,
        "report_path": report_path,
    }


# ==========================================================================
# GUI
# ==========================================================================

PALETTE = {
    "bg": "#f4f6f5",
    "accent": "#3a7d44",
    "accent_dark": "#2d5f35",
    "text": "#1f2421",
    "subtext": "#5b6660",
    "console_bg": "#1c1e1a",
    "console_fg": "#e8e8e3",
}


class App(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title(f"{APP_NAME} — Modrinth Edition")
        self.geometry("800x720")
        self.minsize(700, 620)
        self.configure(bg=PALETTE["bg"])

        self.msg_queue = queue.Queue()
        self.cancel_event = threading.Event()
        self.worker_thread = None
        self.last_out_dir = None
        self.mc_versions = []  # filled in by a background fetch

        self._build_style()
        self._build_widgets()
        self.after(100, self._poll_queue)
        self._load_versions_async()

    # ---- styling ----------------------------------------------------
    def _build_style(self):
        style = ttk.Style(self)
        try:
            style.theme_use("clam")
        except tk.TclError:
            pass

        bg, accent, accent_dark = PALETTE["bg"], PALETTE["accent"], PALETTE["accent_dark"]

        style.configure("TFrame", background=bg)
        style.configure("Header.TFrame", background=accent_dark)
        style.configure("TLabel", background=bg, foreground=PALETTE["text"])
        style.configure("Sub.TLabel", background=bg, foreground=PALETTE["subtext"])
        style.configure("Header.TLabel", background=accent_dark, foreground="white",
                         font=("TkDefaultFont", 18, "bold"))
        style.configure("SubHeader.TLabel", background=accent_dark, foreground="#d7e8da",
                         font=("TkDefaultFont", 10))
        style.configure("TButton", padding=6)
        style.configure("Accent.TButton", padding=8, font=("TkDefaultFont", 10, "bold"))
        style.map(
            "Accent.TButton",
            background=[("disabled", "#a9b8ab"), ("active", accent_dark), ("!disabled", accent)],
            foreground=[("disabled", "#eef1ee"), ("!disabled", "white")],
        )
        style.configure("Horizontal.TProgressbar", background=accent, troughcolor="#dfe6e1",
                         bordercolor="#dfe6e1", lightcolor=accent, darkcolor=accent)

    # ---- layout -------------------------------------------------------
    def _build_widgets(self):
        header = ttk.Frame(self, style="Header.TFrame")
        header.pack(fill="x")
        ttk.Label(header, text=APP_NAME, style="Header.TLabel").pack(anchor="w", padx=22, pady=(18, 0))
        ttk.Label(
            header,
            text="Migrate your Minecraft mods to a new version, via Modrinth — "
                 "works with Prism, MultiMC, Modrinth App, Pandora & more",
            style="SubHeader.TLabel",
        ).pack(anchor="w", padx=22, pady=(2, 16))

        body = ttk.Frame(self)
        body.pack(fill="both", expand=True, padx=22, pady=16)
        body.columnconfigure(1, weight=1)

        row = 0
        ttk.Label(body, text="Mods folder").grid(row=row, column=0, sticky="w", pady=6)
        self.mods_var = tk.StringVar()
        ttk.Entry(body, textvariable=self.mods_var).grid(row=row, column=1, sticky="ew", padx=8)
        btns = ttk.Frame(body)
        btns.grid(row=row, column=2)
        ttk.Button(btns, text="Browse…", command=self._browse_mods).pack(side="left", padx=2)
        ttk.Button(btns, text="Auto-detect", command=self._auto_detect).pack(side="left", padx=2)

        row += 1
        self.mods_hint = ttk.Label(body, text="", style="Sub.TLabel")
        self.mods_hint.grid(row=row, column=1, columnspan=2, sticky="w", padx=8)

        row += 1
        ttk.Label(body, text="Current Minecraft version").grid(row=row, column=0, sticky="w", pady=6)
        self.current_var = tk.StringVar()
        self.current_combo = ttk.Combobox(body, textvariable=self.current_var, values=[])
        self.current_combo.grid(row=row, column=1, sticky="ew", padx=8, columnspan=2)

        row += 1
        ttk.Label(body, text="Target Minecraft version").grid(row=row, column=0, sticky="w", pady=6)
        self.target_var = tk.StringVar()
        self.target_combo = ttk.Combobox(body, textvariable=self.target_var, values=[])
        self.target_combo.grid(row=row, column=1, sticky="ew", padx=8, columnspan=2)

        row += 1
        opts_row = ttk.Frame(body)
        opts_row.grid(row=row, column=1, columnspan=2, sticky="w", padx=8)
        self.versions_status = ttk.Label(opts_row, text="Loading version list…", style="Sub.TLabel")
        self.versions_status.pack(side="left")
        self.snapshots_var = tk.BooleanVar(value=False)
        self.snapshots_check = ttk.Checkbutton(
            opts_row, text="Include snapshots", variable=self.snapshots_var,
            command=self._on_snapshots_toggle,
        )
        self.snapshots_check.pack(side="left", padx=16)

        row += 1
        ttk.Label(body, text="Save migrated mods to").grid(row=row, column=0, sticky="w", pady=6)
        self.out_var = tk.StringVar(value=str(Path.home() / "ModMigrator" / "migrated_mods"))
        ttk.Entry(body, textvariable=self.out_var).grid(row=row, column=1, sticky="ew", padx=8)
        ttk.Button(body, text="Browse…", command=self._browse_out).grid(row=row, column=2)

        row += 1
        action_row = ttk.Frame(body)
        action_row.grid(row=row, column=0, columnspan=3, sticky="ew", pady=(16, 4))
        self.start_btn = ttk.Button(action_row, text="Start Migration", style="Accent.TButton",
                                     command=self._start)
        self.start_btn.pack(side="left")
        self.cancel_btn = ttk.Button(action_row, text="Cancel", command=self._cancel, state="disabled")
        self.cancel_btn.pack(side="left", padx=8)
        self.status_label = ttk.Label(action_row, text="", style="Sub.TLabel")
        self.status_label.pack(side="left", padx=12)

        row += 1
        self.progress = ttk.Progressbar(body, mode="determinate")
        self.progress.grid(row=row, column=0, columnspan=3, sticky="ew", pady=(2, 12))

        row += 1
        log_frame = ttk.Frame(body)
        log_frame.grid(row=row, column=0, columnspan=3, sticky="nsew")
        body.rowconfigure(row, weight=1)

        self.log_text = tk.Text(
            log_frame, wrap="word", height=14,
            bg=PALETTE["console_bg"], fg=PALETTE["console_fg"],
            insertbackground=PALETTE["console_fg"],
            font=("TkFixedFont", 10), borderwidth=0, padx=10, pady=8,
        )
        self.log_text.pack(side="left", fill="both", expand=True)
        scrollbar = ttk.Scrollbar(log_frame, command=self.log_text.yview)
        scrollbar.pack(side="right", fill="y")
        self.log_text.configure(yscrollcommand=scrollbar.set, state="disabled")

        self.log_text.tag_configure("ok", foreground="#7ee787")
        self.log_text.tag_configure("warn", foreground="#f4c95d")
        self.log_text.tag_configure("error", foreground="#ff6b6b")
        self.log_text.tag_configure("skip", foreground="#9aa39a")
        self.log_text.tag_configure("info", foreground="#79c0ff")

        row += 1
        footer = ttk.Frame(body)
        footer.grid(row=row, column=0, columnspan=3, sticky="ew", pady=(10, 0))
        self.summary_label = ttk.Label(footer, text="", style="Sub.TLabel")
        self.summary_label.pack(side="left")
        self.open_folder_btn = ttk.Button(footer, text="Open Output Folder",
                                           command=self._open_output_folder, state="disabled")
        self.open_folder_btn.pack(side="right")

    # ---- actions --------------------------------------------------------
    def _browse_mods(self):
        path = filedialog.askdirectory(title="Select your instance's mods folder")
        if path:
            self.mods_var.set(path)
            self.mods_hint.configure(text="")

    def _browse_out(self):
        path = filedialog.askdirectory(title="Select a folder to save migrated mods")
        if path:
            self.out_var.set(path)

    def _auto_detect(self):
        candidates = find_mod_folders()
        if not candidates:
            messagebox.showinfo(
                APP_NAME,
                "Couldn't auto-detect any launcher instances on this "
                "computer.\n\n"
                "This tool knows the default locations for Prism, MultiMC, "
                "the Modrinth App, Pandora, ATLauncher, GDLauncher, "
                "CurseForge, Technic and a plain .minecraft — but if you've "
                "moved your instances, or use a different launcher, just "
                "click Browse… and point it at your instance's 'mods' "
                "folder directly (most launchers have an 'Open Folder' "
                "option on the instance).",
            )
            return
        if len(candidates) == 1:
            launcher, instance, path = candidates[0]
            self.mods_var.set(str(path))
            self.mods_hint.configure(text=f"Detected: {launcher} — {instance}")
            return
        options = [f"{launcher}  ·  {instance}   ({path})"
                   for launcher, instance, path in candidates]
        index = self._pick_from_list("Select an instance", options)
        if index is not None:
            launcher, instance, path = candidates[index]
            self.mods_var.set(str(path))
            self.mods_hint.configure(text=f"Detected: {launcher} — {instance}")

    def _pick_from_list(self, title, options):
        win = tk.Toplevel(self)
        win.title(title)
        win.geometry("560x320")
        win.transient(self)
        win.grab_set()
        result = {"index": None}

        ttk.Label(win, text="Multiple instances were found across your "
                            "launchers:", padding=10).pack(anchor="w")
        listbox = tk.Listbox(win, font=("TkDefaultFont", 10))
        for opt in options:
            listbox.insert("end", opt)
        listbox.pack(fill="both", expand=True, padx=10, pady=6)
        listbox.selection_set(0)

        def confirm():
            sel = listbox.curselection()
            if sel:
                result["index"] = sel[0]
            win.destroy()

        listbox.bind("<Double-Button-1>", lambda e: confirm())

        btn_row = ttk.Frame(win)
        btn_row.pack(fill="x", pady=8)
        ttk.Button(btn_row, text="Select", style="Accent.TButton", command=confirm).pack(side="right", padx=10)
        ttk.Button(btn_row, text="Cancel", command=win.destroy).pack(side="right")

        self.wait_window(win)
        return result["index"]

    # ---- version dropdown loading --------------------------------------
    def _load_versions_async(self):
        def work():
            release = fetch_minecraft_versions(releases_only=True)
            full = fetch_minecraft_versions(releases_only=False)
            self.msg_queue.put(("versions", (release, full), None))
        threading.Thread(target=work, daemon=True).start()

    def _apply_versions(self, release, full):
        self._versions_release = release
        self._versions_full = full
        self.mc_versions = release
        self._refresh_version_dropdowns()
        if release:
            self.versions_status.configure(text=f"{len(release)} release versions")
        else:
            self.versions_status.configure(
                text="Couldn't load list — type versions manually")

    def _refresh_version_dropdowns(self):
        show_snapshots = self.snapshots_var.get()
        values = getattr(self, "_versions_full", []) if show_snapshots \
            else getattr(self, "_versions_release", [])
        self.current_combo.configure(values=values)
        self.target_combo.configure(values=values)

    def _on_snapshots_toggle(self):
        self._refresh_version_dropdowns()

    def _start(self):
        mods_folder = Path(self.mods_var.get().strip()).expanduser()
        current_version = self.current_var.get().strip()
        target_version = self.target_var.get().strip()
        out_dir_raw = self.out_var.get().strip()

        if not mods_folder.is_dir():
            messagebox.showerror(APP_NAME, "Please choose a valid mods folder.")
            return
        if not current_version or not target_version:
            messagebox.showerror(APP_NAME, "Please fill in both the current and target Minecraft versions.")
            return
        if not out_dir_raw:
            messagebox.showerror(APP_NAME, "Please choose an output folder.")
            return

        out_dir = Path(out_dir_raw).expanduser()

        self._set_log_text("")
        self.progress.configure(value=0, maximum=1)
        self.summary_label.configure(text="")
        self.open_folder_btn.configure(state="disabled")
        self.start_btn.configure(state="disabled")
        self.cancel_btn.configure(state="normal")
        self.status_label.configure(text="Working…")

        self.cancel_event = threading.Event()
        self.last_out_dir = out_dir

        self.worker_thread = threading.Thread(
            target=self._worker,
            args=(mods_folder, current_version, target_version, out_dir),
            daemon=True,
        )
        self.worker_thread.start()

    def _cancel(self):
        self.cancel_event.set()
        self.status_label.configure(text="Cancelling…")

    def _worker(self, mods_folder, current_version, target_version, out_dir):
        def log(msg, tag=None):
            self.msg_queue.put(("log", msg, tag))

        def set_progress(done, total):
            self.msg_queue.put(("progress", done, total))

        try:
            result = run_migration(
                mods_folder, current_version, target_version, out_dir,
                log, set_progress, self.cancel_event,
            )
            self.msg_queue.put(("done", result, None))
        except Exception as e:  # noqa: BLE001 - surface any failure to the UI
            self.msg_queue.put(("error", str(e), None))

    def _poll_queue(self):
        try:
            while True:
                kind, a, b = self.msg_queue.get_nowait()
                if kind == "log":
                    self._append_log(a, b)
                elif kind == "progress":
                    total = b or 1
                    self.progress.configure(maximum=total, value=a)
                elif kind == "done":
                    self._on_done(a)
                elif kind == "error":
                    self._on_error(a)
                elif kind == "versions":
                    release, full = a
                    self._apply_versions(release, full)
        except queue.Empty:
            pass
        self.after(100, self._poll_queue)

    def _append_log(self, msg, tag):
        self.log_text.configure(state="normal")
        self.log_text.insert("end", msg + "\n", tag or ())
        self.log_text.see("end")
        self.log_text.configure(state="disabled")

    def _set_log_text(self, text):
        self.log_text.configure(state="normal")
        self.log_text.delete("1.0", "end")
        if text:
            self.log_text.insert("end", text)
        self.log_text.configure(state="disabled")

    def _on_done(self, result):
        self.start_btn.configure(state="normal")
        self.cancel_btn.configure(state="disabled")
        self.open_folder_btn.configure(state="normal")
        self.status_label.configure(text="Cancelled" if self.cancel_event.is_set() else "Done")
        self.summary_label.configure(text=(
            f"Migrated: {len(result['migrated'])}   "
            f"No build yet: {len(result['no_target_version'])}   "
            f"Not on Modrinth: {len(result['not_on_modrinth'])}   "
            f"Blocked: {len(result['security_blocked'])}   "
            f"Failed: {len(result['failed_download'])}"
        ))

    def _on_error(self, message):
        self.start_btn.configure(state="normal")
        self.cancel_btn.configure(state="disabled")
        self.status_label.configure(text="Error")
        messagebox.showerror(APP_NAME, f"Something went wrong:\n\n{message}")

    def _open_output_folder(self):
        path = self.last_out_dir
        if not path or not path.exists():
            return
        system = platform.system()
        try:
            if system == "Windows":
                os.startfile(str(path))  # type: ignore[attr-defined]
            elif system == "Darwin":
                subprocess.Popen(["open", str(path)])
            else:
                subprocess.Popen(["xdg-open", str(path)])
        except OSError:
            messagebox.showinfo(APP_NAME, f"Your files are here:\n{path}")


def main():
    app = App()
    app.mainloop()


if __name__ == "__main__":
    main()
