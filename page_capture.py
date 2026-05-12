# -*- coding: utf-8 -*-
"""
멀티 페이지 문서 캡처 프로그램 (Windows)

기능
1) GUI 에서 캡처 영역, 다음 페이지 이동 방식(클릭/단축키), 페이지 수, 저장 위치,
   파일명, 추가 출력(JPEG/PNG)을 지정
2) 지정 영역을 캡처하면서 다음 페이지로 자동 이동
3) PDF / JPEG / PNG 저장

요구 사항
    pip install pillow mss pyautogui keyboard
    Windows
"""

import sys
import time
import threading
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, List, Optional, Tuple

import tkinter as tk
from tkinter import ttk, filedialog, messagebox

try:
    from PIL import Image, ImageTk
    import mss
    import pyautogui
except ImportError as e:
    print("필수 패키지가 누락되었습니다:", e)
    print("다음 명령으로 설치해 주세요:")
    print("    pip install pillow mss pyautogui keyboard")
    sys.exit(1)


# ---------------------------------------------------------------------------
# 상수
# ---------------------------------------------------------------------------
DEFAULT_DPI = 200
INVALID_FILENAME_CHARS = r'\/:*?"<>|'

HOTKEY_ALIASES = {
    "page down": "pagedown",
    "page up": "pageup",
    "page-down": "pagedown",
    "page-up": "pageup",
    "→": "right",
    "←": "left",
    "↑": "up",
    "↓": "down",
}


Logger = Callable[[str], None]


@dataclass
class CaptureConfig:
    region: Tuple[int, int, int, int]      # (left, top, width, height)
    nav_mode: str                          # "click" | "hotkey"
    nav_click: Optional[Tuple[int, int]]
    nav_hotkey: Optional[str]
    pages: int
    wait: float
    save_dir: Path
    filename: str
    save_jpeg: bool
    save_png: bool
    dpi: int


