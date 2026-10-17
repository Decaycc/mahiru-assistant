# -*- coding: utf-8 -*-
"""LightC 垃圾清理规则库（**生成文件，勿手改**）。

由 tools/gen_lightc_rules.py 从 lightc-rules.json 生成，共 18 条规则。

来源：LightC（Chunyu33/light-c），src-tauri/src/scanner/categories.rs
     的 JunkCategory::all() 18 个分类。
许可：LightC Source Available License v1.0，Copyright (c) 2026 Evan Lau，
     **非开源**（第 7 条声明）。规则表属其实质内容，复用受其第 2 条限制。

风险映射：LightC risk 1/2/3 → junk level safe/caution/risky。
locked（仅 OldWindowsInstallation，is_system_managed=true）→ risky + locked 标志，
前端整片禁用勾选，只引导系统磁盘清理。

本模块在 import 时引用 junk 的运行时环境常量还原路径，
因此在任何机器上跑都跟随该机器的真实环境变量。
"""

from __future__ import annotations

from app.core import junk as _j


def _r(key, name, category, level, kind, paths, desc, default,
      patterns=(), locked=False, system_managed=False, source=""):
    """用 junk._rule 造规则，再补 LightC 独有的字段。"""
    r = _j._rule(key, name, category, level, kind, paths, desc,
                 default=default, patterns=patterns)
    if locked or system_managed:
        r["locked"] = True
        r["system_managed"] = bool(system_managed)
    r["source"] = source
    return r


