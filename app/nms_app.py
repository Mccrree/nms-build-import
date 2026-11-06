"""NMS Build Import - desktop app for players who do not use an AI agent.

The same pipeline as the skill's scripts (it imports them, it does not reimplement them):
scan a save, extract cached bases and corvettes into build files, adjust a build, rehearse
an import, write it with a hash-verified backup, and restore a backup. Everything runs
locally; libNOM.io.cli does the save <-> JSON conversion and ships next to the .exe.

  python app/nms_app.py          # from a checkout (needs Python 3.10+ and libNOM)
  NMS-Build-Import.exe           # packaged, see app/build_exe.py
"""
from __future__ import annotations

import contextlib
import json
import math
import os
import queue
import sys
import tempfile
import threading
import time
import tkinter as tk
from datetime import datetime
from pathlib import Path
from tkinter import filedialog, messagebox, ttk
from types import SimpleNamespace
from typing import Any, Callable

if not getattr(sys, "frozen", False):
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

import extract_build  # noqa: E402
import import_build  # noqa: E402
import make_views  # noqa: E402
import nms_save as ns  # noqa: E402
import scan_save  # noqa: E402
import transform_build  # noqa: E402

APP_NAME = "NMS Build Import"
APP_VERSION = "1.0.0"
SETTINGS_PATH = Path(os.environ.get("NMS_APP_SETTINGS")
                     or Path(os.environ.get("APPDATA", Path.home())) / "NMS-build-import" / "settings.json")
DEFAULT_WORKSPACE = Path(os.environ.get("NMS_APP_WORKSPACE") or Path.home() / "Documents" / "NMS-build-import")
COLOURS = make_views.COLOURS

