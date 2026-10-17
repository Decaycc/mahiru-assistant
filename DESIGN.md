---
version: alpha
name: mahiru — 采用 Zapier 设计语言
description: >
  mahiru 的界面改用 Zapier 的设计语言：暖米色画布 #fffefb、深咖啡墨 #201515、
  单一饱和橙 #ff4f00 做唯一的转换色（主 CTA）；层级靠表面温度（canvas / canvas-soft）
  与 1px 墨线承担，不用投影；圆角是单一的 12px 中位值（按钮与卡片同形）；
  字族是 Degular Display 的开源替身 Inter（spec 自带指引）扛显示层，其余全用 Inter。
colors:
  primary: "#ff4f00"        # Zapier Orange：唯一的主 CTA 填充
  on-primary: "#fffefb"     # 暖白：橙底/墨底上的字
  ink: "#201515"            # 深咖啡：标题、主文字、secondary 按钮填充、1px 描边
  ink-soft: "#2f2a26"       # 近黑带暖棕
  ink-mid: "#36342e"        # 中强调文字
  body: "#605d52"           # 默认正文
  body-mid: "#939084"       # 次要正文 / 元信息
  mute: "#c5c0b1"           # 最低优先级：脚注、发丝分隔
  canvas: "#fffefb"         # 暖米白页面底
  canvas-soft: "#f8f4f0"    # 奶油软面：卡片 / 内嵌区

typography:
  # Degular Display 是专有字体，spec 自带指引：显示层用 Inter 500 最接近。
  # Inter 随包内置（web/assets/fonts/），中文由 Noto Sans SC 接 —— 这是栈，不是替换。
  family: '"Inter", "Noto Sans SC", system-ui, -apple-system, sans-serif'
  display-md:   { fontSize: 32px, fontWeight: 500, lineHeight: 36px, letterSpacing: 1px }
  display-sub-sm: { fontSize: 24px, fontWeight: 600, lineHeight: 30px, letterSpacing: -0.6px }
  display-xs:   { fontSize: 20px, fontWeight: 700, lineHeight: 25px, letterSpacing: -0.5px }
  body-lg:      { fontSize: 20px, fontWeight: 400, lineHeight: 30px, letterSpacing: -0.2px }
  body-md:      { fontSize: 18px, fontWeight: 400, lineHeight: 27px }
  body-md-strong: { fontSize: 18px, fontWeight: 600, lineHeight: 27px }
  body-sm:      { fontSize: 16px, fontWeight: 400, lineHeight: 24px }
  body-sm-strong: { fontSize: 16px, fontWeight: 600, lineHeight: 24px }
  caption:      { fontSize: 14px, fontWeight: 400, lineHeight: 21px }
  eyebrow-uppercase: { fontSize: 14px, fontWeight: 500, lineHeight: 14px, letterSpacing: 1px }
  button-md:    { fontSize: 18px, fontWeight: 600, lineHeight: 27px }
  button-sm:    { fontSize: 14.4px, fontWeight: 700, lineHeight: 14.4px, letterSpacing: 0.144px }

rounded:
  none: 0px
  sm: 6px        # 输入框、内联药丸
  md: 12px       # 按钮与卡片 —— 品牌的中位圆角签名
  pill: 9999px   # 状态药丸、徽章
  full: 9999px   # 圆形图标容器

spacing:
  xxs: 2px
  xs: 4px
  sm: 8px
  md: 12px
  lg: 16px
  xl: 24px
  2xl: 32px
  3xl: 48px
  4xl: 64px

elevation:
  level-0: flat                  # 无阴影、无边框
  level-1: '1px solid ink 边框'   # 描边卡、outline 按钮
  level-2: 'canvas-soft 填充'     # 软面卡 —— 靠表面温差而非投影
---

# mahiru × Zapier

