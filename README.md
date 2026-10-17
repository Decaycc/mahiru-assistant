# Mahiru

Windows 上的游戏加速与清理工具。把「打游戏前腾一下内存、清一下垃圾」这件事
做成点几下就完的界面。

> 作者：**decaycc**

## 下载

**不用装、不用编译，直接下这个单文件 EXE 双击运行：**

### ⬇️ [mahiru-assistant-v1.0.1.exe](https://github.com/Decaycc/mahiru-assistant/releases/latest/download/mahiru-assistant-v1.0.1.exe)

13.26 MB · Windows 10/11 · 单文件绿色版

想先看版本说明或校验哈希：[Releases 页面](https://github.com/Decaycc/mahiru-assistant/releases)

> 文件叫 `mahiru-assistant-v1.0.1.exe` 而不是中文名，是因为 GitHub 的
> Release 资产用非 ASCII 文件名会上传失败（踩过，报 422）。下载后随便改回
> `Mahiru.exe` 都不影响运行。

### 第一次运行时 Windows 会拦一下，这是正常的

双击之后如果弹出蓝色的「**Windows 已保护你的电脑**」，那**不是**查出了病毒 ——
SmartScreen 只是在说「这个 EXE 没有数字签名，我头一次见」。代码签名证书要按年
买，个人项目没买，所以每个没签名的独立软件都会有这一步。

做法：点「**更多信息**」→「**仍要运行**」。只需要做一次。

少数杀软还会因为「这个程序会删文件」这个**行为**报毒 —— 那是启发式误报。
想自己核对的话有两条路：

- Release 页面里附了 SHA256，下完先比对一下
- 源码全在这个仓库里，可以照着 `python tools\build.py` 自己打一份，
  对比是不是同一个东西

## 它做什么

| 功能 | 说明 |
|---|---|
| **内存优化** | 关闭后台常驻程序、清理进程工作集、清空待机内存列表；带保护名单，杀软/反作弊/自身进程不会被碰 |
| **游戏优先级** | 列表里挑出正在跑的游戏设优先级，可记住，下次一键应用 |
| **垃圾清理** | 50 条内置规则 + 从开源规则库衍生的 3000+ 条路径模板；清理时可以选「移入回收站」而不是直接删 |
| **规则更新** | 设置页里一键拉取 Winapp2 / Winapp3 / BleachBit / MultronWcleaner 的最新规则，也能一键退回内置版 |
| **小功能** | 启动项管理、硬件与磁盘健康、大文件查找、重复文件查找 |

## 安全设计

这个工具会**删文件**，所以安全相关的取舍都写在代码注释和 `PLAN.md` 里：

- **保护路径永不删除**：`Windows\Installer`、`WinSxS`、`System32`、`DriverStore`、页面文件等
- **隐私数据永不匹配**：Cookie / 历史 / 密码 / 书签 / 表单 / 会话 / IndexedDB
- **凭据永不触碰**：`.ssh`、`.aws`、`id_rsa` 等按段判定拒绝
- **不跟随重解析点**，不会绕出扫描范围
- **占用中的文件跳过，不强删**
- **界面传入的路径一律不可信**：扫描根走白名单，进程在核心层重新校验一次保护状态
- **启动项禁用是搬移不是删除**：值在活动键与禁用区之间移动，随时还原
- **两个查找功能全程只列不删**
- **回收站不可用时拒绝删除**：卷的回收站被关掉、容量为 0、或单个条目超过上限时，
  操作会被**跳过**并说明原因 —— 绝不悄悄降级成永久删除
- **出包前强制跑验证**：`tools\build.py` 会先跑 `tools\run_checks.py`，任何一项
  不过就停止出包（`--skip-checks` 是逃生口）

## 运行

需要 Windows 10/11 和 WebView2 运行时。Win11 自带；Win10 一般由系统更新装上。

> 万一没有：程序会在开窗前**明确告诉你**去装，而不是开一个白屏的窗口。
> 界面用的是 ES6，而缺少 WebView2 时 pywebview 会静默降级到 IE 内核，
> 那种情况下白屏是必然的 —— 所以这里宁可拦住。

### 直接用

下载 `dist/Mahiru.exe`，双击。**单文件、免安装**，配置写在 EXE 同级的
`config/` 里（那个目录不可写时退回 `%APPDATA%\mahiru`）。

### 从源码跑

```bat
pip install pywebview pythonnet
python run.py
```

### 自己打包

```bat
pip install pyinstaller
python tools\build.py            :: 产出 dist\Mahiru.exe
python tools\build.py --console  :: 保留控制台，排查启动问题
```

## 自检与验证

GUI 不好靠人眼在自动化里验证，所以内置了两套：

```bat
python app\core\selftest.py             :: 6 项回归（含真实注册表夹具）
python run.py --smoke 6                 :: 开窗跑 6 阶段冒烟并读回 DOM
Mahiru.exe --smoke 6              :: 打包版同样能跑，报告落在 config\
Mahiru.exe --update-rules         :: 无界面更新清理规则
```

删除路径上的安全保证（保护清单、回收站降级、规则构建、界面接线）由
`tools\run_checks.py` 统一跑一遍：

```bat
python tools\run_checks.py              :: 跑完 tools\verify\ 下全部脚本
python tools\run_checks.py --list       :: 只列出来
python tools\run_checks.py --only recycle   :: 只跑名字含 recycle 的
```

这些脚本会真造夹具、真走删除流程，但**只动
`%USERPROFILE%\.mahiru_fixture`**（跑前跑后都会清），不会碰你的真实文件。

冒烟报告会写到 `config/smoke_report.txt` —— windowed 打包版没有控制台，
报告必须落盘，这也让「在别人机器上跑一遍验证」成为可能。

## 目录结构

```
run.py                  打包入口（必须在包外，见 PLAN.md）
app/
  main.py               窗口、DPI、崩溃处理、WebView2 检查、--smoke / --update-rules
  bridge.py             唯一对 JS 暴露的 Api 类
  paths.py              只读资源 / 可写数据分离（onefile 关键）
  elevation.py          UAC 检测与提权重启
  core/
    mem.py              内存优化核心（切分器生成）
    junk.py             垃圾清理核心（切分器生成）
    tools.py            小功能（手写）
    rule_update.py      规则下载与生成（手写）
    selftest.py         回归测试
web/                    界面（原生 HTML/CSS/JS，无框架）
tools/                  构建、截图、规则更新等开发工具
  verify/               删除路径上的安全回归脚本（run_checks.py 调用）
design/                 图标管线与界面风格对比
DESIGN.md               界面设计规范（Al Jazeera 编辑部语言；令牌以它为准）
PLAN.md                 完整方案与每个里程碑的实测记录
```

> `app/core/mem.py` 与 `junk.py` **就是源文件，直接改即可**。
> `tools/split_core.py` 是重构期一次性用过的切分器（把早期的 `gameboost.py` /
> `junkclean.py` 拆成现在这两个模块），**已经不在工作流里**：它依赖的
> `GameBoost/` 目录在本仓库不存在，重跑它不会覆盖任何东西。
> 要改行为就直接改 `app/core/` 下的文件，然后跑一遍 `app/core/selftest.py`。

## 已知限制

- **仅 Windows**。内存接口走的是 NT 原生调用，换平台要重写。
- **清空待机内存列表是唯一的例外**：内核接口不区分进程，所以它**也会清掉
  反作弊进程的工作集**。游戏或反作弊在跑时，界面会建议改用逐个整理。
- **SMART 失败预测需要管理员权限**，普通权限下读不到，界面会如实说明。
- 打包版冷启动约 2.3 秒（onefile 每次都要解压，这是单文件形态的代价）。

## 第三方资源

清理规则衍生自开源规则库，图标使用了第三方插画 ——
详见 [`THIRD_PARTY_NOTICES.md`](THIRD_PARTY_NOTICES.md)。

## 许可

本仓库代码：见 [`LICENSE`](LICENSE)。
第三方派生数据的许可以 `THIRD_PARTY_NOTICES.md` 为准。
