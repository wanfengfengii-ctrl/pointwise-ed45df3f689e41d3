# 东岚科技馆触读展台

布展员用馆内音片清单和现场布置单发行节目。值班员校对触板、开场并开放逻辑拍。触板按实际触摸提交按压，讲解服务据实收证据启动音片或记录正式静默。闭场后，值班员凭实际启动记录及原触点出处复盘。

## 运行

需要 Python 3.11 标准库。以下命令在项目根目录执行。

```text
python3 -B check_project.py
python3 -B demo.py
python3 -B -m session.runtime --db gallery.sqlite3 --port 8080
```

`check_project.py` 由物化平台提供。直接发现原回归可运行 `python3 -B -m unittest discover`。演示在临时目录启动真实 HTTP 服务，显式发行 `examples/gallery.json` 的样例，演示错序交件、无关缺报、闭场补交和重开复领。

服务器绑定 `127.0.0.1`。`--db` 指定场次、讲解和场报库。紧邻它的 `.panels` 文件保存触板受理、回执与交件。使用原路径重开，两份数据会一并续办。初始化仅创建缺失结构，样例通过发行接口显式录入。程序以持久化的启动事件表示实际开讲，音频播放硬件由展馆现场负责。

## JSON HTTP

GET 用查询参数，POST 用 JSON 对象。整数标识由服务发行。板号、组号、规则号、音片号、位置和请求号是文本。成功返回 HTTP 200 与结果对象。拒绝时返回 `error` 和 `message`，所属业务事务回滚。400 表示结构或编排无效，404 表示身份或原号未知，409 表示时序、封拍或交件冲突。503 表示存储操作失败。

| 请求 | 参数与结果 |
| --- | --- |
| `POST /issue` | `audio` 和 `groups`。音片字段为 `audio_id`、`name`、`length_ticks`。组含 `group_id`、`boards`、`rules`，规则含 `rule_id`、`priority`、`requires`、`audio_id`。返回 `show_id` 及定稿。 |
| `GET /show` | `show_id`。领取指定版本的音片和有序规则。 |
| `POST /open` | `show_id` 和 `bindings`，每项含 `board_id`、`group_id`、`position`。全部板须覆盖且板位互异。返回 `session_id`、节目号、校位表及进度。 |
| `GET /session` | `session_id`。领取固定节目号、校位表、`last_tick` 和 `closed_tick`。未闭场的 `closed_tick` 为 null。 |
| `POST /tick` | `session_id`、`tick`。从 1 连续开放下一拍，并核对无需触点即可办结的组。 |
| `POST /touch`、`POST /seal` | `session_id`、`board_id`、`tick`、`request_id`。返回 `accepted` 或 `sealed` 的原回执及 `delivery_id`。再次封同一板拍可领取第一次固定的交件。 |
| `GET /receipt`、`GET /delivery` | 分别用 `session_id` 与 `request_id` 查原回执，或以 `delivery_id` 领取原交件正文。 |
| `POST /receive` | `evidence` 为交件正文。实收确认含原身份和 `event_id`。重投同件返回原确认，矛盾交件拒收。 |
| `GET /inspect` | `session_id`、`group_id`、`tick`。返回 `pending`、`started` 或 `silent`。开讲附带 `start_id`、`rule_id`、`clip`、`sources`。 |
| `GET /plays` | `session_id`。按实际启动顺序列出已经提交的开讲，用于现场核对。 |
| `POST /close` | `session_id`。固定 `last_tick`，禁止开放新拍，已开放的原拍仍可办理。 |
| `POST /report` | 仅提供 `session_id` 或 `report_id` 之一。按场次处理闭场覆盖，待结时给出 `pending` 清单。全覆盖后签出 `published` 场报。按报告号直接领取已存场报。 |

## 现场裁定与出处

同一组最多两块触板。音片拍长是正整数，随定稿和实际启动保存。规则要求至少一块指定板同拍按下，组内优先号互异，较小值先匹配。每个交件仅属于发出时的原场、原板、原拍。按压和封拍各自提交，封拍交件记录首次封拍时的按压引用。空引用确证空拍，有引用只说明已受理按压。触发开讲所需的原按压正文要实收后才具备出处。

规则仍可能改变时继续待定。唯一可命中的规则具备正式出处即可开讲，无可能命中时签存静默。所需触板以该板第一份实收的正式按压为出处，后续同板事实不会改写它。只有 `started` 会提交一个实际启动事件，`silent` 是稳定的正式结局。处于待定的组拍不占正式结局名额。值班员按场次号和原请求号查领，封拍后的新按压会拒绝，先前成功的原请求仍可复领。

闭场包含所有已开放拍及定稿内各组。只要有应结组拍缺项，报告就返回按拍号再按组号排序的清单。报告发布后固定条目、音片、出处和报告号。零拍闭场可签出空场报。原回归覆盖节目重发、校位失配、真空拍对照、按压迟到、无关缺报、提交后失答、同库重开、原拍隔离和闭场覆盖。
