# 恒艺美发客户端首屏生成文档

## 目标

基于参考图的“手机海报式首屏”生成一个恒艺美发客户端首页。保留参考图的高级感构图：手持手机、浅蓝背景、超大白色标题、品牌标识、人物头像社交证明、底部真实服务场景、圆形预约 CTA。将牙科诊所主题完整替换为美发门店主题。

生成后的页面用于客户侧，不出现内部工作台、客户维护、流失预警、员工操作等内容。

## 参考图风格拆解

- 画面比例：竖版移动端海报，适合 9:16 或手机截图。
- 主视觉：一只手拿着 iPhone，手机屏幕占画面主体。
- 背景：干净的浅蓝色，通透、明亮、有医疗/专业服务感。
- 首屏结构：
  - 顶部状态栏：9:41、信号、电量。
  - 左上品牌：线性图标 + 品牌名。
  - 右上菜单：三横线。
  - 主标题：超大白色无衬线字体，三行排版。
  - 社交证明：2 个圆形用户头像 + “+2k”小圆标。
  - 简短说明：两到三行浅色正文。
  - 底部场景：服务人员围绕一个巨大主体物操作。
  - 圆形 CTA：亮黄色圆形按钮，带环绕文字和箭头。

## 美发主题替换规则

| 参考图元素 | 替换为恒艺美发元素 |
| --- | --- |
| SmileLab | 恒艺美发 / HengYi Salon |
| 牙齿图标 | 发丝、剪刀、梳子或“H”发丝线性标志 |
| Restore Your True Smile | 焕新你的专属发型 |
| 牙齿治疗说明 | 预约常用发型师、查看排档、余额积分和订单 |
| 牙医/清洁牙齿 | 美发老师剪发、吹风、染护、造型 |
| 巨大牙齿 | 亮泽发丝、发束、发型轮廓或镜面沙龙椅 |
| Book Your Consultation | 预约你的发型师 |
| +2k | +2k 会员 / +2k 好评 |

## 推荐页面文案

品牌名：

```text
恒艺美发
```

主标题：

```text
焕新
你的专属
发型
```

辅助说明：

```text
查看常用美发老师的可约时间，管理余额、积分与订单，让每次到店都更从容。
```

圆形 CTA：

```text
预约你的发型师
```

社交证明：

```text
+2k 会员
```

## 图像生成 Prompt

可直接复制给图片生成模型：

```text
Create a premium mobile app hero poster for a Chinese hair salon brand named "恒艺美发". The composition is based on a realistic hand holding a modern iPhone, vertical 9:16 poster, clean sky blue background, elegant high-end salon service feeling.

Inside the phone screen: top status bar 9:41, signal and battery icons, top-left minimal hair strand logo with the brand text "恒艺美发", top-right hamburger menu. Huge white modern sans-serif headline in Chinese: "焕新 你的专属 发型", arranged in three large lines, soft rounded typography, no negative letter spacing. Add two small circular customer avatar photos and a small white bubble saying "+2k 会员".

Under the headline, add subtle white supporting copy: "查看常用美发老师的可约时间，管理余额、积分与订单。"

Bottom visual: replace the giant tooth with a glossy flowing lock of healthy hair or an elegant salon chair with luminous hair strands. Three professional hair stylists in refined black salon aprons are working around it with scissors, comb, hair dryer, and color brush. Make the stylists feel premium salon professionals, not doctors. Add a bright lime-yellow circular CTA sticker over the lower hair visual, with circular text "预约你的发型师" and a simple arrow pointing up-right.

Visual style: photorealistic phone and hand, clean editorial app design, premium beauty salon, airy blue background, white typography, lime CTA accent, polished commercial poster, high detail, modern iOS app aesthetic, no dental elements.
```

## 负面 Prompt

```text
No teeth, no dental clinic, no dentist, no medical blue scrubs, no surgical tools, no dental drill, no toothpaste, no hospital, no oral care objects, no English dental brand, no SmileLab text, no internal staff dashboard, no CRM, no charts, no admin table.
```

## 前端页面生成 Prompt

如果用 Claude、Codex 或前端生成器生成 HTML/CSS 页面，使用这段：

```text
Build a mobile-first landing hero for the customer-side app of "恒艺美发". Use a full-screen phone-poster composition inspired by a premium beauty service campaign.

The page should look like a phone screen inside a hand-held iPhone mockup or a centered rounded mobile viewport. Background color is airy salon blue. Top area has iOS status bar, brand logo text "恒艺美发", and a hamburger menu icon. The hero headline is huge white Chinese text: "焕新 / 你的专属 / 发型". Supporting copy: "查看常用美发老师的可约时间，管理余额、积分与订单。"

Add small customer avatar bubbles and "+2k 会员". Bottom hero visual should be hair-salon themed: flowing glossy hair, salon chair, or stylists working with scissors, comb, dryer, and color brush. Add a circular lime CTA button labeled "预约你的发型师" with an up-right arrow. CTA should navigate to the appointment/schedule screen.

Do not include staff workbench, retention reminders, internal customer management, churn warnings, or admin functions. This is customer-facing only: balance, points, orders, stylist schedule, and appointment.

Use semantic HTML, responsive CSS, accessible button labels, SVG icons rather than emoji, 44px minimum touch targets, and no horizontal scroll.
```

## 可生成页面的信息架构

客户侧只保留这些功能：

1. 我的会员卡：余额、积分、会员等级。
2. 我的订单：已预约、已完成、已取消订单。
3. 老师排档：展示所有美发老师。
4. 常用老师：客户可以设为常用，并只看该老师排档。
5. 预约 CTA：进入预约页或直接选择时间。

明确不展示：

1. 工作台。
2. 今日待联系。
3. 流失预警。
4. 复制话术。
5. 已联系/忽略。
6. 员工日程管理。
7. 内部营销名单。

## 视觉参数建议

- 主色：浅蓝 `#6FAFE0` 或 `#75B5E7`。
- 主文字：白色 `#FFFFFF`。
- CTA：荧光黄绿 `#E8FF4F`。
- 辅助文字：半透明白 `rgba(255,255,255,.76)`。
- 品牌辅助色：深墨绿或黑色，用于小图标和按钮箭头。
- 字体：Inter、SF Pro、PingFang SC、Microsoft YaHei。
- 标题字号：手机宽 390px 时可用 64px-78px，行高 0.92-1.0。
- 圆角：手机壳 36px-46px，卡片 12px，CTA 圆形。

## 交付检查

- 首屏一眼能看出是美发，不是牙科。
- 品牌显示为“恒艺美发”。
- CTA 指向预约发型师。
- 客户只能看到余额、积分、订单、老师排档和预约。
- 不出现任何内部运营字段或员工工作台入口。
