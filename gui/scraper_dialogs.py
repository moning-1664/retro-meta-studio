"""
gui/scraper_dialogs.py
========================
Screen Scraper 연동 GUI (설계서 v2 §10, §18).
- 단건 스크랩: 검색 -> 후보 선택 -> 미리보기 -> 적용 (새 Version으로 MasterDB 저장)
- 일괄 스크랩: 다중 게임/시스템 대상 -> Progress -> 결과 리뷰 화면 -> 선택 저장
"""

import tkinter as tk
from tkinter import ttk, messagebox
from pathlib import Path

import db as dbmod
from scraper import screenscraper as ss
from gui.style import BG, PANEL, PANEL2, TEXT, MUTED, SUCCESS, WARNING, ERROR, ACCENT


class SingleScrapeDialog(tk.Toplevel):
    """Metadata/Media 탭 상단 [스크랩] 버튼에서 호출 (§10)."""

    def __init__(self, parent, cfg, db, masterdb_root, rom_entry, on_applied=None):
        super().__init__(parent)
        self.cfg = cfg
        self.db = db
        self.masterdb_root = masterdb_root
        self.rom_entry = rom_entry
        self.on_applied = on_applied
        self.search_result = None

        self.title(f"스크랩 - {rom_entry['rom_filename']}")
        self.configure(bg=BG)
        self.geometry("500x480")
        self.transient(parent)
        self.grab_set()

        tk.Label(self, text=rom_entry["rom_filename"], bg=BG, fg=TEXT,
                 font=("Segoe UI", 11, "bold")).pack(anchor="w", padx=16, pady=(16, 4))

        search_row = tk.Frame(self, bg=BG); search_row.pack(fill="x", padx=16)
        self.search_var = tk.StringVar(value=dbmod.get_default_fields(rom_entry).get("name", ""))
        tk.Entry(search_row, textvariable=self.search_var, bg=PANEL2, fg=TEXT, bd=1, relief="flat", insertbackground=TEXT).pack(
            side="left", fill="x", expand=True
        )
        ttk.Button(search_row, text="검색", command=self._do_search).pack(side="left", padx=6)

        self.result_frame = tk.Frame(self, bg=BG)
        self.result_frame.pack(fill="both", expand=True, padx=16, pady=10)
        tk.Label(self.result_frame, text="검색 결과가 여기에 표시됩니다.", bg=BG, fg=MUTED).pack(pady=20)

        btn_row = tk.Frame(self, bg=BG); btn_row.pack(fill="x", padx=16, pady=12, side="bottom")
        ttk.Button(btn_row, text="닫기", command=self.destroy).pack(side="right")
        self.apply_btn = ttk.Button(btn_row, text="적용", style="Accent.TButton",
                                     command=self._apply, state="disabled")
        self.apply_btn.pack(side="right", padx=8)

    def _do_search(self):
        for w in self.result_frame.winfo_children():
            w.destroy()

        scraper_cfg = self.cfg.get("scraper", {})
        if not scraper_cfg.get("devid"):
            messagebox.showwarning("설정 필요", "Settings에서 ScreenScraper API 인증 정보를 먼저 입력해주세요.", parent=self)
            return

        rom_path = self.rom_entry.get("_local_rom_path")  # GUI 호출부에서 채워줌
        try:
            if rom_path and Path(rom_path).exists():
                parsed, method = ss.search_by_hash(scraper_cfg, rom_path)
            else:
                parsed, method = None, None
            if not parsed:
                parsed, method = ss.search_by_name(scraper_cfg, self.search_var.get())
        except Exception as e:
            messagebox.showerror("검색 오류", str(e), parent=self)
            return

        if not parsed:
            tk.Label(self.result_frame, text="검색 결과가 없습니다.", bg=BG, fg=ERROR).pack(pady=20)
            return

        self.search_result = parsed
        fields = parsed["fields"]

        tk.Label(self.result_frame, text=f"매칭 방식: {method}", bg=BG, fg=SUCCESS if method == "해시" else WARNING,
                 font=("Segoe UI", 9, "bold")).pack(anchor="w")
        for key, label in [("name", "Title"), ("desc", "Description"), ("genre", "Genre"),
                            ("developer", "Developer"), ("releasedate", "Release")]:
            tk.Label(self.result_frame, text=f"{label}: {fields.get(key, '')}", bg=BG, fg=TEXT,
                     wraplength=450, justify="left").pack(anchor="w", pady=2)

        self.apply_btn.configure(state="normal")

    def _apply(self):
        if not self.search_result:
            return
        fields = self.search_result["fields"]
        media_urls = self.search_result.get("media_urls", {})

        # media 다운로드 -> MasterDB media 디렉토리 저장
        from import_engine import _sanitize_for_path
        paths = dbmod.db_paths(self.masterdb_root)
        stem = _sanitize_for_path(Path(self.rom_entry["rom_filename"]).stem)
        dest_dir = paths["media_dir"] / self.rom_entry["system"] / stem
        dest_dir.mkdir(parents=True, exist_ok=True)

        saved_media = {}
        for mtype, urls in media_urls.items():
            saved_list = []
            for i, url in enumerate(urls[:1]):  # 대표 이미지 1개만 (스켈레톤)
                ext = ".png"
                dest = dest_dir / f"{mtype}{ext}"
                try:
                    ss.download_media(url, dest)
                    saved_list.append(str(dest))
                except Exception:
                    continue
            if saved_list:
                saved_media[mtype] = saved_list[0] if mtype not in ("screenshots", "videos") else saved_list

        dbmod.add_version(
            self.rom_entry, source_local_id="scraper", fields=fields,
            uncertain_match=False, set_as_default=True,
        )
        # [설계] 스크랩 적용은 사용자의 명시적 선택이므로, 기존 media가 있어도 overwrite=True로 교체.
        if saved_media:
            dbmod.set_rom_media(self.rom_entry, saved_media, overwrite=True)
        dbmod.save_db(self.masterdb_root, self.db)

        messagebox.showinfo("완료", "새로운 Version으로 MasterDB에 저장되었습니다.", parent=self)
        if self.on_applied:
            self.on_applied()
        self.destroy()


