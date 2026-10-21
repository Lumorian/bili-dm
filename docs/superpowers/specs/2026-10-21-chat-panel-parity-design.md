# 弹幕面板 1:1 复刻 B 站官方聊天列表

- 日期:2026-10-21
- 状态:已实现
- 目标:浮动弹幕面板的行内排版、配色、徽章与卡片,逐像素对齐 B 站直播间网页/直播姬
  的 `chat-history-panel`(官方弹幕姬面板)。

## 1. 参考来源(不是猜的)

官方样式全部来自可核对的一手材料,不靠截图目测:

| 材料 | 用途 |
|------|------|
| `blfe-live-room/static/css/app.<hash>.vip.css` | `.chat-history-list`/`.chat-item`/`.danmaku-item` 的排版声明 |
| `blfe-live-room/static/css/8792.<hash>.vip.css` | `medal.vue` 的 `.fans-medal-item` 组件样式、`.user-level-icon` 配色 |
| `blfe-live-room/static/js/app.<hash>.js` | 行内 DOM 顺序与文案(`danmaku-item-left/right`、`" : "`、`赠送`、`开通了`) |
| `laputa-css/{map,light,dark}.css`(bili-theme v11.0.1) | `--bg2`/`--text2`/`--text3`/`--pay_yellow`/`--brand_pink` 令牌 |
| headless Chrome + 上述 CSS 的本地最小页面(`docs/reference/chat-panel.html`) | 量出真实盒子(见下表),避免"看着像" |

度量页可以随时重跑核对(官方发版后换掉其中的 CSS hash 即可):

```bash
google-chrome --headless=new --disable-gpu --no-sandbox \
  --window-size=400,400 --dump-dom \
  file://$PWD/docs/reference/chat-panel.html | sed -n '/<pre id="out">/,/<\/pre>/p'
```

关键 DOM(官方):

```html
<div class="chat-item danmaku-item">
  <div class="danmaku-item-left">
    <div class="fans-medal-item-ctnr"><div class="fans-medal-item">
      <div class="fans-medal-label guard"><i class="medal-deco medal-guard"></i>
        <div class="fans-medal-content">酷萨</div></div>
      <div class="fans-medal-level"><div class="fans-medal-level-font">33</div></div>
    </div></div>
    <span class="user-name">浮*** : </span>
  </div>
  <span class="danmaku-item-right">哈哈哈哈</span>
</div>
```

## 2. 量出来的盒子(12px 基准,Arial/微软雅黑)

headless Chrome 实测(`getBoundingClientRect`):

```
.chat-item.danmaku-item        x=10 y=5 w=270 h=30   (padding 5,line-box 20)
  .fans-medal-item-ctnr        w=54.02 h=16  margin-left 4  margin-right 3
    .fans-medal-item           w=54.02 h=15  radius 8  padding 2 6 2 2
      .fans-medal-label.guard  padding-left 12
        .medal-deco.medal-guard  w=20 h=20  position absolute  left 6  margin-left -12
        .fans-medal-content      w=24.02(两个汉字) margin-right 2  transform scale(.8333)
      .fans-medal-level        w=8 h=12   (.one-digit-level 4 / .three-digits-level 15)
  .user-name                   line-height 20
  .danmaku-item-right          line-height 20
.chat-history-list             padding 5px 10px  font-size 12px
```

由此得到的两条易错结论(实现时都踩过):

1. **`transform:scale(.8333)` 不参与布局** —— 勋章名排版仍占 24px,只有绘制缩到 83.33%。
2. **航海图标绝对定位溢出胶囊** —— `left:6px;margin-left:-12px` 相对 `.fans-medal-label`
   (其左缘已在胶囊内 2px),因此图标左缘在胶囊外 4px,**不计入胶囊宽度**。

## 3. 实现映射

