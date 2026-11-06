无人深空 建筑导入工具 (NMS Build Import)
==========================================

把别人在《无人深空》里盖的基地、或者护卫舰的外形，搬进你自己的存档。不需要会编程，也不需要 AI。

只支持 PC 版 Steam / GOG 存档。不支持 Game Pass 和主机（PS / Xbox / Switch）。

一、第一次使用
--------------
1. 把整个压缩包解压到一个固定的文件夹（不要直接在压缩包里运行）。
   NMS-Build-Import.exe 必须和 libNOM 文件夹放在一起。
2. 双击 NMS-Build-Import.exe。
   Windows 可能提示“已保护你的电脑”：点“更多信息” → “仍要运行”。
   （这个程序没有购买代码签名证书，所以会有这个提示。）

二、拿到别人的基地
------------------
1. 进游戏，飞到别人的基地，或者在太空异象里用基地传送终端去看“精选基地”。
2. 在游戏里存档（游戏不用退出）。
3. 在工具的「① 读取存档」页点「读取存档」，在「别人的基地」里选中想要的，点「提取选中」。
   游戏只会临时保存附近别人的基地，几小时内就会被替换掉——看中了当天就提取。

三、导入
--------
星球基地：
  1. 在游戏里，在想放的位置放一台基地电脑，起一个好认的名字，存档，然后完全退出游戏（退到桌面）。
  2. 回到工具，点「读取存档」。
  3. 到「② 导入」页，左边选建筑文件，右边选“我的星球基地”和刚才那台基地电脑的名字。
  4. 点「演练（不改存档）」，看结果没问题，再点「写入存档」。

护卫舰（直接新建一艘，不用覆盖原来的船）：
  1. 需要一个空的飞船槽位（最多 12 艘，在游戏里拆掉一艘不要的船），以及至少一艘自己的护卫舰。
  2. 完全退出游戏，点「读取存档」。
  3. 「② 导入」页选护卫舰建筑文件，右边选“新建一艘护卫舰”，填名字。
  4. 先演练，再写入。

四、安全措施
------------
- 游戏开着时，工具只能读、不能写；写入前必须完全退出游戏。
- 每次写入前，都会把整个存档文件夹完整备份到「文档\NMS-save-backups」，每个文件都校验过。
- 写入后会从磁盘读回来再检查一遍，不对就自动还原。
- 后悔了：在「③ 备份与恢复」选一个备份，点「恢复选中备份」。
  注意：恢复会丢掉那之后在游戏里的进度。

五、常见问题
------------
- 进游戏后零件缺了一块：多半是建筑有一部分埋进了地里。在「调整」里抬高几米再导入，
  或者把基地电脑放到更高的地方。导入前预览下方会显示“基地电脑下方”有多少零件。
- 零件显示不出来：保持勾选“自动学会建筑用到的零件”再导入一次。
- 提示“飞船槽位已满”：在游戏里拆掉一艘不要的船，存档退出，再读取存档。
- 提示“找不到这个名字的基地”：确认基地电脑放好、名字一致、并且存过档。
- Steam 启动时问用本地还是云端存档：选“本地”。

六、关于别人的作品
------------------
别人盖的建筑是别人的作品。自己玩没问题，请不要把别人的作品当成自己的上传或分发。

工作文件（提取出来的建筑）在：文档\NMS-build-import\builds
源代码与更新：https://github.com/Mccrree/nms-build-import

-------------------------------------------------------------------------------

NMS Build Import - English quick guide

Copies another player's No Man's Sky base, or a corvette design, into your own save. PC saves from
Steam / GOG only (not Game Pass, not consoles).

1. Unzip everything to a folder; keep NMS-Build-Import.exe next to the libNOM folder. If Windows
   SmartScreen warns, click "More info" -> "Run anyway" (the program is not code-signed).
2. Get builds: visit bases in game, save, then "Read save" and extract the ones you like the same day.
3. Import a planet base: place a base computer in game, name it, save, quit to desktop; read the
   save; on "Import" pick the build and your base; Rehearse, then Write.
   Import a corvette as a new ship: needs one free ship slot (max 12) and one corvette of your own.
4. Every write is preceded by a full, hash-checked backup (Documents\NMS-save-backups) and can be
   undone on the "Backups" page (progress made since is lost).
5. Other players' builds are their work: enjoy them, do not re-upload them as your own.
