# -*- coding: utf-8 -*-
"""GameBoost Next 图标生成（最终版）

流程：
  1. 从源图按比例裁出头部方形（保证整个头含头发完整入框）
  2. 每个尺寸单独缩放
  3. 手动打包多尺寸 ICO（Pillow 的 save(sizes=) 只能对同一张图缩放，
     无法为不同尺寸提供不同裁切，所以自己打包：6 字节头 + 每帧 16 字节目录项 + PNG）

源图：codex-pet 仓库 pictures/ 里的高分辨率椎名真昼插画（986x1643）。
精灵图（89x182）分辨率太低，放大到 256 会糊，已弃用。
"""
import glob
import io
import os
import shutil
import struct
import sys

from PIL import Image

# 路径按本文件位置推导，不写死机器路径。
# 源图（插画原图）不入库 —— 它是第三方作品，仓库里只放裁好的成品图标。
# 需要重新生成时用环境变量指定原图目录：
#     set MAHIRU_SRC_IMAGE=D:\some\pictures
SRC_DIR = os.environ.get("MAHIRU_SRC_IMAGE", "")
OUT = os.path.dirname(os.path.abspath(__file__))
CHOSEN = 6      # 秋冬限定_2：暖色调、正面清晰

# 裁切参数（由 10% 网格标尺读出）
#   头发顶 ≈ y 7.5% (123px)，下巴 ≈ y 34.7% (570px) → 头高约 447px
#   脸中心 x ≈ 42%
FACE_X, FACE_Y, SIDE = 0.42, 0.215, 0.53
# 界面内品牌标的裁切：比图标更紧，只留脸与头发。
# 侧栏只有 30px，带上衣领和围巾会把脸挤小，看不清五官。
BRAND_Y, BRAND_SIDE = 0.225, 0.36

ICO_SIZES = [256, 128, 64, 48, 32, 24, 16]


def main():
    # 已经裁好的原图就放在 design/ 下（mahiru-source.jpg），优先用它，
    # 这样重跑不需要再去外部找原图。
    kept = os.path.join(OUT, "mahiru-source.jpg")
    if not SRC_DIR:
        if not os.path.isfile(kept):
            print("缺少原图。请二选一：\n"
                  "  1) 把原图放到 design/mahiru-source.jpg\n"
                  "  2) 用环境变量 MAHIRU_SRC_IMAGE 指定原图所在目录",
                  file=sys.stderr)
            return 2
        src_path = kept
    else:
        files = sorted(
            p for p in glob.glob(os.path.join(SRC_DIR, "**", "*"), recursive=True)
            if os.path.isfile(p) and p.lower().endswith((".png", ".jpg", ".jpeg")))
        if not files:
            print(f"{SRC_DIR} 下没有图片", file=sys.stderr)
            return 2
        src_path = files[min(CHOSEN, len(files) - 1)]
        shutil.copyfile(src_path, kept)     # 存一份，之后可复现

    src = Image.open(src_path).convert("RGB")

    w, h = src.size
    side = int(w * SIDE)
    cx, cy = int(w * FACE_X), int(h * FACE_Y)
    left = max(0, min(w - side, cx - side // 2))
    top = max(0, min(h - side, cy - side // 2))
    head = src.crop((left, top, left + side, top + side))
    head.save(os.path.join(OUT, "icon-source.png"))
    print(f"源图 {src.size} -> 头部裁切 {head.size} @ ({left},{top})")

    # 品牌标：更紧的头部特写
    bside = int(w * BRAND_SIDE)
    bx, by = int(w * FACE_X), int(h * BRAND_Y)
    bl = max(0, min(w - bside, bx - bside // 2))
    bt = max(0, min(h - bside, by - bside // 2))
    brand = src.crop((bl, bt, bl + bside, bt + bside))
    brand.resize((96, 96), Image.LANCZOS).save(
        os.path.join(OUT, "brand-mark@2x.png"))
    brand.resize((48, 48), Image.LANCZOS).save(
        os.path.join(OUT, "brand-mark.png"))
    print(f"品牌标裁切 {brand.size} @ ({bl},{bt})")

    # 打包多尺寸 ICO
    blobs = []
    for s in ICO_SIZES:
        buf = io.BytesIO()
        head.resize((s, s), Image.LANCZOS).save(buf, format="PNG")
        blobs.append((s, buf.getvalue()))
    header = struct.pack("<HHH", 0, 1, len(blobs))
    offset = 6 + 16 * len(blobs)
    dirent, body = b"", b""
    for s, png in blobs:
        dim = 0 if s >= 256 else s
        dirent += struct.pack("<BBBBHHII", dim, dim, 0, 0, 1, 32, len(png), offset)
        offset += len(png)
        body += png
    ico = os.path.join(OUT, "icon.ico")
    with open(ico, "wb") as f:
        f.write(header + dirent + body)
    print(f"icon.ico  {os.path.getsize(ico)} bytes / {len(blobs)} 帧")

    # 预览
    head.resize((256, 256), Image.LANCZOS).save(os.path.join(OUT, "icon-256.png"))
    row = Image.new("RGB", (256 + 24 + 96 + 24 + 64 + 24 + 32 + 24 + 16 + 40, 300),
                    (255, 255, 255))
    x = 12
    for s in (256, 96, 64, 32, 16):
        row.paste(head.resize((s, s), Image.LANCZOS), (x, 20))
        x += s + 24
    row.save(os.path.join(OUT, "icon-sizes.png"))

    # 回读校验
    im = Image.open(ico)
    print("回读帧:", sorted(s[0] for s in im.info.get("sizes", [])))


if __name__ == "__main__":
    main()
