## Mahiru v1.0.2

**这是界面与功能的大版本更新，建议所有 v1.0.x 用户更新。**

### 这次更新了什么

- **全新界面**：按 Zapier 设计语言重做全部五个页面 —— 暖米画布、咖啡墨、橙色只留给主操作按钮；粉色立绘侧栏 + 莓果色导航胶囊 + 真昼（椎名真昼）表情包点缀。
- **游戏与性能**：新增 116 项 Windows 调校设置（处理器 / 显卡 / 网络 / 系统服务 / 计划任务 / 视觉效果等），每一项都带「推荐值 / 默认值」一键恢复，写注册表前自动备份旧值，危险操作有确认。
- **垃圾清理规则换成 LightC 体系**：18 个分类、71 条扫描路径，风险分 1/2/3 三档，系统托管项（如 Windows.old）默认锁定禁用。
- **设置页重塑**：软件功能说明、关于（GitHub 头像 + 作者）、软件更新检查（真实接 GitHub Releases API，有新版一键下载）。
- **改名 Mahiru**：界面、弹窗、构建产物统一改名，下载文件仍用 ASCII 名 `mahiru-assistant`。

### 下载

**`mahiru-assistant-v1.0.2.exe`** · 14.4 MB · Windows 10/11 · 单文件绿色版

**SHA256**（下载后可校验）：

```
99ae5032fd7845803fde23c25a6468fa75c9428a7f5fa17b4bbe2e4483d2cdd9
```

```powershell
Get-FileHash .\mahiru-assistant-v1.0.2.exe -Algorithm SHA256
```

### 首次运行提示

如果弹出「Windows 已保护你的电脑」：点 **更多信息** → **仍要运行**。
这是因为软件没有数字签名（个人项目没买证书），不是有毒。
用上面的 SHA256 校验比签名更能说明问题。

### 其他

- 内置 15 项验证脚本全部通过（含 LightC 规则、WinHance 调校、CSS 令牌、回收站配置等）
- 第三方规则来源与许可见仓库里的 `THIRD_PARTY_NOTICES.md`
- WinHance 调校数据源为 Winhance（PolyForm Shield 1.0.0，见 THIRD_PARTY_NOTICES）
- LightC 清理规则源为 LightC（Source Available License v1.0，见 THIRD_PARTY_NOTICES）