TEXT: dict[str, dict[str, str]] = {
    "zh": {
        "title": "无人深空 建筑导入工具",
        "lang": "语言",
        "save_folder": "存档文件夹",
        "change": "更改…",
        "default": "默认",
        "libnom": "libNOM",
        "libnom_missing": "未找到——请把 libNOM 文件夹和本程序放在一起",
        "libnom_bundled": "已就绪（随程序附带）",
        "game": "游戏",
        "game_running": "正在运行（只能读取，不能写入）",
        "game_closed": "已关闭",
        "newest_save": "最新存档",
        "workspace": "工作文件夹",
        "open": "打开",
        "tab_save": "① 读取存档",
        "tab_import": "② 导入",
        "tab_backups": "③ 备份与恢复",
        "scan": "读取存档",
        "scan_hint": "只读取副本，游戏开着也可以（先在游戏里存档）。别人的基地会被游戏很快替换掉，看中了就当天提取。",
        "cached": "别人的基地（存档缓存）",
        "mine": "我的基地",
        "ships": "飞船",
        "extract_selected": "提取选中",
        "extract_all": "全部提取",
        "min_parts": "最少零件",
        "col_name": "名称",
        "col_author": "作者",
        "col_parts": "零件",
        "col_reach": "范围 m",
        "col_height": "高度 m",
        "col_unlearned": "未学会",
        "col_type": "类型",
        "col_slot": "槽位",
        "col_model": "型号",
        "col_corvette": "护卫舰零件",
        "col_state": "状态",
        "col_created": "创建时间",
        "col_files": "文件数",
        "flown": "正在驾驶",
        "empty_slot": "空槽位",
        "free_slots": "空飞船槽位：{n} / {total}",
        "builds": "建筑文件",
        "refresh": "刷新",
        "open_file": "打开文件…",
        "preview": "预览（俯视，点 = 零件位置）",
        "adjust": "调整",
        "rotate": "旋转 °",
        "lift": "抬高 m",
        "trim": "只保留半径 m",
        "drop_paragon": "去掉 U_PARAGON（星球上放不了）",
        "target": "导入到",
        "to_planet": "我的星球基地",
        "to_new_ship": "新建一艘护卫舰",
        "to_replace_ship": "覆盖我的护卫舰",
        "ship_name": "新船名字",
        "template": "复制谁的科技",
        "learn": "自动学会建筑用到的零件（推荐）",
        "rehearse": "演练（不改存档）",
        "apply": "写入存档",
        "need_scan": "请先在第①页读取存档。",
        "need_build": "请先选一个建筑文件。",
        "need_target": "请选择导入目标。",
        "planet_help": "星球基地：先在游戏里放一台基地电脑、起个好认的名字，存档后退回桌面，再回来读取存档。",
        "ship_help": "新建护卫舰：需要一个空飞船槽位（在游戏里拆掉一艘不要的船），以及至少一艘自己的护卫舰。",
        "replace_help": "覆盖护卫舰：先在游戏里换开另一艘船。",
        "rehearse_ok": "演练通过，存档没有任何改动。确认无误后可以点「写入存档」。",
        "confirm_apply": "即将写入存档：\n\n{what}\n\n写入前会完整备份整个存档文件夹，写完会读回检查，出问题自动还原。\n请确认游戏已完全退出。继续吗？",
        "applied": "写入完成，已读回检查。\n\n备份：{backup}\n\n进游戏检查一下；如果要撤销，到「③ 备份与恢复」选择这个备份恢复。",
        "after_apply": "存档已改动，请重新读取存档后再做下一次导入。",
        "backups": "备份（最新的在上）",
        "restore": "恢复选中备份",
        "open_folder": "打开备份文件夹",
        "confirm_restore": "把存档恢复到这个备份：\n{name}\n\n备份之后在游戏里的进度会丢失。恢复前会先另做一份安全备份。继续吗？",
        "restored": "已恢复，并逐个文件校验过。\n恢复前的安全备份：{safety}",
        "busy": "处理中：{what}…",
        "ready": "就绪",
        "error": "出错了",
        "log": "日志",
        "extracted": "已提取 {n} 个建筑到 {dir}",
        "nothing_cached": "存档里没有零件数达到 {n} 的别人的基地。去游戏里逛逛别人的基地，存档后再读取。",
        "summary_parts": "零件：{before} → {after}",
        "summary_learn": "新学会的零件：{n} 种",
        "summary_target": "目标：{target}",
        "summary_ship": "新船：槽位 {slot}「{name}」，科技复制自「{template}」",
        "summary_paths": "只改动了这些地方（其余逐项比对一致）：",
        "summary_check": "重建后的存档可以正常加载：{ok}",
        "parts_info": "{parts} 个零件 · 范围 {reach:.0f} m · 高度 {hmin:+.0f}..{hmax:+.0f} m · 基地电脑下方 {below} 个",
        "kind_planet": "星球基地",
        "kind_corvette": "护卫舰",
        "author": "作者",
        "steam_only": "支持 Steam / GOG 的 PC 存档；不支持 Game Pass 和主机。",
        "others_work": "别人的建筑是别人的作品：自己玩没问题，请不要当成自己的作品上传。",
        "lang_restart": "语言已切换。",
        "legend_structure": "结构",
        "legend_decor": "家具与装饰",
        "legend_tech": "电力与设备",
        "legend_other": "其他",
        "legend_anchor": "基地电脑 / 护卫舰核心",
        "auto": "自动（推荐）",
    },
    "en": {
        "title": "No Man's Sky Build Import",
        "lang": "Language",
        "save_folder": "Save folder",
        "change": "Change…",
        "default": "default",
        "libnom": "libNOM",
        "libnom_missing": "not found - keep the libNOM folder next to this program",
        "libnom_bundled": "ready (bundled)",
        "game": "Game",
        "game_running": "running (reading only, no writing)",
        "game_closed": "closed",
        "newest_save": "Newest save",
        "workspace": "Workspace",
        "open": "Open",
        "tab_save": "① Read save",
        "tab_import": "② Import",
        "tab_backups": "③ Backups",
        "scan": "Read save",
        "scan_hint": "Reads a copy only, fine with the game open (save in game first). Other players' bases rotate out quickly - extract what you like the same day.",
        "cached": "Other players' bases (cached)",
        "mine": "My bases",
        "ships": "Ships",
        "extract_selected": "Extract selected",
        "extract_all": "Extract all",
        "min_parts": "min parts",
        "col_name": "Name",
        "col_author": "Author",
        "col_parts": "Parts",
        "col_reach": "Reach m",
        "col_height": "Height m",
        "col_unlearned": "Unlearned",
        "col_type": "Type",
        "col_slot": "Slot",
        "col_model": "Model",
        "col_corvette": "Corvette parts",
        "col_state": "State",
        "col_created": "Created",
        "col_files": "Files",
        "flown": "flying",
        "empty_slot": "empty slot",
        "free_slots": "Free ship slots: {n} / {total}",
        "builds": "Build files",
        "refresh": "Refresh",
        "open_file": "Open file…",
        "preview": "Preview (from above, dots = parts)",
        "adjust": "Adjust",
        "rotate": "Rotate °",
        "lift": "Raise m",
        "trim": "Keep radius m",
        "drop_paragon": "Drop U_PARAGON (not placeable on planets)",
        "target": "Import into",
        "to_planet": "My planet base",
        "to_new_ship": "A new corvette",
        "to_replace_ship": "Overwrite my corvette",
        "ship_name": "New ship name",
        "template": "Copy tech from",
        "learn": "Learn the parts the build uses (recommended)",
        "rehearse": "Rehearse (no changes)",
        "apply": "Write to save",
        "need_scan": "Read the save on page ① first.",
        "need_build": "Pick a build file first.",
        "need_target": "Choose where to import.",
        "planet_help": "Planet base: place a base computer in game, give it a distinctive name, save, quit to desktop, then read the save again.",
        "ship_help": "New corvette: needs one empty ship slot (scrap a ship you do not need in game) and at least one corvette of your own.",
        "replace_help": "Overwrite: switch to a different ship in game first.",
        "rehearse_ok": "Rehearsal passed; nothing on disk changed. Click \"Write to save\" when you are happy.",
        "confirm_apply": "About to write to your save:\n\n{what}\n\nThe whole save folder is backed up first, the result is read back and checked, and any failure restores it.\nMake sure the game is fully closed. Continue?",
        "applied": "Written and verified.\n\nBackup: {backup}\n\nCheck it in game; to undo, restore this backup on page ③.",
        "after_apply": "The save changed - read it again before the next import.",
        "backups": "Backups (newest first)",
        "restore": "Restore selected",
        "open_folder": "Open backup folder",
        "confirm_restore": "Restore the save to this backup:\n{name}\n\nProgress made in game since then is lost. A safety backup of the current state is made first. Continue?",
        "restored": "Restored and verified file by file.\nSafety backup of the previous state: {safety}",
        "busy": "Working: {what}…",
        "ready": "Ready",
        "error": "Error",
        "log": "Log",
        "extracted": "Extracted {n} builds to {dir}",
        "nothing_cached": "No other player's base with {n}+ parts is cached. Visit some bases in game, save, and read again.",
        "summary_parts": "Parts: {before} → {after}",
        "summary_learn": "Newly learned parts: {n} kinds",
        "summary_target": "Target: {target}",
        "summary_ship": "New ship: slot {slot} \"{name}\", tech copied from \"{template}\"",
        "summary_paths": "Only these places changed (everything else compared equal):",
        "summary_check": "Rebuilt save loads: {ok}",
        "parts_info": "{parts} parts · reach {reach:.0f} m · height {hmin:+.0f}..{hmax:+.0f} m · {below} below the base computer",
        "kind_planet": "planet base",
        "kind_corvette": "corvette",
        "author": "by",
        "steam_only": "PC saves from Steam / GOG; not Game Pass or consoles.",
        "others_work": "Other players' builds are their work: enjoy them, do not re-upload them as yours.",
        "lang_restart": "Language changed.",
        "legend_structure": "structure",
        "legend_decor": "furniture & decor",
        "legend_tech": "power & tech",
        "legend_other": "other",
        "legend_anchor": "base computer / corvette core",
        "auto": "automatic (recommended)",
    },
}

# the pipeline speaks English; the most common refusals get a translation in front
ERROR_HINTS = {
    "is running": {"zh": "游戏正在运行：请在游戏里存档并退回桌面后再试。"},
    "ship slots are taken": {"zh": "飞船槽位已满：请在游戏里拆掉一艘不需要的船，存档退出后重新读取存档。"},
    "expected exactly one planet base": {"zh": "找不到这个名字的基地：确认游戏里已放好基地电脑并存档，然后重新读取存档。"},
    "currently flying": {"zh": "这艘护卫舰正在驾驶中：请在游戏里换开另一艘船，存档退出后再试。"},
    "re-scan first": {"zh": "读取存档之后游戏又写过存档：请重新读取存档。"},
    "libNOM.io.cli was not found": {"zh": "找不到 libNOM：请把 libNOM 文件夹和本程序放在同一个文件夹里。"},
    "has none": {"zh": "存档里没有你自己的护卫舰：新船要复制一艘现有护卫舰的型号和科技。"},
}


