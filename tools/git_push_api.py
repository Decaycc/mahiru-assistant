# -*- coding: utf-8 -*-
"""通过 GitHub Git Data API 把本地工作树推送到 Decaycc/mahiru-assistant 的 main 分支。

因 github.com:443 被墙而 api.github.com:443 可达，故不走 git push，直接：
  1. 枚举本地文件（尊重 .gitignore）
  2. 拉取远程 tree 清单
  3. 计算差异（新增/变更/删除）
  4. 逐文件上传新 blob（Git blob = sha1("blob <size>\\0<content>")）
  5. 用完整路径一次性创建新 tree（GitHub 自动嵌套）
  6. 创建 commit（父 = 远程 HEAD）
  7. PATCH git/refs/heads/main 更新分支

用法：
  $env:GH_TOKEN = "<PAT>"
  D:\\Envs\\mahiru-assistant\\Scripts\\python.exe tools\\_git_push.py --dry-run
  ... --execute
"""
import base64
import fnmatch
import hashlib
import json
import os
import sys
import time
import urllib.request
import urllib.parse
import urllib.error

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
API = "https://api.github.com"
REPO = "Decaycc/mahiru-assistant"
TOKEN = os.environ.get("GH_TOKEN", "")


def get_remote_head():
    """动态读取远程 main 的 HEAD，避免硬编码过期。"""
    ref = api_req("GET", "%s/repos/%s/git/ref/heads/main" % (API, REPO))
    return ref["object"]["sha"]

IGNORED_DIRS = {"__pycache__", "build", "dist", "config", ".vscode", ".idea",
                ".git", ".pytest_cache", ".mypy_cache", ".ruff_cache"}
IGNORED_DIR_GLOBS = ("*.egg-info",)
IGNORED_FILE_GLOBS = ("*.pyc", "*.pyo", "*.pyd", "*.spec", "Thumbs.db",
                      "desktop.ini", "*.swp", "*.swo")
# tools/.rule_cache/ 是被 gitignore 的整目录
IGNORED_SUBDIRS = {("tools", ".rule_cache")}


def ignored(relpath):
    parts = relpath.replace("\\", "/").split("/")
    for p in parts:
        if p in IGNORED_DIRS:
            return True
    for i in range(len(parts) - 1):
        if tuple(parts[i:i + 2]) in IGNORED_SUBDIRS:
            return True
    name = parts[-1]
    for g in IGNORED_DIR_GLOBS:
        if any(fnmatch.fnmatch(p, g) for p in parts[:-1]):
            return True
    for g in IGNORED_FILE_GLOBS:
        if fnmatch.fnmatch(name, g):
            return True
    return False


def walk_local():
    out = {}
    for dirpath, dirnames, filenames in os.walk(ROOT):
        dirnames[:] = [d for d in dirnames if d not in IGNORED_DIRS
                       and not any(fnmatch.fnmatch(d, g) for g in IGNORED_DIR_GLOBS)]
        rel_dir = os.path.relpath(dirpath, ROOT)
        if rel_dir == ".":
            rel_dir = ""
        # 剔除 tools/.rule_cache
        dirnames[:] = [d for d in dirnames
                       if (rel_dir.replace("\\", "/"), d) not in IGNORED_SUBDIRS]
        for fn in filenames:
            rel = os.path.normpath(os.path.join(rel_dir, fn)).replace("\\", "/")
            if ignored(rel):
                continue
            abs_p = os.path.join(dirpath, fn)
            out[rel] = abs_p
    return out


def blob_sha(path):
    with open(path, "rb") as f:
        data = f.read()
    h = hashlib.sha1()
    h.update(b"blob %d\x00" % len(data))
    h.update(data)
    return h.hexdigest(), data


