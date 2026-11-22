# 第三方资源与许可

本项目的**代码**由 decaycc 编写。以下第三方资源被使用或派生了数据，
各自的许可以本节为准。

---

## 1. 清理规则（派生数据）

`app/core/third_party_rules.py` 与 `GameBoost/third_party_rules.py`
是**衍生数据**，由 `tools/update_rules.py` 从下面三个开源规则库生成。
生成文件头部已写入来源、版本与许可。

| 来源 | 地址 | 许可 | 本次版本 |
|---|---|---|---|
| Winapp2.ini | https://github.com/MoscaDotTo/Winapp2 | CC-BY-SA-4.0 | 260915 / 4068 条 |
| Winapp3.ini | 同上 `Winapp3/` 目录 | CC-BY-SA-4.0 | 251007 / 855 条 |
| BleachBit | https://github.com/bleachbit/bleachbit | GPL-3.0-or-later | 108 个 cleaner |

### ⚠ Winapp3 的额外要求

Winapp3.ini 的许可里比 Winapp2 多写了一句：

> If you plan on modifying, distributing, and/or hosting Winapp3.ini for your
> own program or website, please ask first.

**自用没问题**；如果要公开发布本工具，建议先联系对方打个招呼，
或用 `python tools/update_rules.py --no-winapp3` 生成不含 Winapp3 的规则。

### 派生说明

生成过程只做**过滤与改写**，不复制原始规则文件本身：

- 只保留指向「缓存 / 日志 / 临时」类目录的路径，并转成带占位符的模板
- 明确剔除 Cookie、历史、密码、书签、表单、会话、IndexedDB、localStorage
- 剔除反作弊目录、裸通配目录名、Windows 系统目录
- 输出为 Python 列表常量

因此本仓库**不包含** Winapp2.ini / Winapp3.ini / BleachBit 的原始文件。
需要原始数据请从上述地址自行获取。

---

## 2. 图标插画

`design/mahiru-source.jpg`、`design/icon.ico`、`design/icon.svg`、
`design/icon-*.png`、`web/assets/brand-mark*.png` 由一张第三方插画裁切而来。

- 原图来源：https://github.com/liuanhuaming03/codex-pet （`pictures/` 目录）
- 该仓库未声明明确的开源许可

**这意味着**：图标部分**不适合**随代码一起以开源许可发布。
如果本仓库要公开，建议二选一：

1. 把 `design/mahiru-source.jpg` 与裁切产物换成自己画的 / 有明确许可的素材
2. 保留代码开源，但在 README 里说明图标素材不随许可授予

`design/make_icon.py` 是裁切脚本，重跑需要自备原图
（放到 `design/mahiru-source.jpg`，或用环境变量 `MAHIRU_SRC_IMAGE` 指定目录）。

---

## 3. 运行时依赖

| 包 | 许可 | 用途 |
|---|---|---|
| pywebview | BSD-3-Clause | 界面外壳（WebView2 宿主） |
| pythonnet | MIT | pywebview 在 Windows 上的依赖 |
| PyInstaller | GPL-2.0-with-exception | 打包（仅构建期，产物不受 GPL 约束） |
| Microsoft Edge WebView2 Runtime | 微软专有（可自由再分发） | 渲染界面，系统自带或由安装器部署 |

打包产物内含上述依赖，分发时请遵守各自许可。
