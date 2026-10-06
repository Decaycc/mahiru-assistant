## mahiru小助手 v1.0.0

Windows 上的游戏加速与清理工具。单文件、免安装。

### 下载

点下面的 **`mahiru-assistant-v1.0.0.exe`** 直接下载，双击即用。

| | |
|---|---|
| 文件大小 | 13.26 MB |
| 运行环境 | Windows 10 / 11（需要 WebView2 运行时，Win11 自带） |
| 安装 | **不需要**，单文件绿色版 |
| 配置位置 | EXE 同级的 `config\` 目录（不可写时退回 `%APPDATA%\mahiru`） |

**校验（可选）** —— 下载后可比对 SHA256：

```
d695c12f238ccfd9bc2819e9f89c6dcdc3be83c7c1e95bf06078ae1d7017dcca
```

```powershell
Get-FileHash .\mahiru-assistant-v1.0.0.exe -Algorithm SHA256
```

### 功能

- **内存优化** —— 关闭后台常驻程序、清理进程工作集、清空待机内存列表
- **游戏优先级** —— 挑出正在跑的游戏设优先级，可记住，下次一键应用
- **垃圾清理** —— 50 条内置规则 + 3000+ 条来自开源规则库的路径模板
- **规则更新** —— 一键拉取 Winapp2 / Winapp3 / BleachBit 的最新规则
- **小功能** —— 启动项管理、硬件与磁盘健康、大文件查找、重复文件查找

### 安全设计

这个工具会**删文件**，所以安全相关的取舍都写在代码注释和 `PLAN.md` 里：

- **保护路径永不删除**：`Windows\Installer`、`WinSxS`、`System32`、`DriverStore`、页面文件等
- **隐私数据永不匹配**：Cookie / 历史 / 密码 / 书签 / 表单 / 会话 / IndexedDB
- **凭据永不触碰**：`.ssh`、`.aws`、`id_rsa` 等按路径段判定拒绝
- **不跟随重解析点**，不会绕出扫描范围
- **占用中的文件跳过，不强删**
- **启动项禁用是搬移不是删除**，随时还原
- **两个查找功能全程只列不删**

### 已知限制

- **仅 Windows**
- **「清空待机内存列表」是唯一的例外**：内核接口不区分进程，它也会清掉反作弊进程的工作集。游戏或反作弊在跑时，界面会建议改用逐个整理。
- **SMART 失败预测需要管理员权限**，普通权限下读不到时界面会如实说明
- 冷启动约 2.3 秒（onefile 每次都要解压，这是单文件形态的代价）

### 源码

完整源码在本仓库。构建自己的版本：

```bat
pip install pywebview pythonnet pyinstaller
python tools\build.py
```

内置 6 项回归测试与 6 阶段界面冒烟，打包版同样可跑：

```bat
mahiru小助手.exe --smoke 6
```

### 第三方资源

清理规则衍生自 [Winapp2](https://github.com/MoscaDotTo/Winapp2) /
[Winapp3](https://github.com/MoscaDotTo/Winapp2/tree/master/Winapp3) /
[BleachBit](https://github.com/bleachbit/bleachbit)，
图标使用的插画来自 [codex-pet](https://github.com/liuanhuaming03/codex-pet)。
详见仓库里的 `THIRD_PARTY_NOTICES.md`。