def api_req(method, url, body=None):
    req = urllib.request.Request(url, method=method)
    req.add_header("Authorization", "Bearer " + TOKEN)
    req.add_header("User-Agent", "Mahiru-push")
    req.add_header("Accept", "application/vnd.github+json")
    data = None
    if body is not None:
        data = json.dumps(body).encode("utf-8")
        req.add_header("Content-Type", "application/json")
    try:
        with urllib.request.urlopen(req, data=data, timeout=60) as r:
            return json.loads(r.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        raw = e.read().decode("utf-8", "replace")
        raise RuntimeError("%s %s -> %s %s" % (method, url, e.code, raw[:500]))


def get_remote_tree(head):
    tree = api_req("GET", "%s/repos/%s/git/trees/%s?recursive=1"
                   % (API, REPO, head))
    manifest = {}
    for e in tree["tree"]:
        if e["type"] == "blob":
            manifest[e["path"]] = e["sha"]
    return manifest


def main():
    dry = "--execute" not in sys.argv
    remote_head = get_remote_head()
    local = walk_local()
    remote = get_remote_tree(remote_head)

    add = {}       # path -> abs
    changed = {}   # path -> abs (content sha differs)
    same = {}      # path -> (abs, blobsha)
    deleted = sorted(set(remote) - set(local))

    for path, abs_p in sorted(local.items()):
        sha, _ = blob_sha(abs_p)
        if path in remote:
            if remote[path] == sha:
                same[path] = abs_p
            else:
                changed[path] = abs_p
        else:
            add[path] = abs_p

    print("本地文件(跟踪): %d" % len(local))
    print("远程 blob: %d" % len(remote))
    print("  未变(复用): %d" % len(same))
    print("  新增: %d" % len(add))
    print("  变更: %d" % len(changed))
    print("  删除: %d" % len(deleted))
    for p in deleted:
        print("    DEL %s" % p)
    total_upload = len(add) + len(changed)
    upload_bytes = 0
    for abs_p in list(add.values()) + list(changed.values()):
        upload_bytes += os.path.getsize(abs_p)
    print("需上传 blob: %d 个, 合计 %.2f MB" % (total_upload, upload_bytes / 1048576))

    if dry:
        print("\n[DRY RUN] 不写远程。加 --execute 执行。")
        return

    # 上传新增/变更的 blob
    new_shas = {}
    for i, (path, abs_p) in enumerate(sorted(list(add.items()) + list(changed.items())), 1):
        sha, data = blob_sha(abs_p)
        b64 = base64.b64encode(data).decode("ascii")
        r = api_req("POST", "%s/repos/%s/git/blobs" % (API, REPO),
                    {"content": b64, "encoding": "base64"})
        if r["sha"] != sha:
            raise RuntimeError("blob sha mismatch for %s" % path)
        new_shas[path] = sha
        print("[%d/%d] blob %s (%d B)" % (i, total_upload, path, len(data)))

    # 组装完整 tree（含删除=不出现）
    entries = []
    for path, abs_p in sorted(same.items()):
        entries.append({"path": path, "mode": "100644", "type": "blob",
                        "sha": blob_sha(abs_p)[0]})
    for path, abs_p in sorted(add.items()):
        entries.append({"path": path, "mode": "100644", "type": "blob",
                        "sha": new_shas[path]})
    for path, abs_p in sorted(changed.items()):
        entries.append({"path": path, "mode": "100644", "type": "blob",
                        "sha": new_shas[path]})

    tree = api_req("POST", "%s/repos/%s/git/trees" % (API, REPO),
                   {"tree": entries})
    print("tree 创建成功: %s (entries=%d)" % (tree["sha"], len(entries)))

    now = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    commit = api_req("POST", "%s/repos/%s/git/commits" % (API, REPO), {
        "message": "Mahiru 全面升级：Zapier 设计皮肤 + WinHance 游戏与性能模块 + LightC 清理规则 + 设置页重塑与改名",
        "tree": tree["sha"],
        "parents": [remote_head],
        "author": {"name": "decaycc", "email": "decaycc@users.noreply.github.com", "date": now},
        "committer": {"name": "decaycc", "email": "decaycc@users.noreply.github.com", "date": now},
    })
    print("commit 创建成功: %s" % commit["sha"])

    ref = api_req("PATCH", "%s/repos/%s/git/refs/heads/main" % (API, REPO),
                  {"sha": commit["sha"], "force": False})
    print("main 已更新: %s -> %s" % (ref["ref"], ref["object"]["sha"]))
    print("DONE")


if __name__ == "__main__":
    main()
