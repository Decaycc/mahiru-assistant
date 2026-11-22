# Mahiru

Windows 上的内存优化与垃圾清理工具。打游戏前腾一下内存、清掉攒下来的缓存，
点几下就完事。

作者 [decaycc](https://github.com/Decaycc)。

## 下载

单文件 EXE，解压即用，不需要安装：

**[Mahiru.exe](https://github.com/Decaycc/mahiru-assistant/releases/latest/download/Mahiru.exe)**

Windows 10 / 11 · 约 14 MB · 绿色版

第一次运行 Windows 可能弹「已保护你的电脑」，点「更多信息」→「仍要运行」即可。
这是因为 EXE 没有代码签名证书，不是病毒。Release 页附了 SHA256，可以自行校验。

## 功能

**内存优化** — 关闭后台常驻程序、清理进程工作集、清空待机内存列表。
带保护名单，杀软、反作弊、输入法、驱动配套进程不会被结束。

**游戏优先级** — 从运行中的程序里挑出游戏设优先级，可记住配置，下次一键应用。

**垃圾清理** — 内置规则 + 从开源规则库衍生的路径模板，覆盖系统缓存、浏览器、
开发工具、游戏平台，以及微信/QQ/钉钉/飞书/WPS 等国内常用软件。
支持「移入回收站」代替直接删除。

**规则更新** — 设置页可拉取规则库最新版本，也能一键退回内置版。

**系统服务** — 打游戏时可选停掉搜索索引、遥测、Xbox 等服务，用完一键还原。

## 安全

这个工具会删文件，所以几个关键约束写在代码里：

- 保护路径永不删除：`Windows\Installer`、`WinSxS`、`System32`、`DriverStore`、页面文件
- 隐私数据永不匹配：Cookie、历史、密码、书签、表单、会话、IndexedDB
- 凭据目录永不触碰：`.ssh`、`.aws`、`id_rsa` 等按路径段判定
- 不跟随重解析点，不会绕出扫描范围
- 正在被占用的文件跳过，不强删
- 回收站不可用时（卷被禁用、容量为 0、单条目超限）跳过并说明原因，不会降级成永久删除
- 界面传入的路径不可信，扫描根走白名单，进程保护状态在核心层再校验一次
- 启动项禁用是搬移而非删除，随时可还原
- 出包前强制跑验证脚本，任何一项不过就停止出包

删除路径上的这些保证由 `tools\run_checks.py` 覆盖。

## 运行

需要 Windows 10/11 和 WebView2。Win11 自带，Win10 一般随系统更新装上。
没有的话程序会提示你去装，而不是开一个白窗口。

### 从源码

```bat
pip install pywebview pythonnet
python run.py
```

### 打包

```bat
pip install pyinstaller
python tools\build.py
python tools\build.py --console   :: 保留控制台，方便看启动错误
```

## 验证

```bat
python app\core\selftest.py         :: 底层接口自检
python run.py --smoke 6             :: 开窗跑冒烟测试，读回 DOM 断言
Mahiru.exe --update-rules           :: 无界面更新清理规则
python tools\run_checks.py          :: 跑删除路径上的全部回归
```

`run_checks.py` 的脚本会真造夹具、真走删除流程，但只动
`%USERPROFILE%\.mahiru_fixture`，跑前跑后都清理，不碰真实文件。

## 目录

```
run.py                 打包入口
app/
  main.py              窗口、DPI、崩溃处理、WebView2 检查
  bridge.py            对 JS 暴露的 Api 类
  paths.py             只读资源 / 可写数据分离
  elevation.py         UAC 检测与提权重启
  core/
    mem.py             内存优化
    junk.py            垃圾清理
    services.py        系统服务控制
    tools.py           小工具
    rule_update.py     规则下载与生成
    selftest.py        回归测试
web/                   界面（原生 HTML/CSS/JS，无框架）
tools/                 构建与验证
design/                图标、界面规范、发版说明
```

## 已知限制

- 仅支持 Windows。内存部分走 NT 原生接口，换平台要重写。
- 清空待机内存列表不区分进程，反作弊的工作集也会被清。正在游戏时建议改用
  逐个整理，界面会给出提示。
- SMART 失败预测需要管理员权限，普通权限下读不到。
- 单文件打包版冷启动约 2 秒，每次启动都要解压，这是 onefile 的代价。

## 第三方资源

清理规则衍生自开源规则库，图标使用第三方插画。
具体来源与许可证见 [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md)。

## 许可

代码许可见 [LICENSE](LICENSE)。
第三方派生数据以其自身许可证为准，详见 THIRD_PARTY_NOTICES.md。
