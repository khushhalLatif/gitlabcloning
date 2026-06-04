"""
Clone GitLab project links from a list and create one zip per project locally.

Files needed:

1. config.json
2. project_links.txt

Install:
    pip install requests

Run:
    python clone_links_to_individual_zips.py
"""

import json
import os
import re
import shutil
import stat
import subprocess
import tempfile
import time
import uuid
import zipfile
from urllib.parse import quote, urlparse


# ─────────────────────────────────────────────
# Load config
# ─────────────────────────────────────────────
with open("config.json", "r", encoding="utf-8") as f:
    config = json.load(f)

ACCESS_TOKEN = config["access_token"]
LINKS_FILE = config.get("links_file", "project_links.txt")
OUTPUT_DIR = config.get("output_dir", "repo_zips")
CLONE_DEPTH = config.get("clone_depth", 1)
INCLUDE_GIT_FOLDER = config.get("include_git_folder", False)

os.makedirs(OUTPUT_DIR, exist_ok=True)


# ─────────────────────────────────────────────
# Fresh temp folder every run
# ─────────────────────────────────────────────
BASE_TEMP_DIR = os.path.join(tempfile.gettempdir(), "gitlab_link_clone_runs")
os.makedirs(BASE_TEMP_DIR, exist_ok=True)

TMP_DIR = os.path.join(
    BASE_TEMP_DIR,
    f"run_{time.strftime('%Y%m%d_%H%M%S')}_{uuid.uuid4().hex[:6]}"
)


# ─────────────────────────────────────────────
# Windows delete helpers
# ─────────────────────────────────────────────
def remove_readonly(func, path, exc_info):
    try:
        os.chmod(path, stat.S_IWRITE)
        func(path)
    except Exception:
        pass


def safe_rmtree(path, retries=5, delay=2):
    if not os.path.exists(path):
        return

    for attempt in range(1, retries + 1):
        try:
            shutil.rmtree(path, onerror=remove_readonly)
            print("✔ Temp folder cleaned.")
            return
        except Exception as e:
            print(f"⚠ Cleanup attempt {attempt}/{retries} failed: {e}")
            time.sleep(delay)

    print("⚠ Temp folder could not be deleted right now.")
    print("You can delete it manually later:")
    print(path)


# ─────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────
def read_project_links(file_path):
    if not os.path.exists(file_path):
        raise FileNotFoundError(f"Links file not found: {file_path}")

    links = []

    with open(file_path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()

            if not line:
                continue

            if line.startswith("#"):
                continue

            links.append(line)

    return links


def normalize_git_url(url):
    url = url.strip()

    if not url.endswith(".git"):
        url += ".git"

    return url


def add_token_to_url(http_url):
    token_encoded = quote(ACCESS_TOKEN, safe="")

    if http_url.startswith("https://"):
        return http_url.replace(
            "https://",
            f"https://oauth2:{token_encoded}@",
            1
        )

    raise ValueError(f"Only HTTPS GitLab links are supported: {http_url}")


def get_repo_name_from_url(url):
    parsed = urlparse(url)
    path = parsed.path.strip("/")

    if path.endswith(".git"):
        path = path[:-4]

    repo_name = path.split("/")[-1]

    # Make safe Windows filename
    repo_name = re.sub(r'[<>:"/\\|?*]', "_", repo_name)

    return repo_name


def get_safe_zip_name(url, index):
    parsed = urlparse(url)
    path = parsed.path.strip("/")

    if path.endswith(".git"):
        path = path[:-4]

    # Keep subgroup path in zip name to avoid duplicate repo names
    safe_name = re.sub(r'[<>:"/\\|?*]', "_", path)

    return f"{index:03d}_{safe_name}.zip"


# ─────────────────────────────────────────────
# Clone repo
# ─────────────────────────────────────────────
def clone_repo(http_url, dest):
    auth_url = add_token_to_url(http_url)

    os.makedirs(os.path.dirname(dest), exist_ok=True)

    cmd = [
        "git",
        "-c", "core.longpaths=true",
        "-c", "gc.auto=0",
        "clone"
    ]

    if CLONE_DEPTH and int(CLONE_DEPTH) > 0:
        cmd.extend(["--depth", str(CLONE_DEPTH)])

    cmd.extend([auth_url, dest])

    result = subprocess.run(
        cmd,
        capture_output=True,
        text=True
    )

    if result.returncode != 0:
        err_lines = result.stderr.strip().splitlines()
        err = err_lines[-1] if err_lines else "Unknown git clone error"
        print(f"   ⚠ Clone failed: {err}")
        return False

    # Remove token from .git/config for safety
    subprocess.run(
        [
            "git",
            "-C",
            dest,
            "remote",
            "set-url",
            "origin",
            http_url
        ],
        capture_output=True,
        text=True
    )

    return True


# ─────────────────────────────────────────────
# Create zip for one repo
# ─────────────────────────────────────────────
def create_zip_for_folder(folder_path, zip_path):
    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
        for root, dirs, files in os.walk(folder_path):

            # Skip .git folder by default
            if not INCLUDE_GIT_FOLDER:
                dirs[:] = [d for d in dirs if d != ".git"]

            for file in files:
                full_path = os.path.join(root, file)

                if not os.path.exists(full_path):
                    continue

                arcname = os.path.relpath(full_path, folder_path)

                try:
                    zf.write(full_path, arcname)
                except FileNotFoundError:
                    print(f"   ⚠ Skipped missing file: {full_path}")
                except PermissionError:
                    print(f"   ⚠ Skipped locked file: {full_path}")
                except OSError as e:
                    print(f"   ⚠ Skipped file because of OS error: {full_path}")
                    print(f"      {e}")

    size_mb = os.path.getsize(zip_path) / (1024 * 1024)
    print(f"   ✅ Zip created: {zip_path} ({size_mb:.2f} MB)")


# ─────────────────────────────────────────────
# Main
# ─────────────────────────────────────────────
def main():
    print("📁 Temp dir:")
    print(f"   {TMP_DIR}\n")

    os.makedirs(TMP_DIR, exist_ok=True)

    links = read_project_links(LINKS_FILE)

    if not links:
        print("⚠ No links found.")
        return

    print(f"✔ Found {len(links)} project link(s).\n")

    success = 0
    failed = []

    for index, raw_link in enumerate(links, 1):
        http_url = normalize_git_url(raw_link)
        repo_name = get_repo_name_from_url(http_url)

        clone_path = os.path.join(
            TMP_DIR,
            f"{index:03d}_{repo_name}"
        )

        zip_name = get_safe_zip_name(http_url, index)
        zip_path = os.path.join(OUTPUT_DIR, zip_name)

        print(f"[{index}/{len(links)}] Processing:")
        print(f"   {http_url}")

        if os.path.exists(zip_path):
            print(f"   ⚠ Zip already exists, skipping:")
            print(f"      {zip_path}")
            continue

        cloned = clone_repo(http_url, clone_path)

        if not cloned:
            failed.append(http_url)
            continue

        create_zip_for_folder(clone_path, zip_path)
        success += 1

        # Remove cloned repo after zip is created
        safe_rmtree(clone_path)

        print("")

    print("\n🧹 Cleaning main temp folder...")
    safe_rmtree(TMP_DIR)

    print("\n" + "─" * 60)
    print(f"Total links : {len(links)}")
    print(f"Success     : {success}")
    print(f"Failed      : {len(failed)}")
    print(f"Output dir  : {os.path.abspath(OUTPUT_DIR)}")

    if failed:
        print("\nFailed links:")
        for link in failed:
            print(f" - {link}")

    print("─" * 60)


if __name__ == "__main__":
    main()