# 18 条规则，顺序与 categories.rs 的 JunkCategory::all() 一致。
LIGHTC_RULES: list[dict] = [
    # WindowsTemp — categories.rs:143-148
    _r('lightc_windows_temp', 'Windows 临时文件', '临时文件', 'safe', 'contents',
       [_j.TEMP, _j.TEMP, _j._join(_j.WINDIR, 'Temp')],
       '系统和程序的临时文件。删除后会自动重建，是最值得清理的一项。', default=True, patterns=['*'],
       locked=False, system_managed=False, source='categories.rs:143-148'),

    # SystemCache — categories.rs:149-154
    _r('lightc_system_cache', '系统缓存', '系统缓存', 'risky', 'contents',
       [_j._join(_j.WINDIR, 'Prefetch'), _j._join(_j.LOCAL, 'Microsoft', 'Windows', 'Caches')],
       '系统预读取缓存（Prefetch）与 Windows 缓存目录。\n删除后系统启动与程序首次启动会变慢，之后自动重建。', default=False, patterns=['*'],
       locked=False, system_managed=False, source='categories.rs:149-154'),

    # BrowserCache — categories.rs:155-227
    _r('lightc_browser_cache', '浏览器缓存', '浏览器缓存', 'caution', 'contents',
       [_j._join(_j.LOCAL, 'Microsoft', 'Windows', 'INetCache'), _j._join(_j.LOCAL, 'Google', 'Chrome', 'User Data', 'Default', 'Cache'), _j._join(_j.LOCAL, 'Google', 'Chrome', 'User Data', 'Default', 'Code Cache'), _j._join(_j.LOCAL, 'Google', 'Chrome', 'User Data', 'Default', 'GPUCache'), _j._join(_j.LOCAL, 'Google', 'Chrome', 'User Data', 'Profile *', 'Cache'), _j._join(_j.LOCAL, 'Google', 'Chrome', 'User Data', 'Profile *', 'Code Cache'), _j._join(_j.LOCAL, 'Google', 'Chrome', 'User Data', 'ShaderCache'), _j._join(_j.LOCAL, 'Microsoft', 'Edge', 'User Data', 'Default', 'Cache'), _j._join(_j.LOCAL, 'Microsoft', 'Edge', 'User Data', 'Default', 'Code Cache'), _j._join(_j.LOCAL, 'Microsoft', 'Edge', 'User Data', 'Default', 'GPUCache'), _j._join(_j.LOCAL, 'Microsoft', 'Edge', 'User Data', 'Profile *', 'Cache'), _j._join(_j.LOCAL, 'Microsoft', 'Edge', 'User Data', 'Profile *', 'Code Cache'), _j._join(_j.LOCAL, 'Microsoft', 'Edge', 'User Data', 'ShaderCache'), _j._join(_j.LOCAL, 'Mozilla', 'Firefox', 'Profiles', '*', 'cache2'), _j._join(_j.ROAMING, 'Mozilla', 'Firefox', 'Profiles', '*', 'cache2'), _j._join(_j.LOCAL, 'BraveSoftware', 'Brave-Browser', 'User Data', 'Default', 'Cache'), _j._join(_j.LOCAL, 'BraveSoftware', 'Brave-Browser', 'User Data', 'Default', 'Code Cache'), _j._join(_j.ROAMING, 'Opera Software', 'Opera Stable', 'Cache'), _j._join(_j.LOCAL, 'Tencent', 'QQBrowser', 'User Data', 'Default', 'Cache'), _j._join(_j.LOCAL, 'Tencent', 'QQBrowser', 'User Data', 'Default', 'Code Cache'), _j._join(_j.LOCAL, '360Chrome', 'Chrome', 'User Data', 'Default', 'Cache'), _j._join(_j.LOCAL, '360Chrome', 'Chrome', 'User Data', 'Default', 'Code Cache'), _j._join(_j.LOCAL, '360se6', 'User Data', 'Default', 'Cache'), _j._join(_j.LOCAL, 'UCBrowser', 'User Data', 'Default', 'Cache'), _j._join(_j.LOCAL, 'Vivaldi', 'User Data', 'Default', 'Cache'), _j._join(_j.LOCAL, 'YandexBrowser', 'User Data', 'Default', 'Cache'), _j._join(_j.LOCAL, 'CentBrowser', 'User Data', 'Default', 'Cache')],
       '浏览器网页缓存、脚本缓存、GPU 缓存与着色器缓存，覆盖 Edge/Chrome/Firefox/Brave/Opera/QQ浏览器/360 等。\n不影响收藏夹、密码与登录状态。', default=True, patterns=['*'],
       locked=False, system_managed=False, source='categories.rs:155-227'),

    # RecycleBin — categories.rs:228-231
    _r('lightc_recycle_bin', '回收站', '回收站', 'risky', 'recyclebin',
       ["::recyclebin::"],
       '清空回收站。\n注意：这是永久删除，清空后无法还原。', default=False, patterns=[],
       locked=False, system_managed=False, source='categories.rs:228-231'),

    # WindowsUpdate — categories.rs:232-235
    _r('lightc_windows_update', 'Windows 更新缓存', '更新残留', 'caution', 'contents',
       [_j._join(_j.WINDIR, 'SoftwareDistribution', 'Download')],
       '已下载的 Windows 更新包。已安装的可以删，系统会重新下载需要的部分。', default=True, patterns=['*'],
       locked=False, system_managed=False, source='categories.rs:232-235'),

    # DeliveryOptimization — categories.rs:236-246
    _r('lightc_delivery_optimization', '传递优化文件', '更新残留', 'caution', 'contents',
       [_j._join(_j.WINDIR, 'SoftwareDistribution', 'DeliveryOptimization'), _j._join(_j.WINDIR, 'ServiceProfiles', 'NetworkService', 'AppData', 'Local', 'Microsoft', 'Windows', 'DeliveryOptimization', 'Cache')],
       'Windows 更新分发优化缓存（局域网/互联网共享的更新片段）。', default=True, patterns=['*'],
       locked=False, system_managed=False, source='categories.rs:236-246'),

    # WindowsDefenderCache — categories.rs:247-262
    _r('lightc_windows_defender_cache', 'Microsoft Defender 防病毒', '系统缓存', 'caution', 'contents',
       [_j._join(_j.PROGRAMDATA, 'Microsoft', 'Windows Defender', 'LocalCopy'), _j._join(_j.PROGRAMDATA, 'Microsoft', 'Windows Defender', 'Support'), _j._join(_j.PROGRAMDATA, 'Microsoft', 'Windows Defender', 'Scans', 'History', 'Service')],
       'Microsoft Defender 的本地副本、支持文件与扫描历史缓存。', default=True, patterns=['*'],
       locked=False, system_managed=False, source='categories.rs:247-262'),

    # ThumbnailCache — categories.rs:325-332
    _r('lightc_thumbnail_cache', '缩略图缓存', '系统缓存', 'safe', 'files',
       [_j._join(_j.LOCAL, 'Microsoft', 'Windows', 'Explorer'), _j._join(_j.SYSTEM_ROOT_DIR, 'Users', '*', 'AppData', 'Local', 'Microsoft', 'Windows', 'Explorer')],
       '资源管理器的缩略图与图标缓存数据库。删除后重新打开文件夹会重建。', default=True, patterns=['thumbcache_*.db', 'iconcache_*.db'],
       locked=False, system_managed=False, source='categories.rs:325-332'),

    # LogFiles — categories.rs:263-266
    _r('lightc_log_files', '日志文件', '日志与转储', 'caution', 'files',
       [_j._join(_j.WINDIR, 'Logs'), _j._join(_j.LOCAL, 'CrashDumps')],
       'Windows 日志（*.log / *.etl / *.evtx）与崩溃转储目录。', default=True, patterns=['*.log', '*.etl', '*.evtx'],
       locked=False, system_managed=False, source='categories.rs:263-266'),

    # MemoryDump — categories.rs:267-270
    _r('lightc_memory_dump', '内存转储文件', '日志与转储', 'risky', 'files',
       [_j._join(_j.WINDIR, "Minidump")],
       '蓝屏时产生的小型转储（Minidump 目录下的 *.dmp）。仅排障需要。\n完整内存镜像 MEMORY.DMP 由内置规则单独处理。', default=False, patterns=['*.dmp'],
       locked=False, system_managed=False, source='categories.rs:267-270'),

    # OldWindowsInstallation — categories.rs:271-276
    _r('lightc_old_windows_installation', '旧版 Windows 安装', '系统残留', 'risky', 'contents',
       [_j._join(_j.SYSTEM_ROOT_DIR, 'Windows.old'), _j._join(_j.SYSTEM_ROOT_DIR, '$Windows.~BT'), _j._join(_j.SYSTEM_ROOT_DIR, '$Windows.~WS')],
       '系统升级前的旧 Windows 备份与更新回滚数据。删除后无法回退。\n此项目由系统管理，本工具不直接删除，请在「磁盘清理」中处理。', default=False, patterns=['*'],
       locked=True, system_managed=True, source='categories.rs:271-276'),

    # AppCache — categories.rs:277-281
    _r('lightc_app_cache', '应用程序缓存', '应用缓存', 'risky', 'contents',
       [_j._join(_j.LOCAL, 'Microsoft', 'Windows', 'WebCache')],
       '应用程序缓存（WebCache）。', default=False, patterns=['*'],
       locked=False, system_managed=False, source='categories.rs:277-281'),

    # ThirdPartyAppCache — categories.rs:282-303
    _r('lightc_third_party_app_cache', '第三方应用缓存', '应用缓存', 'caution', 'contents',
       [_j._join(_j.ROAMING, 'discord', 'Cache'), _j._join(_j.ROAMING, 'discord', 'Code Cache'), _j._join(_j.ROAMING, 'discord', 'GPUCache'), _j._join(_j.ROAMING, 'discord', 'ShaderCache'), _j._join(_j.ROAMING, 'Slack', 'Cache'), _j._join(_j.ROAMING, 'Microsoft', 'Teams', 'Cache'), _j._join(_j.ROAMING, 'Microsoft', 'Teams', 'GPUCache'), _j._join(_j.LOCAL, 'Steam', 'htmlcache'), _j._join(_j.LOCAL, 'EpicGamesLauncher', 'Saved', 'webcache'), _j._join(_j.LOCAL, 'Netease', 'CloudMusic', 'Cache'), _j._join(_j.ROAMING, 'Tencent', 'QQMusic', 'Cache')],
       '第三方应用缓存（Discord / Slack / Teams / Steam / Epic / 网易云音乐 / QQ音乐）。', default=True, patterns=['*'],
       locked=False, system_managed=False, source='categories.rs:282-303'),

    # FontCache — categories.rs:304-307
    _r('lightc_font_cache', '字体缓存', '临时文件', 'safe', 'contents',
       [_j._join(_j.WINDIR, 'ServiceProfiles', 'LocalService', 'AppData', 'Local', 'FontCache')],
       '字体渲染缓存，自动重建。', default=True, patterns=['*'],
       locked=False, system_managed=False, source='categories.rs:304-307'),

    # WindowsErrorReports — categories.rs:308-312
    _r('lightc_windows_error_reports', 'Windows 错误报告', '日志与转储', 'caution', 'contents',
       [_j._join(_j.LOCAL, 'Microsoft', 'Windows', 'WER'), _j._join(_j.PROGRAMDATA, 'Microsoft', 'Windows', 'WER')],
       'Windows 错误报告存档与队列。', default=True, patterns=['*'],
       locked=False, system_managed=False, source='categories.rs:308-312'),

    # InstallerTemp — categories.rs:313-320
    _r('lightc_installer_temp', '安装程序临时文件', '安装残留', 'caution', 'contents',
       [_j._join(_j.WINDIR, 'Installer', '$PatchCache$'), _j._join(_j.LOCAL, 'Downloaded Installations')],
       '安装程序的补丁缓存与已下载的安装包。', default=True, patterns=['*'],
       locked=False, system_managed=False, source='categories.rs:313-320'),

    # ClipboardCache — categories.rs:321-324
    _r('lightc_clipboard_cache', '剪贴板缓存', '系统缓存', 'safe', 'contents',
       [_j._join(_j.LOCAL, 'Microsoft', 'Windows', 'Clipboard')],
       '剪贴板历史缓存。', default=True, patterns=['*'],
       locked=False, system_managed=False, source='categories.rs:321-324'),

    # ShaderCache — categories.rs:333-340
    _r('lightc_shader_cache', 'DirectX Shader 缓存', '系统缓存', 'safe', 'contents',
       [_j._join(_j.WINDIR, 'System32', 'd3d_cache'), _j._join(_j.LOCAL, 'D3DSCache'), _j._join(_j.LOCAL, 'AMD', 'DxCache'), _j._join(_j.LOCAL, 'NVIDIA', 'DXCache'), _j._join(_j.LOCAL, 'Intel', 'ShaderCache')],
       'DirectX 着色器缓存。删除后游戏首次运行会重新编译，画面异常时清它常能解决。', default=True, patterns=['*'],
       locked=False, system_managed=False, source='categories.rs:333-340'),

]


def lightc_keys() -> list[str]:
    """所有 LightC 规则的 key（verify 与覆盖过滤用）。"""
    return [r["key"] for r in LIGHTC_RULES]
