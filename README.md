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
- **画图**：生成俯视 + 侧视的 SVG，方便在导入前判断占地、高度和分布。

## 不能做什么

- 主机存档（PS / Xbox / Switch）。只支持 PC 版：Steam、GOG、Game Pass。
- 改地形。建筑会按原来的高度落地，依山而建的设计放在平地上，下半部分会埋进地里。
- 空间站内部（`PlayerSpaceBase`）。那是另一套零件和另一种记录类型。

---

## 准备

| 需要 | 说明 |
|---|---|
| PC 版存档 | Windows：`%APPDATA%\HelloGames\NMS\`；macOS：`~/Library/Application Support/HelloGames/NMS/` |
| Python 3.10+ | 只用标准库，不用装依赖 |
| [libNOM.io.cli](https://github.com/zencq/libNOM.io/releases) | 负责存档和 JSON 互转。下载后设置环境变量 `NMS_LIBNOM` 指向可执行文件 |

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

# 后悔了
python scripts/import_build.py --restore "<备份目录>"
```

扫描和提取只读副本，游戏开着也能用（存过档即可）；**只有写入要求游戏完全退出**。

## 几条来之不易的经验

- **没学会的零件可能不显示。** 存档里明明有 2996 个零件，进游戏却是一地窟窿——因为那些零件的图纸不在 `KnownProducts` 里。逛别人的基地时能正常显示，放进自己基地就不行。所以导入时默认会把建筑用到的零件全部学会。
- **缓存会被清掉。** 存档只保留有限数量的别人的基地，你继续飞就会被顶替，几小时内整批换掉都很常见。看中了就当天提取。
- **下载来的基地可能是被截断的。** 上传有上限，三个互不相关的大型基地都正好停在 2997 个零件。你拿到的是服务器给的那份。
- **偶尔会混进 `U_PARAGON`。** 那是护卫舰的核心零件，在星球上根本不能放，属于游戏留下的残留，导入前用 `--drop-id U_PARAGON` 去掉。
- **元数据必须拿游戏自己的那份当模板修复**，只改尺寸和时间戳。否则存档位的身份信息（槽位 ID、难度标签）会丢。

更多细节见 [`references/save-format.md`](references/save-format.md)，出问题看 [`references/troubleshooting.md`](references/troubleshooting.md)。

## 关于别人的作品

工具搬运的是其他玩家盖的建筑。自己玩没问题，但请不要把别人的作品当成自己的上传或分发。

---

## English summary

A [Claude](https://claude.com/claude-code) skill for No Man's Sky PC saves. It scans a save for builds it has
cached (other players' bases you visited, your own bases, your corvette), extracts one into a portable
build file re-centred on its own base computer, lets you rotate / lift / trim it, and imports it onto a
base computer you placed - learning the parts it uses so nothing stays invisible.

Every write is rehearsed in full first, is preceded by a hash-verified backup of the whole save folder,
touches only two JSON paths (the target's `Objects` and `KnownProducts`), is read back from disk and
verified, and can be undone with one command. Requires Python 3.10+ and
[libNOM.io.cli](https://github.com/zencq/libNOM.io/releases).

Install: download `nms-build-import.skill` and click **Save skill**, or clone this repo into
`~/.claude/skills/nms-build-import`.

Not affiliated with Hello Games. `assets/part_catalog.json` contains only internal part identifiers,
used to validate a build and decide which blueprints to learn.

## License

MIT - see [LICENSE](LICENSE).
