"""
GitLab Group Cloner — Testing Version
=====================================

This script clones only the FIRST 10 projects for testing.

After testing, change:

    TEST_LIMIT = 10

to:

    TEST_LIMIT = None

to clone all projects.

Required:
    pip install requests

config.json example:

{
    "gitlab_url": "https://gitlab.onefiserv.net",
    "access_token": "YOUR_TOKEN_HERE",
    "group_path": "na/gfs/prepaid/moneynetwork/mn-2.0",
    "output_zip": "gitlab_repos_test.zip",
    "verify_ssl": false
}
"""

import json
import os
import shutil
import stat
import subprocess
import tempfile
import time
import uuid
import zipfile
from urllib.parse import quote

import requests
import urllib3


# ─────────────────────────────────────────────
# Testing limit
# ─────────────────────────────────────────────
TEST_LIMIT = 10
# After testing, use this:
# TEST_LIMIT = None


# ─────────────────────────────────────────────
# Load config
# ─────────────────────────────────────────────
with open("config.json", "r", encoding="utf-8") as f:
    config = json.load(f)

GITLAB_URL = config["gitlab_url"].rstrip("/")
ACCESS_TOKEN = config["access_token"]
GROUP_PATH = config["group_path"]
OUTPUT_ZIP = config.get("output_zip", "gitlab_repos_test.zip")
VERIFY_SSL = config.get("verify_ssl", False)

if not VERIFY_SSL:
    urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

HEADERS = {
    "PRIVATE-TOKEN": ACCESS_TOKEN
}


# ─────────────────────────────────────────────
# Fresh temp folder every run
# ─────────────────────────────────────────────
BASE_TEMP_DIR = os.path.join(tempfile.gettempdir(), "gitlab_clone_runs")
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
# Fetch all projects from group + subgroups
# ─────────────────────────────────────────────
def get_all_projects():
    encoded_group = quote(GROUP_PATH, safe="")
    url = f"{GITLAB_URL}/api/v4/groups/{encoded_group}/projects"

    params = {
        "include_subgroups": "true",
        "per_page": 100,
        "page": 1,
        "archived": "false",
        "simple": "false",
        "order_by": "path",
        "sort": "asc"
    }

    projects = []

    print("📡 Fetching projects under:")
    print(f"   {GROUP_PATH}\n")

    while True:
        resp = requests.get(
            url,
            headers=HEADERS,
            params=params,
            timeout=60,
            verify=VERIFY_SSL
        )

        if resp.status_code == 404:
            raise Exception("Group not found. Check group_path or token permissions.")

        if resp.status_code == 401:
            raise Exception("Unauthorized. Check access token.")

        if resp.status_code == 403:
            raise Exception("Forbidden. Token does not have enough permission.")

        resp.raise_for_status()

        page_projects = resp.json()

        if not page_projects:
            break

        projects.extend(page_projects)

        print(f"   Page {params['page']}: {len(page_projects)} project(s)")

        next_page = resp.headers.get("x-next-page")
        if not next_page:
            break

        params["page"] = int(next_page)

    return projects


# ─────────────────────────────────────────────
# Clone one repo
# ─────────────────────────────────────────────
def clone_repo(http_url, dest):
    token_encoded = quote(ACCESS_TOKEN, safe="")

    auth_url = http_url.replace(
        "https://",
        f"https://oauth2:{token_encoded}@"
    )

    os.makedirs(os.path.dirname(dest), exist_ok=True)

    cmd = [
        "git",
        "-c", "core.longpaths=true",
        "-c", "gc.auto=0",
        "clone",
        "--depth", "1",
        auth_url,
        dest
    ]

    result = subprocess.run(
        cmd,
        capture_output=True,
        text=True
    )

    if result.returncode != 0:
        err_lines = result.stderr.strip().splitlines()
        err = err_lines[-1] if err_lines else "Unknown git clone error"
        print(f"           ⚠ {err}")
        return False

    # Remove token from .git/config just for safety
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
# Create zip without .git folders
# ─────────────────────────────────────────────
def create_zip():
    print(f"\n📦 Creating zip: {OUTPUT_ZIP} ...")

    with zipfile.ZipFile(OUTPUT_ZIP, "w", zipfile.ZIP_DEFLATED) as zf:
        for root, dirs, files in os.walk(TMP_DIR):

            # Very important: skip .git folders
            dirs[:] = [d for d in dirs if d != ".git"]

            for file in files:
                full_path = os.path.join(root, file)

                if not os.path.exists(full_path):
                    print(f"⚠ Skipped missing file: {full_path}")
                    continue

                arcname = os.path.relpath(full_path, TMP_DIR)

                try:
                    zf.write(full_path, arcname)
                except FileNotFoundError:
                    print(f"⚠ Skipped missing file during zip: {full_path}")
                except PermissionError:
                    print(f"⚠ Skipped locked file during zip: {full_path}")
                except OSError as e:
                    print(f"⚠ Skipped file because of OS error: {full_path}")
                    print(f"   {e}")

    size_mb = os.path.getsize(OUTPUT_ZIP) / (1024 * 1024)
    print(f"✅ Zip created: {OUTPUT_ZIP} ({size_mb:.2f} MB)")


# ─────────────────────────────────────────────
# Main
# ─────────────────────────────────────────────
def main():
    print("📁 Temp dir:")
    print(f"   {TMP_DIR}\n")

    os.makedirs(TMP_DIR, exist_ok=True)

    projects = get_all_projects()

    if not projects:
        print("⚠ No projects found.")
        return

    print(f"\n✔ Found {len(projects)} project(s).")

    if TEST_LIMIT:
        projects_to_clone = projects[:TEST_LIMIT]
        print(f"⚠ TEST MODE: Cloning only first {TEST_LIMIT} project(s).\n")
    else:
        projects_to_clone = projects
        print("🚀 FULL MODE: Cloning all projects.\n")

    success = 0
    failed = []

    for i, proj in enumerate(projects_to_clone, 1):
        namespace = proj["path_with_namespace"]

        # Keeps full GitLab folder/subfolder structure
        dest = os.path.join(TMP_DIR, *namespace.split("/"))

        print(f"[{i}/{len(projects_to_clone)}] Cloning:")
        print(f"           {namespace}")

        if clone_repo(proj["http_url_to_repo"], dest):
            print("           ✔ Done")
            success += 1
        else:
            failed.append(namespace)

    create_zip()

    print("\n🧹 Cleaning up temp folder...")
    safe_rmtree(TMP_DIR)

    print("\n" + "─" * 60)
    print(f"Total GitLab projects found : {len(projects)}")
    print(f"Projects cloned in this run : {len(projects_to_clone)}")
    print(f"Success                     : {success}")
    print(f"Failed                      : {len(failed)}")
    print(f"Output zip                  : {os.path.abspath(OUTPUT_ZIP)}")

    if failed:
        print("\nFailed repos:")
        for repo in failed:
            print(f" - {repo}")

    print("─" * 60)


if __name__ == "__main__":
    main()