# ===========================================================================
# 오버레이 (영역/좌표 선택 공통)
# ===========================================================================
class _Overlay:
    """반투명 전체화면 오버레이 + ESC 취소 + 모달 동작 공통 셋업.

    screenshot 이 주어지면 커서 주변 픽셀을 확대해 보여주는 돋보기를 함께 띄운다.
    하위 클래스는 self.canvas 에 직접 이벤트를 바인딩하고, 결과를 self.result 에 기록한다.
    """

    MAG_SIZE = 160        # 돋보기 윈도우 크기 (px)
    MAG_ZOOM = 8          # 확대 배율
    MAG_OFFSET = 30       # 커서로부터 돋보기 위치 오프셋 (px)

    def __init__(self, master, prompt: str,
                 screenshot: Optional["Image.Image"] = None,
                 screen_offset: Tuple[int, int] = (0, 0)):
        self.master = master
        self.result = None
        self.screenshot = screenshot
        self.screen_offset = screen_offset

        self.top = tk.Toplevel(master)
        self.top.attributes("-fullscreen", True)
        self.top.attributes("-alpha", 0.30)
        self.top.attributes("-topmost", True)
        self.top.configure(bg="black")
        self.top.config(cursor="cross")

        self.canvas = tk.Canvas(
            self.top, bg="black", highlightthickness=0, cursor="cross"
        )
        self.canvas.pack(fill=tk.BOTH, expand=True)
        sw = self.top.winfo_screenwidth()
        self.canvas.create_text(
            sw // 2, 40, text=prompt,
            fill="white", font=("맑은 고딕", 16, "bold"),
        )
        self.top.bind("<Escape>", lambda _: self._cancel())
        self.top.grab_set()
        self.top.focus_force()

        self.mag_top: Optional[tk.Toplevel] = None
        self.mag_canvas: Optional[tk.Canvas] = None
        self.mag_photo = None  # PhotoImage 참조 유지 (GC 방지)
        if self.screenshot is not None:
            self._setup_magnifier()
            self.canvas.bind("<Motion>", self._on_motion)
            self.canvas.bind("<B1-Motion>", self._on_motion, add="+")
            self.canvas.bind("<Leave>", lambda _: self._hide_magnifier())

    # ---- 돋보기 ---------------------------------------------------------
    def _setup_magnifier(self):
        self.mag_top = tk.Toplevel(self.master)
        self.mag_top.overrideredirect(True)
        self.mag_top.attributes("-topmost", True)
        self.mag_canvas = tk.Canvas(
            self.mag_top,
            width=self.MAG_SIZE, height=self.MAG_SIZE,
            highlightthickness=2, highlightbackground="white",
            bg="black",
        )
        self.mag_canvas.pack()
        self.mag_top.withdraw()

    def _on_motion(self, e):
        self._update_magnifier(e.x_root, e.y_root)

    def _update_magnifier(self, x_root: int, y_root: int):
        if self.screenshot is None or self.mag_canvas is None or self.mag_top is None:
            return

        src_size = self.MAG_SIZE // self.MAG_ZOOM
        ox, oy = self.screen_offset
        sx = x_root - ox - src_size // 2
        sy = y_root - oy - src_size // 2

        crop = self.screenshot.crop((sx, sy, sx + src_size, sy + src_size))
        big = crop.resize((self.MAG_SIZE, self.MAG_SIZE), Image.NEAREST)
        self.mag_photo = ImageTk.PhotoImage(big)

        self.mag_canvas.delete("all")
        self.mag_canvas.create_image(0, 0, anchor="nw", image=self.mag_photo)

        c = self.MAG_SIZE // 2
        z = self.MAG_ZOOM
        # 중앙 픽셀(=커서가 가리키는 픽셀)을 강조하는 사각형
        self.mag_canvas.create_rectangle(
            c - z // 2, c - z // 2, c + z // 2, c + z // 2,
            outline="#ff3333", width=1,
        )
        # 십자선
        self.mag_canvas.create_line(0, c, self.MAG_SIZE, c, fill="#ff3333")
        self.mag_canvas.create_line(c, 0, c, self.MAG_SIZE, fill="#ff3333")
        # 좌표 텍스트
        self.mag_canvas.create_text(
            6, 6, text=f"{x_root}, {y_root}",
            anchor="nw", fill="#ffffff",
            font=("Consolas", 9, "bold"),
        )

        sw = self.top.winfo_screenwidth()
        sh = self.top.winfo_screenheight()
        m = self.MAG_SIZE
        off = self.MAG_OFFSET
        px = x_root + off if x_root + off + m < sw else x_root - off - m
        py = y_root + off if y_root + off + m < sh else y_root - off - m
        self.mag_top.geometry(f"{m}x{m}+{px}+{py}")
        self.mag_top.deiconify()
        self.mag_top.lift()

    def _hide_magnifier(self):
        if self.mag_top is not None:
            try:
                self.mag_top.withdraw()
            except Exception:
                pass

    def _cancel(self):
        self.result = None
        self._close()

    def _close(self):
        if self.mag_top is not None:
            try:
                self.mag_top.destroy()
            except Exception:
                pass
            self.mag_top = None
        try:
            self.top.grab_release()
        except Exception:
            pass
        self.top.destroy()

    def select(self):
        # 메인 mainloop 안에서 동작하도록 wait_window 사용
        self.master.wait_window(self.top)
        return self.result


class RegionSelector(_Overlay):
    """마우스 드래그로 사각 영역 선택 → (left, top, w, h)"""

    MIN_SIZE = 5

    def __init__(self, master, screenshot=None, screen_offset=(0, 0)):
        super().__init__(
            master, "마우스로 캡처할 영역을 드래그하세요 (ESC: 취소)",
            screenshot=screenshot, screen_offset=screen_offset,
        )
        self.start_x = self.start_y = 0
        self.end_x = self.end_y = 0
        self.rect_id = None
        self.canvas.bind("<ButtonPress-1>", self._on_press)
        self.canvas.bind("<B1-Motion>", self._on_drag, add="+")
        self.canvas.bind("<ButtonRelease-1>", self._on_release)

    def _on_press(self, e):
        self.start_x, self.start_y = e.x, e.y
        if self.rect_id:
            self.canvas.delete(self.rect_id)
        self.rect_id = self.canvas.create_rectangle(
            self.start_x, self.start_y, self.start_x, self.start_y,
            outline="red", width=2,
        )

    def _on_drag(self, e):
        self.end_x, self.end_y = e.x, e.y
        self.canvas.coords(
            self.rect_id, self.start_x, self.start_y, self.end_x, self.end_y
        )

    def _on_release(self, e):
        self.end_x, self.end_y = e.x, e.y
        x1, y1 = min(self.start_x, self.end_x), min(self.start_y, self.end_y)
        x2, y2 = max(self.start_x, self.end_x), max(self.start_y, self.end_y)
        if x2 - x1 >= self.MIN_SIZE and y2 - y1 >= self.MIN_SIZE:
            self.result = (x1, y1, x2 - x1, y2 - y1)
        self._close()


