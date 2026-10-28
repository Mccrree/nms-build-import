# nms-build-import

把别人在《无人深空》里盖的基地或护卫舰，搬进你自己的存档。
*A Claude skill that copies another player's No Man's Sky base or corvette build into your own save.*

存档是一个压缩数据块加一份加密的元数据文件，两者必须同时写、且不能在游戏运行时写，否则这个存档位就毁了。
所以这套工具全程只操作副本：先预演一遍完整写入，校验通过后才动真格，写之前自动做一份逐文件校验过的备份，并给你一条随时可用的恢复命令。

---

## 能做什么

- **扫描存档**：列出你自己的基地、存档里缓存的别人的基地（可导入的候选）、以及可用的飞船。
- **提取建筑**：把缓存的基地导出成独立文件。下载来的基地记录不会把基地电脑放在原点，提取时会自动重新对齐，之后可以放到任何一台你自己摆的基地电脑上。
- **调整**：水平旋转、整体抬升、平移、按半径裁剪、去掉指定零件。旋转是刚性的——零件间距和缩放（缩放藏在 `Up`/`At` 向量长度里）都会校验。
- **导入**：星球基地或护卫舰，演练 / 写入 / 恢复三种模式，自动解锁建筑用到的零件。
- **直接新建护卫舰**：不用先在游戏里造一艘占位船，也不用覆盖已有的船——只要有一个空飞船槽位，就能把护卫舰 build 导入成一艘全新的船（已在游戏里验证）。
- **对比存档**：给存档拍快照、在游戏里做一件事、再拍一次，自动列出游戏改了哪些字段。新功能就是这样摸清楚的，不靠猜。
- **画图**：生成俯视 + 侧视的 SVG，方便在导入前判断占地、高度和分布。

## 不能做什么

- 主机存档（PS / Xbox / Switch）和 Game Pass 存档。只支持 PC 版的 Steam（已验证）和 GOG（同一套文件）。Game Pass 的存档放在别处、格式也不同。
- 改地形。建筑会按原来的高度落地，依山而建的设计放在平地上，下半部分会埋进地里。
- 空间站内部（`PlayerSpaceBase`）。那是另一套零件和另一种记录类型。

---

## 准备

| 需要 | 说明 |
|---|---|
| PC 版存档 | Windows：`%APPDATA%\HelloGames\NMS\`；macOS：`~/Library/Application Support/HelloGames/NMS/` |
| Python 3.10+ | 只用标准库，不用装依赖 |
| [libNOM.io.cli](https://github.com/zencq/libNOM.io/releases) | 负责存档和 JSON 互转。Windows 下载 `libNOM.io.cli.win-x64.exe`，设置环境变量 `NMS_LIBNOM` 指向它 |

详见 [`references/setup.md`](references/setup.md)。

## 安装

**方式一**：下载 [`nms-build-import.skill`](nms-build-import.skill)，在 Claude 里点文件卡片上的 **Save skill**。

**方式二**：克隆到本地 skills 目录。

```bash
git clone https://github.com/Mccrree/nms-build-import.git ~/.claude/skills/nms-build-import
```

装好之后，直接跟 Claude 说你想把某个基地搬进存档就行，它会自己引导流程。也可以手动跑脚本：

## 手动用法

```bash
# 出去逛之前，存一份参考扫描
python scripts/scan_save.py --json builds/before-tour.json

# 进游戏逛一圈（飞到各个星球，或用太空异象的传送终端看精选基地），逛完存档

# 回来看看多了什么，并把够大的全部提取出来
python scripts/scan_save.py --since builds/before-tour.json
python scripts/extract_build.py --all --min-parts 300 --out builds/ --views

# 需要的话调整：转个方向、抬高一点、只留主体
python scripts/transform_build.py "builds/某基地 - build.json" --rotate 90 --lift 8 --trim 60 --out builds/adjusted.json

# 先演练，确认没问题再写入（写入前请完全退出游戏）
python scripts/import_build.py --build builds/adjusted.json --target 你的基地名 --dry-run
python scripts/import_build.py --build builds/adjusted.json --target 你的基地名 --apply

# 护卫舰：直接新建一艘（需要一个空飞船槽位）
python scripts/extract_build.py --corvette --ship-index 10 --out builds/
python scripts/import_build.py --build "builds/GUNDA_01 - build.json" --kind corvette --new-ship --ship-name 新船 --dry-run
python scripts/import_build.py --build "builds/GUNDA_01 - build.json" --kind corvette --new-ship --ship-name 新船 --apply

