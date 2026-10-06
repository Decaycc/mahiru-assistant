## mahiru小助手 v1.0.1

**这是一个安全性修复版本，建议所有 v1.0.0 用户更新。**

### 修复了什么

v1.0.0 的「开发构建残留（node_modules / __pycache__ / venv）」规则
**只按目录名匹配**，会把**已安装软件内部的 `node_modules`** 也当成构建残留。

实测在一台机器上命中 200 个目录，其中这 3 个是**已安装应用的运行依赖**：

```
D:\dsh\resources\app.asar.unpacked\dsh\node_modules
D:\workbuddy\resources\app.asar.unpacked\node_modules
D:\workbuddy\resources\app.asar.unpacked\cli\node_modules
```

删掉它们，**DSH 和 WorkBuddy 会直接起不来**。
另外还有 193 个 `__pycache__`，其中一批属于应用自带的 Python 运行时。

### 怎么修的

加了**路径黑名单** `_TYPES_DENY_SUBSTR`：属于「已安装软件 / 运行环境」的路径，
目录名再像也不碰。

```
app.asar                  Electron 打包目录
\resources\app            应用安装目录
\Program Files            系统安装位置
\Windows\
\python\lib\              解释器标准库
\lib\site-packages\       第三方包
\node_modules\            嵌套的（外层已覆盖）
\.dsh\dsh-runtimes\       DSH 自带运行时
\AppData\                 应用数据
```

**效果**：本机命中数 **200 → 8**，且**不再包含任何已安装软件**。

### 仍然要注意

这条规则会删除**带 `pyvenv.cfg` 的真实虚拟环境** —— 包括你自己项目的 `venv`。
它本来就是给「磁盘实在紧张、确定不要那些虚拟环境了」的场景用的，
**默认不勾选**。清理前请务必先看扫描预览。

### 下载

**`mahiru-assistant-v1.0.1.exe`** · 13.26 MB · Windows 10/11 · 单文件绿色版

**SHA256**（下载后可校验）：

```
17c6e450acdd7dc4937f80bc8fb3b01038bab3d9e7f7b09dc847ebbfd9b37027
```

```powershell
Get-FileHash .\mahiru-assistant-v1.0.1.exe -Algorithm SHA256
```

### 首次运行提示

如果弹出「Windows 已保护你的电脑」：点 **更多信息** → **仍要运行**。
这是因为软件没有数字签名（个人项目没买证书），不是有毒。
用上面的 SHA256 校验比签名更能说明问题。

### 其他

- 内存优化、垃圾清理、游戏优先级、小功能四项均与 v1.0.0 相同
- 内置 6 项回归测试 + 6 阶段界面冒烟，全部通过
- 第三方规则来源与许可见仓库里的 `THIRD_PARTY_NOTICES.md`