| 官方 | 本项目 | 文件 |
|------|--------|------|
| `.chat-history-list{padding:5px 10px}` | `PANEL_PAD_X/Y` | `danmaku/wall.py` |
| `.chat-item{padding:5px}` | `ROW_PAD` | 同上 |
| `line-height:20px`(user-name/right 撑起行框) | `LINE_HEIGHT_RATIO = 20/12` | 同上 |
| 行内流式折行(`overflow-wrap:anywhere`) | `danmaku/layout.py` 的 `wrap_runs` | `danmaku/layout.py` |
| `.fans-medal-item` 胶囊 | `_draw_medal`(45° 渐变 + 1px 描边 + 等级槽) | `danmaku/wall.py` |
| `.medal-deco.medal-guard` | 自绘锚形(不引 CDN 图片) | 同上 |
| `.user-name` 后 `" : "` | `style.NAME_SEPARATOR` | `danmaku/style.py` |
| 礼物行 `昵称 赠送 礼物名 x20`,`--pay_yellow` | `KIND_GIFT` 分支 | 同上 |
| 上舰 `昵称 开通了 舰长` | `KIND_SUBSCRIBE` | 同上 |
| `superChat-card-detail` 卡片 | `_paint_superchat` | `danmaku/wall.py` |
| `--bg2`/`--text2`/`--text3`/`--pay_yellow` | `Theme`(dark/light 两套) | `danmaku/theme.py` |

本项目唯一的有意偏离:**行首保留 24px 圆形头像**(官方行内没有头像,用户要求保留)。
头像占用 `10px(padding) + 24px + 5px` 的前缀列,正文自 `TEXT_X = 39px` 起排。

## 4. 协议扩展(UniBarrage → dmnotifier → overlay)

官方面板的这些元素需要协议里原本没有的字段,已按"可选、缺省即旧行为"的方式补上:

```json
{"type":"chat","name":"浮***","content":"哈哈","avatar":"…",
 "uid":12345,"user_level":42,"guard_level":3,"name_color":"#00D1F1",
 "medal":{"name":"酷萨","level":33,"color_start":"#5B8AF5","color_end":"#638FFE",
          "color_border":"#638FFE","color_text":"#FFFFFF","guard_level":3,"is_light":true}}
```

- **UniBarrage**:新增 `universal.UserMeta`/`universal.Medal`;`bilibili` 侧从
  `message.User`/`DANMU_MSG.info.3` 提取(后者才有 v2 的渐变/描边/文字色),
  `SUPER_CHAT_MESSAGE` 额外透出 `background_color_start/end`、`background_price_color`。
- **dmnotifier**:`models.UserMeta`/`models.Medal`;format 转换保留原词
  (`Text/Item/Num/Price`),float 插件把元信息摊平成上面那些字段。
- **overlay**:`Danmaku.medal/guard_level/user_level/name_color/bg_color_*`,
  解析时 `text` 覆盖 `content`(dmnotifier 的 content 是「送出了 20 个 辣条 (2.00 元)」
  这类整句,官方面板要按 `赠送`/`礼物名`/`x20` 分色绘制)。

### 醒目留言卡片

官方 `superChat-card-detail` 是整块卡片:`margin: 0 -5px`、`min-height:38px`,顶栏
`.card-item-middle-top{height:34px;padding:0 5px}`(头像 30px),正文
`.card-item-middle-top-right{color:#333}`,金额 `.card-item-top-right{color:#333}`。
底色取自消息自身的 `background_color_start/end`(SC 有 7 档价格色)。

本项目:卡片占满该行(含行 padding)、6px 圆角、渐变底取协议色(缺省用主题黄),
文字默认用主题的 `card_text`(#333,与官方一致),协议给了 `price_color` 就用它;
卡片底色是深色档位时自动改用白字(`sc_text_color`,按相对亮度判断)。

## 5. 主题

`config.yaml` 的 `theme: dark | light`(默认 dark;CLI `--theme`,设置对话框可切换)。
令牌一一对应官方 bili-theme:

| 令牌 | light | dark |
|------|-------|------|
| `--bg2`(--Ga0) | `#F6F7F8` | `#101011` |
| `--text2`(--Ga7) | `#61666D` | `#A2A7AE` |
| `--text3`(--Ga5) | `#9499A0` | `#757A81` |
| `--pay_yellow`(--Ye5) | `#FFB027` | `#DB8700` |
| `--brand_pink`(--Pi5) | `#FF6699` | `#D44E7D` |

## 6. 验证

- `uv run pytest`:151 项通过,覆盖率 89%(布局 99%、勋章/主题 100%)。
- `go test ./...`:`UniBarrage`(bilibili 提取器)与 `dmnotifier`(float 协议行)全绿。
- 视觉对照:`tests/test_wall_offscreen.py` 断言行高 30px 节奏、胶囊宽度公式、
  勋章名不缩放、锚图标绘制、SC 卡片底色与金额、头像占位/命中两条路径。