class PointSelector(_Overlay):
    """클릭으로 (x, y) 좌표 선택"""

    def __init__(self, master, screenshot=None, screen_offset=(0, 0)):
        super().__init__(
            master, "다음 페이지 버튼 위치를 클릭하세요 (ESC: 취소)",
            screenshot=screenshot, screen_offset=screen_offset,
        )
        self.canvas.bind("<ButtonPress-1>", self._on_click)

    def _on_click(self, e):
        self.result = (e.x_root, e.y_root)
        self._close()


# ===========================================================================
# 선택 결과 시각화 오버레이
# ===========================================================================
class SelectionOverlay:
    """선택된 캡처 영역과 클릭 좌표를 화면 위에 시각적으로 표시.

    Windows 의 -transparentcolor 와 WS_EX_TRANSPARENT 플래그를 이용해
    마우스 입력이 통과하는 투명 오버레이로 동작한다.
    """

    TRANS_COLOR = "magenta"
    REGION_COLOR = "#ff3030"
    POINT_COLOR = "#00d050"
    LABEL_FONT = ("맑은 고딕", 10, "bold")

    def __init__(self, master):
        self.master = master
        self.region: Optional[Tuple[int, int, int, int]] = None
        self.point: Optional[Tuple[int, int]] = None

        self.top = tk.Toplevel(master)
        self.top.overrideredirect(True)
        self.top.attributes("-topmost", True)
        self.top.attributes("-transparentcolor", self.TRANS_COLOR)
        self.top.configure(bg=self.TRANS_COLOR)

        sw = self.top.winfo_screenwidth()
        sh = self.top.winfo_screenheight()
        self.top.geometry(f"{sw}x{sh}+0+0")

        self.canvas = tk.Canvas(
            self.top, width=sw, height=sh, bg=self.TRANS_COLOR,
            highlightthickness=0,
        )
        self.canvas.pack(fill=tk.BOTH, expand=True)

        self.top.update_idletasks()
        self._make_click_through()
        self.top.withdraw()

    def _make_click_through(self):
        try:
            import ctypes
            hwnd = ctypes.windll.user32.GetParent(self.top.winfo_id())
            GWL_EXSTYLE = -20
            WS_EX_LAYERED = 0x00080000
            WS_EX_TRANSPARENT = 0x00000020
            styles = ctypes.windll.user32.GetWindowLongW(hwnd, GWL_EXSTYLE)
            ctypes.windll.user32.SetWindowLongW(
                hwnd, GWL_EXSTYLE,
                styles | WS_EX_LAYERED | WS_EX_TRANSPARENT,
            )
        except Exception:
            pass

    def set_region(self, region: Optional[Tuple[int, int, int, int]]):
        self.region = region
        self._redraw()

    def set_point(self, point: Optional[Tuple[int, int]]):
        self.point = point
        self._redraw()

    def show(self):
        if self.region is None and self.point is None:
            return
        self.top.deiconify()
        self.top.attributes("-topmost", True)
        self.top.lift()

    def hide(self):
        self.top.withdraw()

    def _redraw(self):
        self.canvas.delete("all")
        if self.region:
            l, t, w, h = self.region
            self.canvas.create_rectangle(
                l, t, l + w, t + h,
                outline=self.REGION_COLOR, width=3,
            )
            ly = max(0, t - 20)
            self.canvas.create_rectangle(
                l, ly, l + 96, ly + 18,
                fill=self.REGION_COLOR, outline=self.REGION_COLOR,
            )
            self.canvas.create_text(
                l + 4, ly + 1, anchor="nw", text="캡처 영역",
                fill="white", font=self.LABEL_FONT,
            )
        if self.point:
            x, y = self.point
            r = 14
            self.canvas.create_oval(
                x - r, y - r, x + r, y + r,
                outline=self.POINT_COLOR, width=3,
            )
            self.canvas.create_line(
                x - r - 6, y, x + r + 6, y,
                fill=self.POINT_COLOR, width=2,
            )
            self.canvas.create_line(
                x, y - r - 6, x, y + r + 6,
                fill=self.POINT_COLOR, width=2,
            )
            self.canvas.create_text(
                x + r + 8, y, anchor="w", text="클릭 좌표",
                fill=self.POINT_COLOR, font=self.LABEL_FONT,
            )
        self.show()


