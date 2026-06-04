"""
GitLab Group Cloner — Method 1 (requests + subprocess)
========================================================
Reads config.json:
{
    "gitlab_url": "https://gitlab.onefiserv.net",
    "access_token": "WDyreSgKjMTZt2Zomih7",
    "group_path": "na/gfs/prepaid/moneynetwork/mn-2.0",
    "output_zip": "gitlab_repos.zip"
}

Usage:
    pip install requests
    python gitlab_clone_to_zip.py
"""

import json
import os
import shutil
import stat
import subprocess
import zipfile

import requests


# ─────────────────────────────────────────────
# Load config
# ─────────────────────────────────────────────
with open("config.json") as f:
    config = json.load(f)

GITLAB_URL   = config["gitlab_url"].rstrip("/")
ACCESS_TOKEN = config["access_token"]
GROUP_PATH   = config["group_path"]
OUTPUT_ZIP   = config.get("output_zip", "gitlab_repos.zip")

# Use user TEMP folder — no admin needed, short path
TMP_DIR = os.path.join(os.environ.get("TEMP", os.path.expanduser("~")), "gl_clone")

HEADERS = {"PRIVATE-TOKEN": ACCESS_TOKEN}


# ─────────────────────────────────────────────
# Fix: force-delete read-only .git files on Windows
# ─────────────────────────────────────────────
def remove_readonly(func, path, _):
    """Called by shutil.rmtree on permission error — clears read-only flag."""
    os.chmod(path, stat.S_IWRITE)
    func(path)

def safe_rmtree(path):
    if os.path.exists(path):
        shutil.rmtree(path, onerror=remove_readonly)


# ─────────────────────────────────────────────
# Fetch all projects via REST API (paginated)
# ─────────────────────────────────────────────
def get_all_projects():
    encoded = GROUP_PATH.replace("/", "%2F")
    url = f"{GITLAB_URL}/api/v4/groups/{encoded}/projects"
    params = {"include_subgroups": "true", "per_page": 100, "page": 1, "archived": "false"}
    projects = []
    print(f"📡  Fetching projects under: {GROUP_PATH}")
    while True:
        resp = requests.get(url, headers=HEADERS, params=params, timeout=30, verify=False)
        resp.raise_for_status()
        page = resp.json()
        if not page:
            break
        projects.extend(page)
        print(f"   Page {params['page']}: {len(page)} project(s)...")
        next_page = resp.headers.get("x-next-page", "")
        if not next_page:
            break
        params["page"] = int(next_page)
    return projects


# ─────────────────────────────────────────────
# Clone a single repo
# ─────────────────────────────────────────────
def clone_repo(http_url: str, dest: str) -> bool:
    auth_url = http_url.replace("https://", f"https://oauth2:{ACCESS_TOKEN}@")
    os.makedirs(os.path.dirname(dest), exist_ok=True)
    result = subprocess.run(
        ["git", "-c", "core.longpaths=true", "clone", "--depth", "1", auth_url, dest],
        capture_output=True, text=True
    )
    if result.returncode != 0:
        err = result.stderr.strip().splitlines()[-1] if result.stderr else "unknown"
        print(f"           ⚠  {err}")
        return False
    return True


# ─────────────────────────────────────────────
# Main
# ─────────────────────────────────────────────
def main():
    print(f"📁  Temp dir: {TMP_DIR}\n")

    # 1. Fetch
    projects = get_all_projects()
    if not projects:
        print("⚠  No projects found.")
        return
    print(f"✔   Found {len(projects)} project(s).\n")

    # 2. Clean + create temp dir
    safe_rmtree(TMP_DIR)
    os.makedirs(TMP_DIR)

    success, failed = 0, []

    # 3. Clone each
    for i, proj in enumerate(projects, 1):
        namespace = proj["path_with_namespace"]
        dest = os.path.join(TMP_DIR, namespace)
        print(f"[{i}/{len(projects)}] Cloning: {namespace}")
        if clone_repo(proj["http_url_to_repo"], dest):
            print(f"           ✔ Done")
            success += 1
        else:
            failed.append(namespace)

    # 4. Zip
    print(f"\n📦  Creating zip: {OUTPUT_ZIP} ...")
    with zipfile.ZipFile(OUTPUT_ZIP, "w", zipfile.ZIP_DEFLATED) as zf:
        for root, _dirs, files in os.walk(TMP_DIR):
            for file in files:
                full_path = os.path.join(root, file)
                arcname = os.path.relpath(full_path, TMP_DIR)
                zf.write(full_path, arcname)

    size_mb = os.path.getsize(OUTPUT_ZIP) / (1024 * 1024)
    print(f"✅  Zip created: {OUTPUT_ZIP}  ({size_mb:.2f} MB)")

    # 5. Cleanup — uses safe_rmtree to handle read-only .git files
    print("🧹  Cleaning up temp folder...")
    safe_rmtree(TMP_DIR)
    print("✔   Done.")

    # 6. Summary
    print(f"\n{'─'*50}")
    print(f"  Total   : {len(projects)}")
    print(f"  Success : {success}")
    print(f"  Failed  : {len(failed)}")
    if failed:
        for r in failed:
            print(f"    - {r}")
    print(f"  Output  : {os.path.abspath(OUTPUT_ZIP)}")
    print(f"{'─'*50}\n")


if __name__ == "__main__":
    main()
