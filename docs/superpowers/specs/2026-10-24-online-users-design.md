# 直播间在线人数徽标设计

日期:2026-10-24
状态:已实现

## 目标

仿 B 站官方弹幕姬/直播间聊天面板,在悬浮窗卡片右上角显示当前直播间的开播状态与在线用户数;
多房间(merged)时给出直播中房间数与在线总数,per-room 模式各窗口只看自己的房间。

## 数据口径

B 站公开接口里有两个容易混淆的数字:

| 字段 | 含义 | 量级示例 |
|------|------|----------|
| room/v1/Room/get_info 的 online | 人气值(热度) | 千万级 |
| xlive/.../getOnlineGoldRank 的 onlineNum | 当前在线用户数 | 万级 |

因此不能用 get_info.online 冒充在线人数。实际链路:

1. GET /xlive/web-room/v1/index/getRoomBaseInfo?room_ids=<rid>&...
   - 批量参数必须重复 room_ids,逗号拼接会返回 -400(2026-10 实测);
   - 返回真实房间号、主播 uid、live_status、标题、分区、人气、粉丝数;
   - 支持短号,响应 key 是真实房间号,短号在 short_id 字段里。
2. 对 live_status == 1 的房间:
   GET /xlive/general-interface/v1/rank/getOnlineGoldRank?ruid=<uid>&roomId=<真实房间号>&page=1&pageSize=1
   - onlineNum 是当前在线用户数;
   - onlineNumText 是官方展示缩写(13万+ / 9999+),优先用它,避免自己四舍五入和官方不一致。

匿名即可请求,不需要 cookie;Referer/User-Agent 照 sender.py 设置。在线接口失败时保留
开播状态/标题/人气,徽标退化成「人气 x」,不整块消失。

## 刷新策略

- 默认 30s(online_refresh_seconds,最小 5s),与官方页面节奏接近。
- QThreadPool 工作线程执行同步 urllib,信号回主线程;沿用 submit.py 的模式。
- 所有窗口共享一个 RoomStatsPoller;main 从 cfg.rooms 或 dmnotifier history 播种,
  收到弹幕时 poller.watch(platform, rid) 自动补上未配置的房间。
- 失败保留上一轮快照,网络抖动不把在线数抹成空白。
- 设置里关闭 show_online 后停表且不再发请求;重新打开立即刷新。

## UI

- 位置:控制按钮带左侧,与 🔒/⚙ 同一行;高度 28px,字号 11px,不占弹幕行。
- 单房间:● 直播中 · 在线 1.2万;未开播 ○ 未开播;轮播 ◐ 轮播中。
- 多房间:● 2 个直播间直播中 · 在线 3.4万;全部离线时 ○ 2 个直播间均未开播。
- 悬停 tooltip:主播名/标题/分区/在线用户/人气/粉丝数。
- 徽标文字用主题的弱化色,直播圆点用主题 brand_pink;浅色主题单独调深文字色。

## 测试

- tests/test_roomstats.py:短号映射、重复 room_ids 参数、离线跳过 rank、rank 失败回退人气、数字缩写。
- tests/test_statspoller.py:房间集合过滤、watch 去重、移除房间清快照、失败保留旧值、stop/start。
- tests/test_main_smoke.py:徽标显示、per-room 过滤、离线文案、设置开关。