def load_settings() -> dict[str, Any]:
    try:
        return json.loads(SETTINGS_PATH.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def save_settings(settings: dict[str, Any]) -> None:
    try:
        SETTINGS_PATH.parent.mkdir(parents=True, exist_ok=True)
        SETTINGS_PATH.write_text(json.dumps(settings, ensure_ascii=False, indent=2), encoding="utf-8")
    except OSError:
        pass


class LogWriter:
    """File-like object that forwards the pipeline's prints to the app's log pane."""

    def __init__(self, sink: Callable[[str], None]):
        self.sink = sink

    def write(self, text: str) -> int:
        if text:
            self.sink(text)
        return len(text)

    def flush(self) -> None:
        pass


class App:
    def __init__(self, root: tk.Tk):
        self.root = root
        self.settings = load_settings()
        self.lang = self.settings.get("lang", "zh")
        self.events: queue.Queue = queue.Queue()
        self.busy = False
        self.save: dict[str, Any] | None = None
        self.report: dict[str, Any] | None = None
        self.build_path: Path | None = None
        self.build: dict[str, Any] | None = None
        self.rehearsal: dict[str, Any] | None = None
        self.rehearsal_key: tuple | None = None
        self.log_lines: list[str] = []
        self.status_text = ""
        self.workspace = Path(self.settings.get("workspace") or DEFAULT_WORKSPACE)
        if self.settings.get("save_root"):
            os.environ["NMS_SAVE_ROOT"] = self.settings["save_root"]
        self.root.title(f"{self.t('title')}  {APP_VERSION}")
        self.root.geometry("1180x800")
        self.root.minsize(980, 680)
        self.build_ui()
        self.root.after(100, self.pump)
        self.root.after(300, self.refresh_status)

    # ------------------------------------------------------------------ plumbing

    def t(self, key: str, **values: Any) -> str:
        text = TEXT[self.lang].get(key) or TEXT["en"].get(key, key)
        return text.format(**values) if values else text

    def log(self, text: str) -> None:
        self.events.put(("log", text))

    def explain(self, error: BaseException) -> str:
        message = str(error) or error.__class__.__name__
        for needle, hints in ERROR_HINTS.items():
            if needle in message and self.lang in hints:
                return f"{hints[self.lang]}\n\n{message}"
        return message

    def run(self, what: str, work: Callable[[], Any], done: Callable[[Any], None]) -> None:
        if self.busy:
            return
        self.set_busy(True, what)
        writer = LogWriter(self.log)

        def worker() -> None:
            try:
                with contextlib.redirect_stdout(writer), contextlib.redirect_stderr(writer):
                    result = work()
                self.events.put(("done", done, result))
            except Exception as error:  # surfaced to the player, never swallowed
                self.events.put(("fail", error, None))

        threading.Thread(target=worker, daemon=True).start()

    def pump(self) -> None:
        try:
            while True:
                kind, first, second = (*self.events.get_nowait(), None)[:3]
                if kind == "log":
                    self.append_log(first)
                elif kind == "done":
                    self.set_busy(False)
                    first(second)
                    self.update_apply_state()
                elif kind == "fail":
                    self.set_busy(False)
                    self.update_apply_state()
                    self.append_log(f"\n[{self.t('error')}] {first}\n")
                    messagebox.showerror(self.t("error"), self.explain(first), parent=self.root)
                elif kind == "status":
                    self.apply_status(first)
        except queue.Empty:
            pass
        self.root.after(100, self.pump)

    def set_busy(self, busy: bool, what: str = "") -> None:
        self.busy = busy
        self.status_var.set(self.t("busy", what=what) if busy else self.t("ready"))
        state = "disabled" if busy else "normal"
        for button in self.action_buttons:
            button.configure(state=state)
        if busy and hasattr(self, "apply_button"):
            self.apply_button.configure(state="disabled")
        self.root.configure(cursor="watch" if busy else "")

    def append_log(self, text: str) -> None:
        self.log_lines.append(text)
        self.log_text.configure(state="normal")
        self.log_text.insert("end", text)
        self.log_text.see("end")
        self.log_text.configure(state="disabled")

    # ------------------------------------------------------------------ layout

    def build_ui(self) -> None:
        for child in self.root.winfo_children():
            child.destroy()
        self.action_buttons: list[ttk.Button] = []
        self.root.title(f"{self.t('title')}  {APP_VERSION}")

        top = ttk.Frame(self.root, padding=(10, 8, 10, 0))
        top.pack(fill="x")
        side = ttk.Frame(top)
        side.pack(side="right", anchor="n")  # packed first so long paths cannot push it off screen
        self.info_var = tk.StringVar()
        ttk.Label(top, textvariable=self.info_var, justify="left", wraplength=880).pack(side="left", fill="x",
                                                                                     expand=True, anchor="nw")
        ttk.Label(side, text=self.t("lang")).grid(row=0, column=0, sticky="e")
        lang = ttk.Combobox(side, values=["中文", "English"], width=9, state="readonly")
        lang.set("中文" if self.lang == "zh" else "English")
        lang.bind("<<ComboboxSelected>>", lambda _e: self.switch_language("zh" if lang.get() == "中文" else "en"))
        lang.grid(row=0, column=1, padx=(4, 0))
        ttk.Button(side, text=f"{self.t('save_folder')} {self.t('change')}", command=self.choose_save_root).grid(
            row=1, column=0, columnspan=2, sticky="ew", pady=(4, 0))
        ttk.Button(side, text=f"{self.t('workspace')} {self.t('open')}", command=lambda: self.open_path(self.workspace)).grid(
            row=2, column=0, columnspan=2, sticky="ew", pady=(4, 0))

        bottom = ttk.Frame(self.root, padding=(10, 0, 10, 6))
        bottom.pack(side="bottom", fill="x")  # packed before the panes so it always keeps its row
        self.status_var = tk.StringVar(value=self.t("ready"))
        ttk.Label(bottom, textvariable=self.status_var).pack(side="left")
        ttk.Label(bottom, text=f"{self.t('steam_only')}  {self.t('others_work')}", foreground="#6f7a76").pack(side="right")

        panes = ttk.PanedWindow(self.root, orient="vertical")
        panes.pack(fill="both", expand=True, padx=10, pady=8)
        self.tabs = ttk.Notebook(panes)
        panes.add(self.tabs, weight=5)
        self.build_save_tab()
        self.build_import_tab()
        self.build_backup_tab()

        log_frame = ttk.LabelFrame(panes, text=self.t("log"), padding=4)
        panes.add(log_frame, weight=1)
        self.log_text = tk.Text(log_frame, height=7, wrap="word", state="disabled", font=("Consolas", 9))
        scroll = ttk.Scrollbar(log_frame, command=self.log_text.yview)
        self.log_text.configure(yscrollcommand=scroll.set)
        self.log_text.pack(side="left", fill="both", expand=True)
        scroll.pack(side="right", fill="y")
        if self.log_lines:
            self.log_text.configure(state="normal")
            self.log_text.insert("end", "".join(self.log_lines))
            self.log_text.see("end")
            self.log_text.configure(state="disabled")
        self.apply_status(self.status_text)
        if self.report:
            self.fill_report()
        self.refresh_builds()
        self.refresh_backups()

    def tree(self, parent: tk.Widget, columns: list[tuple[str, str, int]], height: int = 8) -> ttk.Treeview:
        frame = ttk.Frame(parent)
        frame.pack(fill="both", expand=True)
        view = ttk.Treeview(frame, columns=[c[0] for c in columns], show="headings", height=height,
                            selectmode="extended")
        for key, label, width in columns:
            view.heading(key, text=self.t(label))
            view.column(key, width=width, anchor="w" if key in ("name", "author", "type", "model", "state") else "e")
        scroll = ttk.Scrollbar(frame, command=view.yview)
        view.configure(yscrollcommand=scroll.set)
        view.pack(side="left", fill="both", expand=True)
        scroll.pack(side="right", fill="y")
        return view

    def button(self, parent: tk.Widget, key: str, command: Callable[[], None], **pack: Any) -> ttk.Button:
        widget = ttk.Button(parent, text=self.t(key), command=command)
        widget.pack(**({"side": "left", "padx": (0, 6)} | pack))
        self.action_buttons.append(widget)
        return widget

    # ------------------------------------------------------------------ page 1: read save

    def build_save_tab(self) -> None:
        page = ttk.Frame(self.tabs, padding=8)
        self.tabs.add(page, text=self.t("tab_save"))
        bar = ttk.Frame(page)
        bar.pack(fill="x")
        self.button(bar, "scan", self.scan)
        ttk.Label(bar, text=self.t("scan_hint"), foreground="#4a5552", wraplength=820).pack(side="left", fill="x")

        lists = ttk.Notebook(page)
        lists.pack(fill="both", expand=True, pady=(8, 0))

        cached = ttk.Frame(lists, padding=6)
        lists.add(cached, text=self.t("cached"))
        self.cached_view = self.tree(cached, [("name", "col_name", 230), ("author", "col_author", 140),
                                              ("parts", "col_parts", 70), ("reach", "col_reach", 80),
                                              ("height", "col_height", 100), ("unlearned", "col_unlearned", 80)])
        row = ttk.Frame(cached)
        row.pack(fill="x", pady=(6, 0))
        self.button(row, "extract_selected", lambda: self.extract_rows(self.cached_view, "planet"))
        self.button(row, "extract_all", self.extract_all)
        ttk.Label(row, text=self.t("min_parts")).pack(side="left")
        self.min_parts = tk.StringVar(value=str(self.settings.get("min_parts", 50)))
        ttk.Spinbox(row, from_=1, to=5000, increment=50, width=6, textvariable=self.min_parts).pack(side="left", padx=4)

        mine = ttk.Frame(lists, padding=6)
        lists.add(mine, text=self.t("mine"))
        self.mine_view = self.tree(mine, [("name", "col_name", 260), ("type", "col_type", 170),
                                          ("parts", "col_parts", 70), ("reach", "col_reach", 80),
                                          ("height", "col_height", 100)])
        row = ttk.Frame(mine)
        row.pack(fill="x", pady=(6, 0))
        self.button(row, "extract_selected", lambda: self.extract_rows(self.mine_view, "planet"))

        ships = ttk.Frame(lists, padding=6)
        lists.add(ships, text=self.t("ships"))
        self.ships_view = self.tree(ships, [("slot", "col_slot", 50), ("name", "col_name", 200),
                                            ("model", "col_model", 240), ("corvette", "col_corvette", 110),
                                            ("state", "col_state", 120)])
        row = ttk.Frame(ships)
        row.pack(fill="x", pady=(6, 0))
        self.button(row, "extract_selected", lambda: self.extract_rows(self.ships_view, "corvette"))
        self.slots_var = tk.StringVar()
        ttk.Label(row, textvariable=self.slots_var).pack(side="left", padx=8)

    def scan(self) -> None:
        def work() -> tuple:
            libnom = ns.find_libnom()
            profile = ns.locate_profile(ns.locate_nms_root())
            save_name = ns.pick_save_name(profile)
            print(f"{profile / save_name}")
            with tempfile.TemporaryDirectory(prefix="nms_app_scan_") as raw:
                save, flags, hashes = ns.read_copy(libnom, profile, save_name, Path(raw), "scan")
            report = scan_save.make_report(save, flags, hashes, profile, save_name, ns.load_catalog())
            return save, report

        def done(result: tuple) -> None:
            self.save, self.report = result
            self.rehearsal = None
            self.fill_report()
            report = self.report
            self.log(f"save version {report['save_version']} | {len(report['mine'])} own records | "
                     f"{len(report['cached'])} cached | {sum(1 for s in report['ships'] if s['empty'])} free ship slots\n")

        self.run(self.t("scan"), work, done)

    def fill_report(self) -> None:
        report = self.report or {"cached": [], "mine": [], "ships": []}
        for view in (self.cached_view, self.mine_view, self.ships_view):
            view.delete(*view.get_children())
        for row in sorted(report["cached"], key=lambda r: -r["parts"]):
            self.cached_view.insert("", "end", iid=str(row["index"]), values=(
                row["name"], row["author"], row["parts"], f"{row['reach_m']:.0f}",
                f"{row['height_min_m']:+.0f}..{row['height_max_m']:+.0f}", row["unlearned_kinds"]))
        for row in report["mine"]:
            if row["type"] in ("HomePlanetBase",):
                self.mine_view.insert("", "end", iid=str(row["index"]), values=(
                    row["name"], row["type"], row["parts"], f"{row['reach_m']:.0f}",
                    f"{row['height_min_m']:+.0f}..{row['height_max_m']:+.0f}"))
        for ship in report["ships"]:
            state = self.t("empty_slot") if ship["empty"] else (self.t("flown") if ship["is_primary"] else "")
            self.ships_view.insert("", "end", iid=str(ship["index"]), values=(
                ship["index"], ship["name"], ship["model"],
                ship["corvette_build_parts"] if ship["corvette_build_parts"] is not None else "", state))
        free = sum(1 for s in report["ships"] if s["empty"])
        self.slots_var.set(self.t("free_slots", n=free, total=len(report["ships"])) if report["ships"] else "")
        self.fill_targets()

    def builds_dir(self) -> Path:
        folder = self.workspace / "builds" / datetime.now().strftime("%Y-%m-%d")
        folder.mkdir(parents=True, exist_ok=True)
        return folder

    def extract_rows(self, view: ttk.Treeview, kind: str) -> None:
        if not self.save:
            messagebox.showinfo(APP_NAME, self.t("need_scan"), parent=self.root)
            return
        chosen = [int(i) for i in view.selection()]
        if not chosen:
            return
        self.extract(chosen, kind)

    def extract_all(self) -> None:
        if not self.report:
            messagebox.showinfo(APP_NAME, self.t("need_scan"), parent=self.root)
            return
        try:
            minimum = max(1, int(self.min_parts.get()))
        except ValueError:
            minimum = 50
        self.settings["min_parts"] = minimum
        save_settings(self.settings)
        chosen = [r["index"] for r in self.report["cached"] if r["parts"] >= minimum]
        if not chosen:
            messagebox.showinfo(APP_NAME, self.t("nothing_cached", n=minimum), parent=self.root)
            return
        self.extract(chosen, "planet")

    def extract(self, indices: list[int], kind: str) -> None:
        save, report = self.save, self.report
        out = self.builds_dir()

        def work() -> list[Path]:
            player = ns.get_player(save)
            bases = player["PersistentPlayerBases"]
            known = {ns.strip(k) for k in player.get("KnownProducts", []) if isinstance(k, str)}
            catalog = ns.load_catalog()
            written = []
            for index in indices:
                if kind == "corvette":
                    records = ns.ship_build_records(player)
                    if index not in records:
                        print(f"slot {index}: no corvette build")
                        continue
                    base, anchor = bases[records[index]], extract_build.CORVETTE_ANCHOR
                    name = (player["ShipOwnership"][index].get("Name") or "").strip() or f"corvette slot {index}"
                else:
                    base, anchor, name = bases[index], extract_build.PLANET_ANCHOR, None
                args = SimpleNamespace(out=out, keep_duplicates=False, corvette=kind == "corvette", views=True)
                try:
                    written.append(extract_build.extract_one(base, anchor, args, report["save"],
                                                             Path(report["profile"]), known, catalog, name))
                except ValueError as error:
                    print(f"skipped {base.get('Name') or name}: {error}")
            return written

        def done(written: list[Path]) -> None:
            self.log(self.t("extracted", n=len(written), dir=out) + "\n")
            self.refresh_builds(select=written[0] if written else None)
            if written:
                self.tabs.select(1)

        self.run(self.t("extract_selected"), work, done)

    # ------------------------------------------------------------------ page 2: import

    def build_import_tab(self) -> None:
        page = ttk.Frame(self.tabs, padding=8)
        self.tabs.add(page, text=self.t("tab_import"))
        page.columnconfigure(1, weight=1)
        page.rowconfigure(0, weight=1)

        left = ttk.LabelFrame(page, text=self.t("builds"), padding=6)
        left.grid(row=0, column=0, sticky="nsw", padx=(0, 8))
        self.build_list = tk.Listbox(left, width=42, activestyle="none", exportselection=False)
        self.build_list.pack(fill="both", expand=True)
        self.build_list.bind("<<ListboxSelect>>", lambda _e: self.pick_build_from_list())
        row = ttk.Frame(left)
        row.pack(fill="x", pady=(6, 0))
        ttk.Button(row, text=self.t("refresh"), command=self.refresh_builds).pack(side="left", padx=(0, 6))
        ttk.Button(row, text=self.t("open_file"), command=self.open_build_file).pack(side="left")
        self.build_files: list[Path] = []

        middle = ttk.Frame(page)
        middle.grid(row=0, column=1, sticky="nsew")
        middle.rowconfigure(0, weight=1)
        middle.columnconfigure(0, weight=1)
        preview = ttk.LabelFrame(middle, text=self.t("preview"), padding=4)
        preview.grid(row=0, column=0, sticky="nsew")
        self.canvas = tk.Canvas(preview, background="#fbfcfb", highlightthickness=0)
        self.canvas.pack(fill="both", expand=True)
        self.canvas.bind("<Configure>", lambda _e: self.draw_preview())
        self.build_info = tk.StringVar()
        ttk.Label(middle, textvariable=self.build_info, wraplength=560, justify="left").grid(row=1, column=0, sticky="w", pady=4)

        adjust = ttk.LabelFrame(middle, text=self.t("adjust"), padding=6)
        adjust.grid(row=2, column=0, sticky="ew")
        self.rotate_var, self.lift_var, self.trim_var = tk.StringVar(value="0"), tk.StringVar(value="0"), tk.StringVar()
        self.drop_paragon = tk.BooleanVar(value=True)
        for col, (key, var) in enumerate((("rotate", self.rotate_var), ("lift", self.lift_var), ("trim", self.trim_var))):
            ttk.Label(adjust, text=self.t(key)).grid(row=0, column=col * 2, sticky="e", padx=(0 if col == 0 else 10, 4))
            ttk.Entry(adjust, textvariable=var, width=7).grid(row=0, column=col * 2 + 1)
            var.trace_add("write", lambda *_: self.root.after_idle(self.on_adjust))
        ttk.Checkbutton(adjust, text=self.t("drop_paragon"), variable=self.drop_paragon,
                        command=self.on_adjust).grid(row=1, column=0, columnspan=6, sticky="w", pady=(4, 0))

        right = ttk.LabelFrame(page, text=self.t("target"), padding=8)
        right.grid(row=0, column=2, sticky="nse", padx=(8, 0))
        self.target_kind = tk.StringVar(value="planet")
        ttk.Radiobutton(right, text=self.t("to_planet"), value="planet", variable=self.target_kind,
                        command=self.on_target).pack(anchor="w")
        self.planet_box = ttk.Combobox(right, state="readonly", width=30)
        self.planet_box.pack(anchor="w", padx=(18, 0), pady=(2, 8))
        ttk.Radiobutton(right, text=self.t("to_new_ship"), value="new_ship", variable=self.target_kind,
                        command=self.on_target).pack(anchor="w")
        ship_frame = ttk.Frame(right)
        ship_frame.pack(anchor="w", padx=(18, 0), pady=(2, 8))
        ttk.Label(ship_frame, text=self.t("ship_name")).grid(row=0, column=0, sticky="w")
        self.ship_name = tk.StringVar()
        ttk.Entry(ship_frame, textvariable=self.ship_name, width=18).grid(row=0, column=1, padx=4)
        ttk.Label(ship_frame, text=self.t("template")).grid(row=1, column=0, sticky="w", pady=(4, 0))
        self.template_box = ttk.Combobox(ship_frame, state="readonly", width=18)
        self.template_box.grid(row=1, column=1, padx=4, pady=(4, 0))
        ttk.Radiobutton(right, text=self.t("to_replace_ship"), value="replace_ship", variable=self.target_kind,
                        command=self.on_target).pack(anchor="w")
        self.replace_box = ttk.Combobox(right, state="readonly", width=30)
        self.replace_box.pack(anchor="w", padx=(18, 0), pady=(2, 8))
        self.learn = tk.BooleanVar(value=True)
        ttk.Checkbutton(right, text=self.t("learn"), variable=self.learn,
                        command=self.update_apply_state).pack(anchor="w", pady=(4, 6))
        self.help_var = tk.StringVar()
        ttk.Label(right, textvariable=self.help_var, wraplength=270, foreground="#4a5552",
                  justify="left").pack(anchor="w", pady=(0, 8))
        for box in (self.planet_box, self.template_box, self.replace_box):
            box.bind("<<ComboboxSelected>>", lambda _e: self.update_apply_state())
        self.ship_name.trace_add("write", lambda *_: self.update_apply_state())
        buttons = ttk.Frame(right)
        buttons.pack(fill="x")
        self.button(buttons, "rehearse", self.rehearse)
        self.apply_button = ttk.Button(buttons, text=self.t("apply"), command=self.apply)
        self.apply_button.pack(side="left")
        self.result_text = tk.Text(right, width=38, height=14, wrap="word", state="disabled",
                                   font=("Microsoft YaHei UI", 9))
        self.result_text.pack(fill="both", expand=True, pady=(8, 0))
        self.on_target()

    def refresh_builds(self, select: Path | None = None) -> None:
        root = self.workspace / "builds"
        files = sorted(root.rglob("* - build.json"), key=lambda p: p.stat().st_mtime, reverse=True) if root.is_dir() else []
        if self.build_path and self.build_path not in files and self.build_path.is_file():
            files.insert(0, self.build_path)
        self.build_files = files
        self.build_list.delete(0, "end")
        for path in files:
            try:
                label = str(path.relative_to(root))
            except ValueError:
                label = str(path)
            self.build_list.insert("end", label.replace(" - build.json", ""))
        target = select or self.build_path
        if target in files:
            index = files.index(target)
            self.build_list.selection_set(index)
            self.build_list.see(index)
            if select:
                self.load_build(select)

    def pick_build_from_list(self) -> None:
        chosen = self.build_list.curselection()
        if chosen:
            self.load_build(self.build_files[chosen[0]])

    def open_build_file(self) -> None:
        name = filedialog.askopenfilename(parent=self.root, filetypes=[("build", "*.json"), ("*", "*.*")])
        if name:
            self.load_build(Path(name))
            self.refresh_builds()

    def load_build(self, path: Path) -> None:
        try:
            build = json.loads(path.read_text(encoding="utf-8"))
            if not build.get("Objects"):
                raise ValueError("no Objects")
        except (OSError, ValueError) as error:
            messagebox.showerror(self.t("error"), f"{path}\n{error}", parent=self.root)
            return
        self.build_path, self.build = path, build
        self.rehearsal = self.rehearsal_key = None
        self.show_result("")
        corvette = build.get("BuildKind") == "corvette" or build["Objects"][0].get("ObjectID") == "^U_PARAGON"
        if corvette and self.target_kind.get() == "planet":
            self.target_kind.set("new_ship")
        elif not corvette and self.target_kind.get() != "planet":
            self.target_kind.set("planet")
        self.drop_paragon.set(not corvette)
        name = build.get("Name") if build.get("Name") not in (None, "", "Default") else path.stem.replace(" - build", "")
        self.ship_name.set(name[:30])
        self.rotate_var.set("0")
        self.lift_var.set("0")
        self.trim_var.set("")
        self.on_target()
        self.on_adjust()

    def adjusted_build(self) -> dict[str, Any] | None:
        if not self.build:
            return None
        rotate = float(self.rotate_var.get() or 0)
        lift = float(self.lift_var.get() or 0)
        trim = float(self.trim_var.get()) if self.trim_var.get().strip() else None
        stray_core = any(o.get("ObjectID") == "^U_PARAGON" for o in self.build["Objects"][1:])
        drop = ["U_PARAGON"] if self.drop_paragon.get() and self.target_kind.get() == "planet" and stray_core else []
        if not (rotate or lift or trim is not None or drop):
            return self.build
        return transform_build.transform(self.build, rotate, None, lift, trim, drop)

    def on_adjust(self) -> None:
        try:
            build = self.adjusted_build()
        except (ValueError, KeyError) as error:
            self.build_info.set(str(error))
            return
        self.preview_build = build
        if build:
            objects = build["Objects"]
            heights = [o["Position"][1] for o in objects]
            corvette = objects[0].get("ObjectID") == "^U_PARAGON"
            info = self.t("parts_info", parts=len(objects), reach=max(ns.horizontal(o["Position"]) for o in objects),
                          hmin=min(heights), hmax=max(heights), below=sum(1 for h in heights if h < -2))
            author = f"  ·  {self.t('author')} {build['Author']}" if build.get("Author") else ""
            kind = self.t("kind_corvette" if corvette else "kind_planet")
            self.build_info.set(f"{build.get('Name', '')} ({kind}){author}\n{info}")
        self.draw_preview()
        self.update_apply_state()

    def draw_preview(self) -> None:
        canvas = self.canvas
        canvas.delete("all")
        build = getattr(self, "preview_build", None)
        if not build:
            return
        width, height = max(canvas.winfo_width(), 50), max(canvas.winfo_height(), 50)
        objects = build["Objects"]
        xs = [o["Position"][0] for o in objects]
        zs = [o["Position"][2] for o in objects]
        span = max(max(xs) - min(xs), max(zs) - min(zs), 10.0)
        scale = (min(width, height) - 30) / span
        cx, cz = (max(xs) + min(xs)) / 2, (max(zs) + min(zs)) / 2
        for ring in (25, 50, 100, 200):
            r = ring * scale
            if r < min(width, height):
                ox, oz = width / 2 + (0 - cx) * scale, height / 2 + (0 - cz) * scale
                canvas.create_oval(ox - r, oz - r, ox + r, oz + r, outline="#dde3e0")
                canvas.create_text(ox + r * 0.71 + 4, oz - r * 0.71, text=f"{ring} m", fill="#6f7a76", anchor="w",
                                   font=("Segoe UI", 8))
        for obj in sorted(objects, key=lambda o: o["Position"][1]):
            x = width / 2 + (obj["Position"][0] - cx) * scale
            y = height / 2 + (obj["Position"][2] - cz) * scale
            colour = COLOURS[make_views.category(obj["ObjectID"])]
            canvas.create_rectangle(x - 1.5, y - 1.5, x + 1.5, y + 1.5, fill=colour, outline="")
        ox, oz = width / 2 + (0 - cx) * scale, height / 2 + (0 - cz) * scale
        canvas.create_oval(ox - 5, oz - 5, ox + 5, oz + 5, outline="#121a18", width=2)
        for i, key in enumerate(("legend_structure", "legend_decor", "legend_tech", "legend_other")):
            canvas.create_rectangle(10, 10 + i * 16, 20, 20 + i * 16, fill=COLOURS[i], outline="")
            canvas.create_text(26, 15 + i * 16, text=self.t(key), anchor="w", fill="#4a5552")
        canvas.create_text(26, 15 + 4 * 16, text=self.t("legend_anchor"), anchor="w", fill="#4a5552")
        canvas.create_oval(11, 11 + 4 * 16, 19, 19 + 4 * 16, outline="#121a18", width=2)

    def fill_targets(self) -> None:
        if not hasattr(self, "planet_box"):
            return
        report = self.report or {"mine": [], "ships": []}
        self.planets = [r["name"] for r in report["mine"] if r["type"] == "HomePlanetBase"]
        self.corvettes = [s for s in report["ships"] if s["corvette_build_parts"] is not None]
        self.planet_box.configure(values=self.planets)
        labels = [f"{s['index']}: {s['name'] or '(unnamed)'}" + (f" ({self.t('flown')})" if s["is_primary"] else "")
                  for s in self.corvettes]
        # "automatic" lets the importer pick a regular corvette record, the layout verified in game
        self.template_box.configure(values=[self.t("auto")] + labels)
        self.replace_box.configure(values=labels)
        if self.template_box.get() not in self.template_box.cget("values"):
            self.template_box.current(0)
        self.update_apply_state()

    def on_target(self) -> None:
        kind = self.target_kind.get()
        self.help_var.set(self.t({"planet": "planet_help", "new_ship": "ship_help",
                                  "replace_ship": "replace_help"}[kind]))
        if hasattr(self, "build_info"):
            self.on_adjust()

    def import_request(self) -> dict[str, Any]:
        kind = self.target_kind.get()
        request: dict[str, Any] = {"kind": "planet" if kind == "planet" else "corvette", "learn": self.learn.get()}
        if kind == "planet":
            if not self.planet_box.get():
                raise ValueError(self.t("need_target"))
            request["target"] = self.planet_box.get()
        elif kind == "new_ship":
            request["new_ship"] = True
            request["ship_name"] = self.ship_name.get().strip() or None
            if self.template_box.current() > 0:
                request["template_slot"] = int(self.template_box.get().split(":")[0])
        else:
            if not self.replace_box.get():
                raise ValueError(self.t("need_target"))
            request["ship_index"] = int(self.replace_box.get().split(":")[0])
        return request

    def current_key(self) -> tuple | None:
        try:
            build = self.adjusted_build()
            request = self.import_request()
        except (ValueError, KeyError):
            return None
        if not build or not self.report:
            return None
        return (json.dumps(build["Objects"], sort_keys=True), json.dumps(request, sort_keys=True),
                self.report["save_sha256"])

    def update_apply_state(self) -> None:
        if not hasattr(self, "apply_button"):
            return
        ready = (not self.busy and self.rehearsal is not None and self.rehearsal_key is not None
                 and self.rehearsal_key == self.current_key())
        self.apply_button.configure(state="normal" if ready else "disabled")

    def staged_build_file(self) -> Path:
        """The exact build being imported, kept on disk next to its change log."""
        build = self.adjusted_build()
        if build is self.build:
            return self.build_path
        folder = self.workspace / "builds" / "adjusted"
        folder.mkdir(parents=True, exist_ok=True)
        path = folder / f"{self.build_path.stem.replace(' - build', '')} (adjusted) - build.json"
        path.write_text(json.dumps(build, ensure_ascii=False, indent=1), encoding="utf-8")
        return path

    def rehearse(self) -> None:
        if not self.report:
            messagebox.showinfo(APP_NAME, self.t("need_scan"), parent=self.root)
            return
        if not self.build:
            messagebox.showinfo(APP_NAME, self.t("need_build"), parent=self.root)
            return
        try:
            request = self.import_request()
            path = self.staged_build_file()
        except ValueError as error:
            messagebox.showinfo(APP_NAME, str(error), parent=self.root)
            return
        key = self.current_key()
        expect = self.report["save_sha256"]

        def work() -> dict[str, Any]:
            return import_build.run_import(path, apply=False, expect_save_sha256=expect, **request)

        def done(summary: dict[str, Any]) -> None:
            self.rehearsal, self.rehearsal_key = summary | {"_path": str(path), "_request": request}, key
            self.show_result(self.describe(summary) + "\n\n" + self.t("rehearse_ok"))
            self.update_apply_state()

        self.rehearsal = None
        self.update_apply_state()
        self.run(self.t("rehearse"), work, done)

    def describe(self, summary: dict[str, Any]) -> str:
        target, mutation = summary["target"], summary["mutation"]
        kind = ("to_new_ship" if mutation.get("new_ship") else
                "to_planet" if target["type"] == "HomePlanetBase" else "to_replace_ship")
        lines = [self.t("summary_target", target=f"{self.t(kind)} \"{target['name']}\""),
                 self.t("summary_parts", before=target["objects_before"], after=mutation["objects_after"]),
                 self.t("summary_learn", n=len(mutation["added_known_products"]))]
        if mutation.get("new_ship"):
            ship = mutation["new_ship"]
            lines.append(self.t("summary_ship", slot=ship["slot"], name=ship["name"], template=ship["copied_from_name"]))
        analyze = summary.get("live_analyze") or summary.get("staged_analyze") or {}
        lines.append(self.t("summary_check", ok="✓" if analyze.get("IsLoaded") == "True" else "✗"))
        lines.append(self.t("summary_paths"))
        lines += [f"  · {p.replace('BaseContext.PlayerStateData.', '')}"
                  for p in summary["semantic_verification"]["allowed_paths"]]
        lines += summary.get("warnings", [])
        return "\n".join(lines)

    def show_result(self, text: str) -> None:
        self.result_text.configure(state="normal")
        self.result_text.delete("1.0", "end")
        self.result_text.insert("end", text)
        self.result_text.configure(state="disabled")

    def apply(self) -> None:
        rehearsal = self.rehearsal
        if not rehearsal or self.rehearsal_key != self.current_key():
            self.update_apply_state()
            return
        if not messagebox.askyesno(APP_NAME, self.t("confirm_apply", what=self.describe(rehearsal)),
                                   icon="warning", parent=self.root):
            return
        path, request = Path(rehearsal["_path"]), rehearsal["_request"]

        def work() -> dict[str, Any]:
            return import_build.run_import(path, apply=True, expect_save_sha256=rehearsal["save_sha256_before"],
                                           **request)

        def done(summary: dict[str, Any]) -> None:
            self.rehearsal = self.rehearsal_key = None
            self.save = self.report = None
            self.fill_report()
            self.show_result(self.describe(summary) + "\n\n" + self.t("applied", backup=summary["backup"])
                             + "\n\n" + self.t("after_apply"))
            self.log(f"written; backup {summary['backup']}; change log {summary.get('change_log')}\n")
            self.refresh_backups()
            messagebox.showinfo(APP_NAME, self.t("applied", backup=summary["backup"]), parent=self.root)

        self.run(self.t("apply"), work, done)

    # ------------------------------------------------------------------ page 3: backups

    def build_backup_tab(self) -> None:
        page = ttk.Frame(self.tabs, padding=8)
        self.tabs.add(page, text=self.t("tab_backups"))
        ttk.Label(page, text=self.t("backups")).pack(anchor="w")
        self.backup_view = self.tree(page, [("name", "col_name", 420), ("type", "col_created", 260),
                                            ("parts", "col_files", 80)], height=12)
        row = ttk.Frame(page)
        row.pack(fill="x", pady=(6, 0))
        ttk.Button(row, text=self.t("refresh"), command=self.refresh_backups).pack(side="left", padx=(0, 6))
        self.button(row, "restore", self.restore)
        ttk.Button(row, text=self.t("open_folder"),
                   command=lambda: self.open_path(ns.default_backup_root())).pack(side="left")
        self.backup_rows: list[dict[str, Any]] = []

    def refresh_backups(self) -> None:
        if not hasattr(self, "backup_view"):
            return
        self.backup_rows = ns.list_backups(ns.default_backup_root())
        self.backup_view.delete(*self.backup_view.get_children())
        for i, row in enumerate(self.backup_rows):
            self.backup_view.insert("", "end", iid=str(i), values=(row["name"], row["created"][:19].replace("T", " "),
                                                                   row["files"]))

    def restore(self) -> None:
        chosen = self.backup_view.selection()
        if not chosen:
            return
        row = self.backup_rows[int(chosen[0])]
        if not messagebox.askyesno(APP_NAME, self.t("confirm_restore", name=row["name"]), icon="warning",
                                   parent=self.root):
            return

        def work() -> dict[str, Any]:
            return ns.restore(Path(row["path"]), ns.locate_nms_root(), ns.default_backup_root())

        def done(result: dict[str, Any]) -> None:
            self.save = self.report = None
            self.rehearsal = self.rehearsal_key = None
            self.fill_report()
            self.refresh_backups()
            messagebox.showinfo(APP_NAME, self.t("restored", safety=result["pre_restore_safety_backup"]),
                                parent=self.root)

        self.run(self.t("restore"), work, done)

    # ------------------------------------------------------------------ status bar and settings

    def refresh_status(self) -> None:
        self.probe_status()
        self.root.after(4000, self.refresh_status)

    def probe_status(self) -> None:
        def probe() -> None:
            lines = []
            try:
                root = ns.locate_nms_root()
                profile = ns.locate_profile(root)
                saves = [r for r in ns.list_saves(profile) if r.get("timestamp")]
                newest = max(saves, key=lambda r: r["timestamp"]) if saves else None
                lines.append(f"{self.t('save_folder')}: {profile}")
                if newest:
                    lines.append(f"{self.t('newest_save')}: {newest['name']}  {newest.get('saved_at', '')}")
            except Exception as error:
                lines.append(f"{self.t('save_folder')}: {error}")
            try:
                libnom = ns.find_libnom()
                bundled = libnom.parent.parent == ns.APP_DIR or libnom.parent == ns.APP_DIR
                lines.append(f"{self.t('libnom')}: {self.t('libnom_bundled') if bundled else libnom}")
            except RuntimeError:
                lines.append(f"{self.t('libnom')}: {self.t('libnom_missing')}")
            running = ns.game_running()
            lines.append(f"{self.t('game')}: {self.t('game_running' if running else 'game_closed')}")
            self.events.put(("status", "\n".join(lines), None))

        threading.Thread(target=probe, daemon=True).start()

    def apply_status(self, text: str) -> None:
        self.status_text = text
        if hasattr(self, "info_var"):
            self.info_var.set(text)

    def choose_save_root(self) -> None:
        folder = filedialog.askdirectory(parent=self.root, title=self.t("save_folder"),
                                         initialdir=os.environ.get("NMS_SAVE_ROOT") or None)
        if not folder:
            return
        os.environ["NMS_SAVE_ROOT"] = folder
        self.settings["save_root"] = folder
        save_settings(self.settings)
        self.save = self.report = None
        self.fill_report()

    def switch_language(self, lang: str) -> None:
        if lang == self.lang:
            return
        self.lang = lang
        self.settings["lang"] = lang
        save_settings(self.settings)
        build_path = self.build_path
        self.build_ui()
        if build_path and build_path.is_file():
            self.load_build(build_path)
        self.probe_status()
        self.log(self.t("lang_restart") + "\n")

    @staticmethod
    def open_path(path: Path) -> None:
        path = Path(path)
        path.mkdir(parents=True, exist_ok=True)
        os.startfile(path)  # Windows-only app; the CLI covers other platforms


def self_check(out: Path) -> None:
    """NMS-Build-Import.exe --self-check report.json : read-only diagnosis without the window,
    for support and for testing a packaged build (it has no console to print to)."""
    result: dict[str, Any] = {"version": APP_VERSION, "frozen": ns.FROZEN, "app_dir": str(ns.APP_DIR)}
    try:
        catalog = ns.load_catalog()
        result["catalog_parts"] = len(catalog.get("base_parts", {}))
        libnom = ns.find_libnom()
        result["libnom"] = str(libnom)
        profile = ns.locate_profile(ns.locate_nms_root())
        save_name = ns.pick_save_name(profile)
        result["save"] = str(profile / save_name)
        with tempfile.TemporaryDirectory(prefix="nms_app_check_") as raw:
            save, flags, hashes = ns.read_copy(libnom, profile, save_name, Path(raw), "check")
        report = scan_save.make_report(save, flags, hashes, profile, save_name, catalog)
        result.update(ok=True, save_version=report["save_version"], own_records=len(report["mine"]),
                      cached=len(report["cached"]), free_ship_slots=sum(1 for s in report["ships"] if s["empty"]),
                      game_running=ns.game_running())
    except Exception as error:
        result.update(ok=False, error=f"{error.__class__.__name__}: {error}")
    out.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")


def main() -> None:
    if "--self-check" in sys.argv:
        self_check(Path(sys.argv[sys.argv.index("--self-check") + 1]))
        return
    if sys.platform == "win32":
        with contextlib.suppress(Exception):
            import ctypes
            ctypes.windll.shcore.SetProcessDpiAwareness(1)
    root = tk.Tk()
    with contextlib.suppress(tk.TclError):
        ttk.Style(root).theme_use("vista")
    root.option_add("*Font", ("Microsoft YaHei UI", 9))
    App(root)
    root.mainloop()


if __name__ == "__main__":
    main()
