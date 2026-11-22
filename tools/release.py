# -*- coding: utf-8 -*-
"""创建 GitHub Release 并上传 exe 资产。

用法：
  $env:GH_TOKEN = "<PAT>"
  python tools/release.py --dry-run
  python tools/release.py --execute

版本号从 --tag 读取，默认 v1.1.0；资产与说明按版本号自动拼接。
"""
import base64
import json
import os
import sys
import urllib.request
import urllib.error

API = "https://api.github.com"
REPO = "Decaycc/mahiru-assistant"
TOKEN = os.environ.get("GH_TOKEN", "")
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
import argparse

_ap = argparse.ArgumentParser(add_help=False)
_ap.add_argument("--tag", default="v1.1.0")
_known, _ = _ap.parse_known_args()
TAG = _known.tag
# 产物统一放在仓库外的 builds 目录（见 tools\build.py 的 DEFAULT_OUT）
ASSET = os.environ.get("MAHIRU_ASSET") or os.path.join(
    os.path.expanduser("~"), "Desktop", "mahiru-assistant-%s.exe" % TAG)
NOTES = os.path.join(ROOT, "design", "release-notes-%s.md" % TAG.lstrip("v"))


def api_req(method, url, body=None, headers=None, raw_ok=False):
    req = urllib.request.Request(url, method=method)
    req.add_header("Authorization", "Bearer " + TOKEN)
    req.add_header("User-Agent", "Mahiru-release")
    req.add_header("Accept", "application/vnd.github+json")
    if headers:
        for k, v in headers.items():
            req.add_header(k, v)
    data = None
    if body is not None:
        data = json.dumps(body).encode("utf-8")
        req.add_header("Content-Type", "application/json")
    try:
        with urllib.request.urlopen(req, data=data, timeout=120) as r:
            raw = r.read()
            return json.loads(raw.decode("utf-8")) if not raw_ok else raw
    except urllib.error.HTTPError as e:
        raw = e.read().decode("utf-8", "replace")
        raise RuntimeError("%s %s -> %s %s" % (method, url, e.code, raw[:800]))


def main():
    dry = "--execute" not in sys.argv
    with open(NOTES, "r", encoding="utf-8") as f:
        notes = f.read()

    # 检查 tag 是否已存在
    try:
        existing = api_req("GET", "%s/repos/%s/releases/tags/%s" % (API, REPO, TAG))
        print("tag %s 已存在（release id=%s）" % (TAG, existing["id"]))
        release = existing
    except RuntimeError:
        print("tag %s 不存在，将新建" % TAG)
        if dry:
            print("[DRY RUN] 将创建 release，tag=%s" % TAG)
            return
        release = api_req("POST", "%s/repos/%s/releases" % (API, REPO), {
            "tag_name": TAG,
            "target_commitish": "main",
            "name": "Mahiru %s" % TAG,
            "body": notes,
            "draft": False,
            "prerelease": False,
        })
        print("release 已创建: id=%s tag=%s" % (release["id"], release["tag_name"]))

    # 上传资产
    if not os.path.exists(ASSET):
        raise RuntimeError("找不到资产: %s" % ASSET)
    size = os.path.getsize(ASSET)
    print("资产: %s (%.2f MB)" % (ASSET, size / 1048576))

    upload_url = release["upload_url"].split("{")[0]
    url = "%s?name=%s" % (upload_url, os.path.basename(ASSET))

    if dry:
        print("[DRY RUN] 将上传到 %s" % url)
        return

    with open(ASSET, "rb") as f:
        data = f.read()

    req = urllib.request.Request(url, method="POST", data=data)
    req.add_header("Authorization", "Bearer " + TOKEN)
    req.add_header("User-Agent", "Mahiru-release")
    req.add_header("Accept", "application/vnd.github+json")
    req.add_header("Content-Type", "application/octet-stream")
    try:
        with urllib.request.urlopen(req, timeout=600) as r:
            result = json.loads(r.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        raw = e.read().decode("utf-8", "replace")
        raise RuntimeError("上传失败 %s %s" % (e.code, raw[:800]))

    print("资产已上传: %s (%d bytes)" % (result["name"], result["size"]))
    print("下载 URL: %s" % result["browser_download_url"])
    print("DONE")


if __name__ == "__main__":
    main()