# ===========================================================================
# 캡처 워커
# ===========================================================================
class CaptureWorker:
    """백그라운드 스레드에서 실행될 캡처/저장 작업"""

    def __init__(self, config: CaptureConfig, log: Logger,
                 done: Callable[[bool, str], None]):
        self.cfg = config
        self.log = log
        self.done = done

    # ---- 진입점 ----------------------------------------------------------
    def run(self):
        try:
            self._run()
        except Exception as e:
            self.log(f"[오류] {e}")
            self.done(False, str(e))

    def _run(self):
        cfg = self.cfg
        # 지정 파일명의 하위 폴더를 만들고 그 안에 PDF / 이미지 폴더를 모두 저장한다.
        target_dir = cfg.save_dir / cfg.filename
        target_dir.mkdir(parents=True, exist_ok=True)
        self.log(f"저장 폴더: {target_dir}")

        self._countdown(3)
        images = self._capture_pages()
        pdf_path = self._save_pdf(images, target_dir)

        if cfg.save_jpeg:
            self._save_image_folder(images, target_dir / "jpeg",
                                    "JPEG", "jpg", quality=92)
        if cfg.save_png:
            self._save_image_folder(images, target_dir / "png",
                                    "PNG", "png")

        self.done(True, f"완료: {pdf_path}")

    # ---- 단계별 ----------------------------------------------------------
    def _countdown(self, seconds: int):
        for i in range(seconds, 0, -1):
            self.log(f"{i}초 후 캡처를 시작합니다... (대상 창을 활성화하세요)")
            time.sleep(1)

    def _capture_pages(self) -> List[Image.Image]:
        cfg = self.cfg
        l, t, w, h = cfg.region
        bbox = {"left": l, "top": t, "width": w, "height": h}
        images: List[Image.Image] = []

        with mss.mss() as sct:
            for i in range(1, cfg.pages + 1):
                self.log(f"페이지 {i}/{cfg.pages} 캡처 중...")
                shot = sct.grab(bbox)
                images.append(Image.frombytes("RGB", shot.size, shot.rgb))
                if i == cfg.pages:
                    break
                self._navigate_next()
                time.sleep(cfg.wait)

        return images

    def _navigate_next(self):
        cfg = self.cfg
        if cfg.nav_mode == "click":
            if not cfg.nav_click:
                raise RuntimeError("클릭 좌표가 지정되지 않았습니다.")
            x, y = cfg.nav_click
            pyautogui.click(x, y)
            self.log(f"  → ({x}, {y}) 클릭")
        elif cfg.nav_mode == "hotkey":
            if not cfg.nav_hotkey:
                raise RuntimeError("단축키가 지정되지 않았습니다.")
            self._press_hotkey(cfg.nav_hotkey)
            self.log(f"  → 단축키 [{cfg.nav_hotkey}] 입력")
        else:
            raise RuntimeError(f"알 수 없는 이동 방식: {cfg.nav_mode}")

    @staticmethod
    def _press_hotkey(hotkey_str: str):
        keys = [k.strip().lower() for k in hotkey_str.split("+")]
        keys = [HOTKEY_ALIASES.get(k, k) for k in keys]
        if len(keys) == 1:
            pyautogui.press(keys[0])
        else:
            pyautogui.hotkey(*keys)

    def _save_pdf(self, images: List[Image.Image], target_dir: Path) -> Path:
        cfg = self.cfg
        pdf_path = target_dir / f"{cfg.filename}.pdf"
        self.log(f"PDF 저장 준비 중 (목표 DPI={cfg.dpi})...")

        # 100 DPI 를 1.0배 기준으로 LANCZOS 업스케일링하여 PDF 실효 해상도를 키운다.
        scale = max(1.0, cfg.dpi / 100.0)
        if scale > 1.001:
            self.log(f"  이미지 업스케일링 ×{scale:.2f} (LANCZOS)")
            pdf_images = [
                img.resize((int(img.width * scale), int(img.height * scale)),
                           Image.LANCZOS)
                for img in images
            ]
        else:
            pdf_images = images

        save_kwargs = {"resolution": float(cfg.dpi)}
        if len(pdf_images) == 1:
            pdf_images[0].save(pdf_path, "PDF", **save_kwargs)
        else:
            pdf_images[0].save(
                pdf_path, "PDF",
                save_all=True, append_images=pdf_images[1:],
                **save_kwargs,
            )
        size_mb = pdf_path.stat().st_size / 1024 / 1024
        self.log(f"PDF 저장 완료 ({size_mb:.1f} MB)")
        return pdf_path

    def _save_image_folder(self, images: List[Image.Image], folder: Path,
                           pil_format: str, ext: str, **save_opts):
        folder.mkdir(exist_ok=True)
        for i, img in enumerate(images, 1):
            img.save(folder / f"{self.cfg.filename}_{i:03d}.{ext}",
                     pil_format, **save_opts)
        self.log(f"{pil_format} 저장 완료: {folder}")


