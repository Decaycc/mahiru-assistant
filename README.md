# mahiru小助手

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
> `mahiru小助手.exe` 都不影响运行。

## 它做什么

| 功能 | 说明 |
|---|---|
| **内存优化** | 关闭后台常驻程序、清理进程工作集、清空待机内存列表；带保护名单，杀软/反作弊/自身进程不会被碰 |
| **游戏优先级** | 列表里挑出正在跑的游戏设优先级，可记住，下次一键应用 |
| **垃圾清理** | 50 条内置规则 + 从开源规则库衍生的 3000+ 条路径模板 |
| **规则更新** | 设置页里一键拉取 Winapp2 / Winapp3 / BleachBit 的最新规则 |
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

## 运行

需要 Windows 10/11 和 WebView2 运行时（Win11 自带，Win10 一般也有）。

### 直接用

下载 `dist/mahiru小助手.exe`，双击。**单文件、免安装**，配置写在 EXE 同级的
`config/` 里（那个目录不可写时退回 `%APPDATA%\mahiru`）。

### 从源码跑

```bat
pip install pywebview pythonnet
python run.py
```

### 自己打包

```bat
pip install pyinstaller
python tools\build.py            :: 产出 dist\mahiru小助手.exe
python tools\build.py --console  :: 保留控制台，排查启动问题
```

## 自检与验证

GUI 不好靠人眼在自动化里验证，所以内置了两套：

```bat
python app\core\selftest.py             :: 6 项回归（含真实注册表夹具）
python run.py --smoke 6                 :: 开窗跑 6 阶段冒烟并读回 DOM
mahiru小助手.exe --smoke 6              :: 打包版同样能跑，报告落在 config\
mahiru小助手.exe --update-rules         :: 无界面更新清理规则
```

冒烟报告会写到 `config/smoke_report.txt` —— windowed 打包版没有控制台，
报告必须落盘，这也让「在别人机器上跑一遍验证」成为可能。

## 目录结构

```
run.py                  打包入口（必须在包外，见 PLAN.md）
app/
  main.py               窗口、DPI、崩溃处理、--smoke / --update-rules
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
design/                 图标管线与界面风格对比
PLAN.md                 完整方案与每个里程碑的实测记录
```

> `app/core/mem.py` 与 `junk.py` 是 `tools/split_core.py` **生成**的。
> 直接改它们，下次重跑就被覆盖 —— 要改行为请改 `GameBoost/` 下的源文件，
> 或改切分器的适配步骤，然后重跑。

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