class BatchScrapeReviewDialog(tk.Toplevel):
    """일괄 스크랩 완료 후 결과 리뷰 화면 (§18)."""

    def __init__(self, parent, db, masterdb_root, results, on_saved=None):
        super().__init__(parent)
        self.db = db
        self.masterdb_root = masterdb_root
        self.results = results
        self.on_saved = on_saved

        success_count = sum(1 for r in results if r["status"] != "실패")
        self.title(f"일괄 스크랩 결과: {len(results)}개 중 {success_count}개 성공")
        self.configure(bg=BG)
        self.geometry("640x480")
        self.transient(parent)
        self.grab_set()

        tk.Label(self, text=f"일괄 스크랩 결과: {len(results)}개 중 {success_count}개 성공",
                 bg=BG, fg=TEXT, font=("Segoe UI", 11, "bold")).pack(anchor="w", padx=16, pady=(16, 8))

        columns = ("check", "file", "method", "status")
        self.tree = ttk.Treeview(self, columns=columns, show="headings", selectmode="none")
        for col, label, w in [("check", "선택", 50), ("file", "File", 260),
                               ("method", "매칭방식", 100), ("status", "상태", 100)]:
            self.tree.heading(col, text=label)
            self.tree.column(col, width=w, anchor="w")
        self.tree.pack(fill="both", expand=True, padx=16, pady=8)

        self._checked = {}
        for idx, r in enumerate(results):
            checked = r["status"] == "완료"  # 해시 매칭 성공 건은 기본 자동 체크
            self._checked[idx] = tk.BooleanVar(value=checked)
            mark = "☑" if checked else "☐"
            self.tree.insert("", "end", iid=str(idx),
                              values=(mark, r["filename"], r.get("match_method", "-"), r["status"]))

        self.tree.bind("<Button-1>", self._toggle_check)

        btn_row = tk.Frame(self, bg=BG); btn_row.pack(fill="x", padx=16, pady=12, side="bottom")
        ttk.Button(btn_row, text="선택 항목 MasterDB에 저장", style="Accent.TButton",
                   command=self._save_selected).pack(side="right", padx=4)
        ttk.Button(btn_row, text="전체 저장", command=self._save_all).pack(side="right", padx=4)

    def _toggle_check(self, event):
        row = self.tree.identify_row(event.y)
        col = self.tree.identify_column(event.x)
        if not row or col != "#1":
            return
        idx = int(row)
        var = self._checked[idx]
        var.set(not var.get())
        mark = "☑" if var.get() else "☐"
        vals = list(self.tree.item(row, "values"))
        vals[0] = mark
        self.tree.item(row, values=vals)

    def _save_all(self):
        for var in self._checked.values():
            var.set(True)
        self._save_selected()

    def _save_selected(self):
        saved = 0
        for idx, r in enumerate(self.results):
            if not self._checked[idx].get() or not r.get("result"):
                continue
            rom_entry = dbmod.get_or_create_rom_entry(self.db, r["system"], r["filename"])
            fields = r["result"]["fields"]
            dbmod.add_version(
                rom_entry, source_local_id="scraper_batch", fields=fields,
                uncertain_match=(r["status"] == "확인필요"), set_as_default=True,
            )
            saved += 1

        dbmod.save_db(self.masterdb_root, self.db)
        messagebox.showinfo("완료", f"{saved}개 항목이 MasterDB에 저장되었습니다.", parent=self)
        if self.on_saved:
            self.on_saved()
        self.destroy()
