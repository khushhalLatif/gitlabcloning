"""
GitLab Group Cloner
====================
Reads config.json in the same folder:

{
    "gitlab_url": "https://gitlab.onefiserv.net",
    "access_token": "WDyreSgKjMTZt2Zomih7",
    "group_path": "na/gfs/prepaid/moneynetwork/mn-2.0"
}

Usage:
    pip install python-gitlab
    python gitlab_clone_to_zip.py
"""

import json
import os
import shutil
import subprocess
import zipfile

import gitlab


# ─────────────────────────────────────────────
# Load config
# ─────────────────────────────────────────────
with open("config.json") as f:
    config = json.load(f)

GITLAB_URL   = config["gitlab_url"]
ACCESS_TOKEN = config["access_token"]
GROUP_PATH   = config["group_path"]
OUTPUT_ZIP   = config.get("output_zip", "gitlab_repos.zip")
TMP_DIR      = "_clone_tmp"


# ─────────────────────────────────────────────
# Connect to GitLab
# ─────────────────────────────────────────────
print(f"\n🔗  Connecting to {GITLAB_URL} ...")
gl = gitlab.Gitlab(
    url=GITLAB_URL,
    private_token=ACCESS_TOKEN
)
gl.auth()
print(f"✔   Authenticated successfully.\n")


# ─────────────────────────────────────────────
# Fetch all projects in the group (+ subgroups)
# ─────────────────────────────────────────────
print(f"📡  Fetching projects under: {GROUP_PATH}")
group = gl.groups.get(GROUP_PATH)

projects = group.projects.list(
    include_subgroups=True,
    all=True
)
print(f"✔   Found {len(projects)} project(s).\n")


# ─────────────────────────────────────────────
# Clone each project
# ─────────────────────────────────────────────
if os.path.exists(TMP_DIR):
    shutil.rmtree(TMP_DIR)
os.makedirs(TMP_DIR)

success, failed = 0, []

for i, proj in enumerate(projects, 1):
    clone_url_auth = proj.http_url_to_repo.replace(
        "https://", f"https://oauth2:{ACCESS_TOKEN}@"
    )

    # Preserve nested structure:  na/gfs/project  →  na/gfs/project/
    folder_name = proj.path_with_namespace  # keep slashes = real subfolders
    dest = os.path.join(TMP_DIR, folder_name)
    os.makedirs(os.path.dirname(dest), exist_ok=True)  # create parent dirs

    print(f"[{i}/{len(projects)}] Cloning: {proj.path_with_namespace}")

    result = subprocess.run(
        ["git", "clone", "--depth", "1", clone_url_auth, dest],
        capture_output=True,
        text=True
    )

    if result.returncode == 0:
        print(f"           ✔ Done")
        success += 1
    else:
        err = result.stderr.strip().splitlines()[-1] if result.stderr else "unknown error"
        print(f"           ⚠ Failed: {err}")
        failed.append(proj.path_with_namespace)


# ─────────────────────────────────────────────
# Zip everything
# ─────────────────────────────────────────────
print(f"\n📦  Creating zip: {OUTPUT_ZIP} ...")

with zipfile.ZipFile(OUTPUT_ZIP, "w", zipfile.ZIP_DEFLATED) as zf:
    for root, _dirs, files in os.walk(TMP_DIR):
        for file in files:
            full_path = os.path.join(root, file)
            arcname   = os.path.relpath(full_path, TMP_DIR)
            zf.write(full_path, arcname)

size_mb = os.path.getsize(OUTPUT_ZIP) / (1024 * 1024)
print(f"✅  Zip created: {OUTPUT_ZIP}  ({size_mb:.2f} MB)")

shutil.rmtree(TMP_DIR)


# ─────────────────────────────────────────────
# Summary
# ─────────────────────────────────────────────
print(f"\n{'─'*50}")
print(f"  Total projects  : {len(projects)}")
print(f"  Cloned OK       : {success}")
print(f"  Failed          : {len(failed)}")
if failed:
    print("  Failed repos:")
    for r in failed:
        print(f"    - {r}")
print(f"  Output          : {os.path.abspath(OUTPUT_ZIP)}")
print(f"{'─'*50}\n")