本文件是 [Zapier 设计语言分析](https://github.com/VoltAgent/awesome-design-md) 在
mahiru 上的落地规范。**这是对公开视觉语言的独立解读与再创作，与 Zapier 无任何
隶属、背书或授权关系**，也未使用其徽标或商标。

## 1. 视觉主题与气氛

一个自信、成熟的工具界面，不是一个营销页。整个界面是**平的**：没有投影、
没有渐变色块；层级由**表面温度**（暖米画布 vs 奶油软面）与 **1px 墨线**承担。

橙 `#ff4f00` 是**唯一的转换色** —— 每一个主 CTA。它饱和、笃定，是这套体系的
签名；除此之外整个界面只有暖米、奶油、咖啡三族的灰阶，没有任何第二种色相。

圆角是**单一中位值 12px**：按钮与卡片同形，不圆滑到胶囊、也不方正到直角。
这是品牌「友好圆润」与「技术方正」之间的刻意中点。

## 2. 颜色与角色

### 品牌与强调
- **Zapier Orange** `#ff4f00` —— 唯一品牌强调。每一个主 CTA 的填充。
  橙就是品牌，**不要引入第二种彩色**。

### 表面
| 令牌 | 值 | 用途 |
|---|---|---|
| `--canvas` | `#fffefb` | 暖米白页面底（**不是纯白** —— 温度就是品牌声音） |
| `--canvas-soft` | `#f8f4f0` | 奶油软面：卡片、内嵌区、表格头 |

### 文字
| 令牌 | 值 | 用途 |
|---|---|---|
| `--ink` | `#201515` | 深咖啡：标题、主文字、secondary 按钮填充、1px 描边 |
| `--ink-soft` | `#2f2a26` | 近黑带暖棕 |
| `--ink-mid` | `#36342e` | 中强调文字 |
| `--body` | `#605d52` | 默认正文 |
| `--body-mid` | `#939084` | 次要正文 / 元信息 |
| `--mute` | `#c5c0b1` | 最低优先级：脚注、发丝分隔 |

### 语义（本规范自定的适配）
Zapier 原文**没有**语义色，明令「状态借用 ink + orange 层级」。清理工具必须
表达安全等级，但**绝不引入红/绿/黄色相**（橙是 CTA 色，不是危险标记色）。

安全等级用**数字 + 边框粗细 + 字重**三通道表达，全部落在咖啡中性色族里。
LightC 垃圾规则只有 **risk 1 / 2 / 3** 三档，另有一个正交的 `locked`
（系统托管）标志 —— 只落在「旧版 Windows 安装」上，前端不提供删除、只引导系统磁盘清理：

| 档 | 表达 | 依据 |
|---|---|---|
| 1（最安全） | 1px `mute` 细框 · 数字 400 字重 · 无填充 | 中性，无需注意的默认态 |
| 2 | 1px `body-mid` 框 · 数字 500 字重 | 略强的注意度 |
| 3 | 1.5px `ink` 框 · 数字 600 字重 | 明显升级 |
| locked（系统托管） | 2px `ink` 框 · 数字 700 字重 + `canvas-soft` 填充 | 整片禁用勾选，只引导系统磁盘清理 |

> 档位差异完全靠**边框变粗 + 字重加重 + 数字本身**，任何一档都不上色。
> `locked` 是 risk 之上的正交标志：默认不勾选且整行禁用，用户不能在本应用内
> 解锁 —— 只能借系统的磁盘清理去处理。默认勾选规则：`risk ≤ 2` 才默认勾选。

## 3. 排版

**字体**：spec 的显示字族 Degular Display 是专有字体，自带指引「Inter 500 最接近」。
本项目**随包内置 Inter**（`web/assets/fonts/`，两个 woff2 + OFL 许可），不从系统取、
不联网。

- Inter 是**可变字体**（`wght 100–900`），`@font-face` 写 `font-weight: 100 900`，
  整条字重跨度只靠 latin / latin-ext 两个子集文件。
- **Inter 没有中文字形**，中文字符由栈里的 **Noto Sans SC** 接。这是栈，不是替换。
- `unicode-range` 让 latin-ext 只在出现该区段字符时才下载。

字重即层级：显示层 500，标题 600–700，正文 400，按钮 600–700。
**中文没有斜体**，一律不用斜体表达强调。

| 令牌 | 字号 | 字重 | 行高 | 用途 |
|---|---|---|---|---|
| `display-md` | 32px | 500 | 36px | 页面主标题（ls 1px，正字距） |
| `display-sub-sm` | 24px | 600 | 30px | 卡片标题 |
| `display-xs` | 20px | 700 | 25px | 行内微型标题 |
| `body-lg` | 20px | 400 | 30px | 引导段落 |
| `body-md` | 18px | 400 | 27px | 默认正文 |
| `body-md-strong` | 18px | 600 | 27px | 加粗内联正文 |
| `body-sm` | 16px | 400 | 24px | 次要正文、导航 |
| `body-sm-strong` | 16px | 600 | 24px | 加粗说明 |
| `caption` | 14px | 400 | 21px | 脚注、时间戳 |
| `eyebrow-uppercase` | 14px | 500 | 14px | 大写 eyebrow（ls 1px） |
| `button-md` | 18px | 600 | 27px | 主按钮标签 |
| `button-sm` | 14.4px | 700 | 14.4px | 小按钮标签 |

界面字号**全部走令牌**，不写死 px：

| 令牌 | 值 | 对应层级 |
|---|---|---|
| `--fs-title` | 32px | `display-md`（页面标题） |
| `--fs-num` | 24px | `display-sub-sm`（概览大数字） |
| `--fs-body` | 16px | `body-sm`（正文、导航） |
| `--fs-small` | 14px | `caption`（元信息、说明） |

两条维护纪律（沿用）：

- **不要在任何地方写死 px 字号。** 写死就脱离了这套阶梯。
- **列表容器的高度常量跟着字号档位走。** `app.css` 的 `.jlist` / `.plist` 用
  `calc(100vh - Npx)`，N 是按当前档位量出来的；改 `--fs-*` 就要一起调。

`tools/verify/verify_css_tokens.py` 由 `tools/run_checks.py` 调用，检查
「每个 `var(--x)` 都有定义」—— CSS 变量算不出来时整条声明会静默作废。

## 4. 组件

### 按钮
- **主按钮 = 橙底**：`primary` 填充 + `on-primary` 字，圆角 **12px**，`padding: 12px 24px`
  （`spacing.md × xl`），标签 `button-md` 18/600。这是全站唯一的转换动作。
- **次按钮 = 咖啡墨底**：`ink` 填充 + `on-primary` 字，同圆角/内边距/字。
- **三级按钮 = outline**：`canvas` 底 + `ink` 字 + 1px `ink` 边，同圆角/内边距/字。
- **文本按钮 = text-only**：`canvas` 底 + `ink` 字，`button-sm` 字，`padding: 8px 16px`，
  圆角 12px。
- 按下反馈见第 9 节。**橙不用于任何非 CTA 用途。**

### 输入
`text-input` = `canvas` 底、1px `ink` 边、`body-md` 字、`padding: 12px 16px`、
圆角 **6px**（`rounded.sm` —— 输入比按钮更方，spec 的刻意的差异）。
聚焦时**不加彩色光环** —— 边框从 1px 加粗到 2px 并保持 `ink`。

### 卡片
`card-content` = `canvas-soft` 底 + `ink` 字，`padding: 24px`（`spacing.xl`），
圆角 **12px**，**无投影**。表面温差（canvas-soft 对 canvas）就是它的抬升。
`card-feature-dark` = `ink` 底 + `on-primary` 字，同形状/内边距 —— 极性翻转的深咖啡卡。

### 密集行（规则列表）
借 `ex-data-table-cell` 的做法：表头 `canvas-soft` 底 + `caption` 字，正文 `body-sm`，
单元格 `padding: 12px 16px`，行分隔 1px `mute` 线。数值列右对齐排成列。

### 导航
`nav-bar` = `canvas` 底 + `ink` 字，`padding: 12px 24px`。`nav-link` = `ink` 字、
`body-sm`。激活项用 **`primary` 橙做指示**（spec 的 `activeIndicator: primary`）。

### 徽章 / 药丸
`badge-pill` = `canvas-soft` 底 + `ink` 字 + `body-sm`，`padding: 4px 12px`，
圆角 `pill` 9999px。风险等级徽章不走药丸 —— 走第 2 节的数字+边框+字重方案。

## 5. 布局

4px 基准。间距预算当作版面英寸分配：卡片内 `xl` 24px，卡片间距 `md`–`lg`。
分隔来自 1px `mute` 发丝线与表面温差，不靠投影堆叠。

侧栏 212px、顶栏 52px、内容区 `padding: 22px 24px 28px` —— 沿用现状。
窗口最小宽度 1024px。

## 6. 深度与投影

| 层级 | 处理 | 用途 |
|---|---|---|
| Level 0 — 平面 | 无阴影、无边框 | 默认：页面底、hero |
| Level 1 — 发丝 | 1px `ink` 边框 | 描边卡、outline 按钮、输入框 |
| Level 2 — 软面卡 | `canvas-soft` 填充对 `canvas` 底 | 默认内容卡 —— 靠表面温差抬升 |

**全系统无投影。** 弹窗/下拉的抬升也走 Level 1 的 1px `ink` 边（或 Level 2 的
软面填充），绝不引入 drop-shadow。

## 7. 该做与不该做

### 该做
- 把 `#ff4f00` 留给**每一个主 CTA** —— 饱和橙就是转换签名。
- 画布保持**暖**：`#fffefb` 奶油，不是纯白；文字用 `#201515` 咖啡，不是纯黑。
- 按钮与卡片用 **12px** 中位圆角，输入用 6px。
- 橙 CTA + 咖啡墨字 + 奶油底的「三令牌节奏」。
- 层级靠表面温差（canvas vs canvas-soft）与 1px 墨线。

### 不该做
- **不要把奶油画布换成纯白** —— 温度就是品牌。
- **不要用纯黑墨** —— `#201515` 的咖啡暖意贯穿每个文字色。
- **不要把 CTA 做成胶囊** —— 品牌按钮是 12px 圆角矩形。
- **不要引入第二种彩色强调** —— 橙 + 奶油 + 咖啡就是全部调色板。
- **不要给任何元素加投影。**
- 不要用橙做「危险/警告」标记 —— 橙是 CTA 色；风险等级走中性数字+边框+字重。

## 8. 响应式与可达性

- 窗口最小宽度 1024px；再窄时列表数值列折到标题下方。
- 触摸/点击目标：按钮 `12px 24px` 内边距包 18px 标签，行距保证 ≥ 44px 高。
- **尊重 `prefers-reduced-motion`**：时长归零、位移动画取消（见第 9 节），
  但状态反馈本身保留。
- 风险等级**不只靠颜色**（本来就没有颜色）—— 数字 + 边框粗细 + 字重三重编码，
  色觉障碍用户也能分辨。

## 9. 动效

只服务**反馈、状态、连续性**三件事，不做页面加载编排。时长 200–300ms、
`cubic-bezier` 曲线，**禁用 `transition: all`**（只列会变的属性）。

| 令牌 | 值 | 用途 |
|---|---|---|
| `--ease` | `cubic-bezier(.22,.61,.36,1)` | 常规过渡 |
| `--ease-out` | `cubic-bezier(.16,1,.3,1)` | 有信心的到达：入场、展开 |
| `--dur-press` | 90ms | 按下。**必须快于松开** |
| `--dur-fast` | 150ms | 即时反馈：悬停、勾选 |
| `--dur-base` | 240ms | 例行状态变化：选项卡、开关轨道 |
| `--dur-knob` | 280ms | 开关滑块：轨道先亮，滑块后到 |
| `--dur-page` / `--dur-row` | 260 / 300ms | 换页、列表错峰 |

- 只动 `transform` / `opacity` / `background-color` / `border-color`。
  **交互期间不动 `width` / `height` / `margin` / `font-weight`** —— 改字重会改变标签宽度，
  后面标签跟着被推一下，那正是「不细腻」的直接来源。
- 按下用 `:active` 上的 `transition-duration: var(--dur-press)` 覆盖，得到快下慢回。
- 平面世界没有投影可以「陷下去」，所以按下反馈用**橙变深**（主按钮）或
  `ink` 变深（次按钮）加 `.97` 缩放代替。
- 选项卡激活指示用**从中间长出来的 2px 墨线**（常驻 `::after` + `scaleX`），不是滑动药丸。
- `:focus-visible` 一律 2px `ink` 实线、偏移 2px，**且不做动画**：延迟出现等于延迟可用。
- `prefers-reduced-motion: reduce` 下所有时长归零、位移动画取消，但**状态变化照常发生**。

## 10. 给实现者的速查

```
橙 #ff4f00   主 CTA 填充（唯一彩色，永不用于危险标记）
墨 #201515   标题、secondary 按钮填充、1px 描边、焦点环
暖白 #fffefb   页面底（不是纯白）
奶油 #f8f4f0   卡片软面（Level 2 抬升）
正文 #605d52 / 元信息 #939084 / 发丝 #c5c0b1

圆角：输入 6px · 按钮/卡片 12px · 药丸 9999px（单一中位体系）
投影：全无（抬升靠温差 + 1px 墨线）
字族：Inter（可变字体，随包内置）+ Noto Sans SC 接中文
风险等级：数字 + 边框粗细 + 字重（无红/绿/黄色相）
动效：200–300ms · cubic-bezier · 禁 transition:all
```