# 后悔了
python scripts/import_build.py --restore "<备份目录>"

# 想弄清楚游戏改了什么：拍快照 -> 游戏里只做一件事并存档退出 -> 再拍 -> 对比
python scripts/diff_saves.py snapshot before
python scripts/diff_saves.py snapshot after
python scripts/diff_saves.py diff before after
```

扫描和提取只读副本，游戏开着也能用（存过档即可）；**只有写入要求游戏完全退出**。

## 几条来之不易的经验

- **没学会的零件可能不显示。** 存档里明明有 2996 个零件，进游戏却是一地窟窿——因为那些零件的图纸不在 `KnownProducts` 里。逛别人的基地时能正常显示，放进自己基地就不行。所以导入时默认会把建筑用到的零件全部学会。
- **缓存会被清掉。** 存档只保留有限数量的别人的基地，你继续飞就会被顶替，几小时内整批换掉都很常见。看中了就当天提取。
- **下载来的基地可能是被截断的。** 上传有上限，三个互不相关的大型基地都正好停在 2997 个零件。你拿到的是服务器给的那份。
- **偶尔会混进 `U_PARAGON`。** 那是护卫舰的核心零件，在星球上根本不能放，属于游戏留下的残留，导入前用 `--drop-id U_PARAGON` 去掉。
- **元数据必须拿游戏自己的那份当模板修复**，只改尺寸和时间戳。否则存档位的身份信息（槽位 ID、难度标签）会丢。
- **护卫舰 = 两条记录。** 飞船本身在 `ShipOwnership` 的某个槽位里，外形是一条 `PlayerShipBase` 记录，靠 `UserData` = 槽位编号对上。按 `UserData` 找，不要按列表位置找。
- **拆船不会让编号移位。** 12 个槽位是固定的，拆掉的船原地变空，别的船和护卫舰外形都不受影响。
- **种子就是创建时间。** 护卫舰的种子是创建那一刻的 Unix 时间（十六进制），和外形记录里的 `Owner.TS` 完全相等；外形记录不需要服务器 ID（`RID` 为空）。照这个规律新建的船，游戏能正常显示、召唤、飞行、进编辑器。
- **游戏里造不出护卫舰，不一定是没解锁。** 起落架图纸都学会了还是放不上——护卫舰零件仓库（`CorvetteStorageInventory`）里没有起落架这件物品。直接用 `--new-ship` 导入就绕开了。
- **存档对比 99% 是噪音。** 拆一艘船，对比出 21,858 处变化，真正相关的不到十处；地形编辑、发现记录、零件时间戳每次存档都会变。所以对比时一次只做一件事、存完马上退出。游戏不让你做的事（比如造船），就拿几个现成的例子互相比。

更多细节见 [`references/save-format.md`](references/save-format.md)，出问题看 [`references/troubleshooting.md`](references/troubleshooting.md)。

## 关于别人的作品

工具搬运的是其他玩家盖的建筑。自己玩没问题，但请不要把别人的作品当成自己的上传或分发。

---

## English summary

A [Claude](https://claude.com/claude-code) skill for No Man's Sky PC saves. It scans a save for builds it has
cached (other players' bases you visited, your own bases, your corvette), extracts one into a portable
build file re-centred on its own base computer, lets you rotate / lift / trim it, and imports it onto a
base computer you placed - learning the parts it uses so nothing stays invisible. A corvette build can
also become a brand-new ship in a free ship slot, with nothing built in game first (verified in game).

Every write is rehearsed in full first, is preceded by a hash-verified backup of the whole save folder,
touches only the JSON paths its mode declares (the target's `Objects` and `KnownProducts`; for a new
ship also that slot, its colour flag and one appended build record), is read back from disk and
verified, and can be undone with one command. `diff_saves.py` snapshots and diffs saves so new fields
are learned from what the game writes, not guessed. Steam saves (GOG uses the same files); not Game
Pass. Requires Python 3.10+ and [libNOM.io.cli](https://github.com/zencq/libNOM.io/releases).

Install: download `nms-build-import.skill` and click **Save skill**, or clone this repo into
`~/.claude/skills/nms-build-import`.

Not affiliated with Hello Games. `assets/part_catalog.json` contains only internal part identifiers,
used to validate a build and decide which blueprints to learn.

## License

MIT - see [LICENSE](LICENSE).