# ===========================================================================
# 메인 GUI
# ===========================================================================
class App:
    def __init__(self, root: tk.Tk):
        self.root = root
        root.title("Multi-Page Document Capturer")
        root.geometry("620x720")
        root.resizable(False, False)

        self.region: Optional[Tuple[int, int, int, int]] = None
        self.click_point: Optional[Tuple[int, int]] = None

        self.overlay = SelectionOverlay(root)

        self._build_ui()

    # ---- UI 빌드 ---------------------------------------------------------
    def _build_ui(self):
        self._build_region_section()
        self._build_navigation_section()
        self._build_pages_section()
        self._build_save_section()
        self._build_options_section()
        self._build_run_button()
        self._build_log_section()
        self._on_nav_change()

    def _build_region_section(self):
        f = ttk.LabelFrame(self.root, text="1. 캡처 영역")
        f.pack(fill="x", padx=10, pady=6)
        self.region_label = ttk.Label(f, text="영역이 선택되지 않았습니다.")
        self.region_label.pack(side="left", padx=8, pady=8)
        ttk.Button(f, text="영역 선택", command=self._select_region).pack(
            side="right", padx=8, pady=8
        )

    def _build_navigation_section(self):
        f = ttk.LabelFrame(self.root, text="2. 다음 페이지 이동 방식")
        f.pack(fill="x", padx=10, pady=6)
        self.nav_mode = tk.StringVar(value="click")

        row1 = ttk.Frame(f); row1.pack(fill="x", padx=8, pady=4)
        ttk.Radiobutton(
            row1, text="좌표 클릭", value="click",
            variable=self.nav_mode, command=self._on_nav_change
        ).pack(side="left")
        self.click_label = ttk.Label(row1, text="(좌표 미지정)")
        self.click_label.pack(side="left", padx=10)
        self.click_btn = ttk.Button(
            row1, text="좌표 선택", command=self._select_click_point
        )
        self.click_btn.pack(side="right")

        row2 = ttk.Frame(f); row2.pack(fill="x", padx=8, pady=4)
        ttk.Radiobutton(
            row2, text="단축키", value="hotkey",
            variable=self.nav_mode, command=self._on_nav_change
        ).pack(side="left")
        self.hotkey_entry = ttk.Entry(row2, width=20)
        self.hotkey_entry.insert(0, "right")
        self.hotkey_entry.pack(side="left", padx=10)
        ttk.Label(row2, text="예: right / pagedown / ctrl+right").pack(side="left")

    def _build_pages_section(self):
        f = ttk.LabelFrame(self.root, text="3. 페이지 / 대기 시간")
        f.pack(fill="x", padx=10, pady=6)
        ttk.Label(f, text="페이지 수:").grid(row=0, column=0, sticky="e", padx=8, pady=4)
        self.page_entry = ttk.Spinbox(f, from_=1, to=999, width=8)
        self.page_entry.set(10)
        self.page_entry.grid(row=0, column=1, sticky="w", padx=4, pady=4)

        ttk.Label(f, text="페이지 간 대기(초):").grid(row=0, column=2, sticky="e", padx=8, pady=4)
        self.wait_entry = ttk.Entry(f, width=8)
        self.wait_entry.insert(0, "1.0")
        self.wait_entry.grid(row=0, column=3, sticky="w", padx=4, pady=4)

    def _build_save_section(self):
        f = ttk.LabelFrame(self.root, text="4. 저장 정보")
        f.pack(fill="x", padx=10, pady=6)

        ttk.Label(f, text="저장 위치:").grid(row=0, column=0, sticky="e", padx=8, pady=4)
        self.save_dir_var = tk.StringVar(value=str(Path.home() / "Documents"))
        ttk.Entry(f, textvariable=self.save_dir_var, width=46).grid(
            row=0, column=1, padx=4, pady=4
        )
        ttk.Button(f, text="…", width=3, command=self._browse_dir).grid(
            row=0, column=2, padx=4
        )

        ttk.Label(f, text="파일명:").grid(row=1, column=0, sticky="e", padx=8, pady=4)
        self.filename_var = tk.StringVar(value="captured")
        ttk.Entry(f, textvariable=self.filename_var, width=46).grid(
            row=1, column=1, padx=4, pady=4
        )

    def _build_options_section(self):
        f = ttk.LabelFrame(self.root, text="5. 추가 출력 옵션")
        f.pack(fill="x", padx=10, pady=6)
        ttk.Label(f, text="* PDF 는 항상 저장됩니다.").pack(anchor="w", padx=8, pady=(4, 0))

        dpi_row = ttk.Frame(f); dpi_row.pack(fill="x", padx=8, pady=4)
        ttk.Label(dpi_row, text="PDF 화질:").pack(side="left")
        self.dpi_var = tk.IntVar(value=DEFAULT_DPI)
        for label, val in [("표준 100 DPI", 100),
                           ("고화질 200 DPI", 200),
                           ("최고화질 300 DPI", 300)]:
            ttk.Radiobutton(
                dpi_row, text=label, value=val, variable=self.dpi_var
            ).pack(side="left", padx=6)

        self.opt_jpeg = tk.BooleanVar(value=False)
        self.opt_png = tk.BooleanVar(value=False)
        opts = ttk.Frame(f); opts.pack(fill="x", padx=8, pady=4)
        ttk.Checkbutton(opts, text="JPEG 폴더 저장", variable=self.opt_jpeg).pack(side="left", padx=6)
        ttk.Checkbutton(opts, text="PNG 폴더 저장", variable=self.opt_png).pack(side="left", padx=6)

    def _build_run_button(self):
        self.run_btn = ttk.Button(self.root, text="▶ 실행", command=self._on_run)
        self.run_btn.pack(fill="x", padx=10, pady=(8, 4))

    def _build_log_section(self):
        f = ttk.LabelFrame(self.root, text="로그")
        f.pack(fill="both", expand=True, padx=10, pady=6)
        self.log_text = tk.Text(f, height=10, wrap="word", state="disabled")
        self.log_text.pack(fill="both", expand=True, padx=4, pady=4)

    # ---- UI 핸들러 -------------------------------------------------------
    def _select_region(self):
        self.overlay.hide()
        self.root.withdraw()
        self.root.update()
        time.sleep(0.25)
        screenshot, offset = self._grab_screen()
        sel = RegionSelector(
            self.root, screenshot=screenshot, screen_offset=offset
        ).select()
        self.root.deiconify()
        self.root.lift()
        if sel is None:
            self.log("영역 선택이 취소되었습니다.")
            self.overlay.show()
            return
        self.region = sel
        l, t, w, h = sel
        self.region_label.config(text=f"({l}, {t})  {w} × {h} px")
        self.overlay.set_region(sel)

    def _select_click_point(self):
        self.overlay.hide()
        self.root.withdraw()
        self.root.update()
        time.sleep(0.25)
        screenshot, offset = self._grab_screen()
        pt = PointSelector(
            self.root, screenshot=screenshot, screen_offset=offset
        ).select()
        self.root.deiconify()
        self.root.lift()
        if pt is None:
            self.log("좌표 선택이 취소되었습니다.")
            self.overlay.show()
            return
        self.click_point = pt
        self.click_label.config(text=f"({pt[0]}, {pt[1]})")
        self.overlay.set_point(pt)

    @staticmethod
    def _grab_screen():
        """주 모니터 스크린샷과 그 좌상단 좌표(offset)를 반환."""
        with mss.mss() as sct:
            mon = sct.monitors[1]  # 0 번은 가상 전체화면, 1 번이 주 모니터
            shot = sct.grab(mon)
            img = Image.frombytes("RGB", shot.size, shot.rgb)
            return img, (mon["left"], mon["top"])

    def _on_nav_change(self):
        if self.nav_mode.get() == "click":
            self.click_btn.state(["!disabled"])
            self.hotkey_entry.state(["disabled"])
        else:
            self.click_btn.state(["disabled"])
            self.hotkey_entry.state(["!disabled"])

    def _browse_dir(self):
        d = filedialog.askdirectory(initialdir=self.save_dir_var.get() or ".")
        if d:
            self.save_dir_var.set(d)

    def log(self, msg: str):
        def _append():
            self.log_text.config(state="normal")
            self.log_text.insert("end", msg + "\n")
            self.log_text.see("end")
            self.log_text.config(state="disabled")
        self.root.after(0, _append)

    # ---- 실행 ------------------------------------------------------------
    def _on_run(self):
        config = self._build_config()
        if config is None:
            return

        self.run_btn.state(["disabled"])
        # 오버레이가 캡처에 찍히지 않도록 캡처 동안 숨긴다.
        self.overlay.hide()
        self.log("=" * 40)
        self.log("캡처를 시작합니다.")

        worker = CaptureWorker(config, self.log, self._on_done)
        threading.Thread(target=worker.run, daemon=True).start()

    def _build_config(self) -> Optional[CaptureConfig]:
        if not self.region:
            messagebox.showwarning("입력 필요", "캡처 영역을 먼저 선택하세요.")
            return None

        nav_mode = self.nav_mode.get()
        nav_click: Optional[Tuple[int, int]] = None
        nav_hotkey: Optional[str] = None
        if nav_mode == "click":
            if not self.click_point:
                messagebox.showwarning("입력 필요", "다음 페이지 클릭 좌표를 선택하세요.")
                return None
            nav_click = self.click_point
        else:
            nav_hotkey = self.hotkey_entry.get().strip()
            if not nav_hotkey:
                messagebox.showwarning("입력 필요", "단축키를 입력하세요.")
                return None

        try:
            pages = int(self.page_entry.get())
            if pages < 1:
                raise ValueError
        except Exception:
            messagebox.showwarning("입력 오류", "페이지 수는 1 이상의 정수여야 합니다.")
            return None

        try:
            wait_sec = float(self.wait_entry.get())
            if wait_sec < 0:
                raise ValueError
        except Exception:
            messagebox.showwarning("입력 오류", "대기 시간은 0 이상의 숫자여야 합니다.")
            return None

        save_dir = self.save_dir_var.get().strip()
        if not save_dir:
            messagebox.showwarning("입력 필요", "저장 위치를 지정하세요.")
            return None

        filename = self.filename_var.get().strip()
        if not filename:
            messagebox.showwarning("입력 필요", "파일명을 입력하세요.")
            return None
        for ch in INVALID_FILENAME_CHARS:
            filename = filename.replace(ch, "_")

        return CaptureConfig(
            region=self.region,
            nav_mode=nav_mode,
            nav_click=nav_click,
            nav_hotkey=nav_hotkey,
            pages=pages,
            wait=wait_sec,
            save_dir=Path(save_dir),
            filename=filename,
            save_jpeg=self.opt_jpeg.get(),
            save_png=self.opt_png.get(),
            dpi=self.dpi_var.get(),
        )

    def _on_done(self, success: bool, message: str):
        def _ui():
            self.run_btn.state(["!disabled"])
            self.overlay.show()
            if success:
                messagebox.showinfo("완료", message)
            else:
                messagebox.showerror("실패", message)
        self.root.after(0, _ui)


# ===========================================================================
def main():
    pyautogui.FAILSAFE = True
    pyautogui.PAUSE = 0.05

    root = tk.Tk()
    App(root)
    root.mainloop()


if __name__ == "__main__":
    main()
