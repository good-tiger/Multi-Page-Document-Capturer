# -*- coding: utf-8 -*-
"""
멀티 페이지 문서 캡처 프로그램 (Windows)

기능
1) 사용자가 GUI 에서 캡처 영역, 다음 페이지 이동 방식(클릭/단축키),
   페이지 수, 저장 위치, 파일명, 추가 이미지 출력(JPEG/PNG)을 선택
2) 실행 시 지정한 영역을 캡처하고 다음 페이지로 이동을 반복
3) 캡처한 페이지들을 합쳐 PDF 로 저장 (기본 출력)
4) 옵션에 따라 JPEG / PNG 폴더에도 이미지 저장
5) 저장된 PDF 를 OpenDataLoader 로 변환하여 마크다운(.md) 으로 저장

필수 패키지
    pip install pillow mss pyautogui keyboard opendataloader-pdf

추가 요구사항
    - Windows
    - Java 가 설치되어 있어야 OpenDataLoader 가 동작합니다.
"""

import os
import sys
import time
import threading
import subprocess
import shutil
import tkinter as tk
from tkinter import ttk, filedialog, messagebox
from pathlib import Path

# ---------------------------------------------------------------------------
# 외부 패키지 import (없으면 친절한 오류 메시지)
# ---------------------------------------------------------------------------
try:
    from PIL import Image
    import mss
    import pyautogui
except ImportError as e:
    print("필수 패키지가 누락되었습니다:", e)
    print("다음 명령으로 설치해 주세요:")
    print("    pip install pillow mss pyautogui keyboard opendataloader-pdf")
    sys.exit(1)


# ===========================================================================
# 영역 선택 오버레이 (전체화면을 반투명으로 덮고 마우스 드래그로 영역 지정)
# ===========================================================================
class RegionSelector:
    """전체 화면 위에 반투명 오버레이를 띄워 마우스 드래그로 사각 영역을 선택.

    메인 Tk() 의 자식 Toplevel 로 만들어야 메인 창이 사라지는 문제를 막을 수 있다.
    """

    def __init__(self, master):
        self.master = master
        self.start_x = self.start_y = 0
        self.end_x = self.end_y = 0
        self.region = None  # (left, top, width, height)

        self.top = tk.Toplevel(master)
        self.top.attributes("-fullscreen", True)
        self.top.attributes("-alpha", 0.30)
        self.top.attributes("-topmost", True)
        self.top.configure(bg="black")
        self.top.config(cursor="cross")

        sw = self.top.winfo_screenwidth()
        self.canvas = tk.Canvas(
            self.top, bg="black", highlightthickness=0, cursor="cross"
        )
        self.canvas.pack(fill=tk.BOTH, expand=True)

        self.canvas.create_text(
            sw // 2,
            40,
            text="마우스로 캡처할 영역을 드래그하세요 (ESC: 취소)",
            fill="white",
            font=("맑은 고딕", 16, "bold"),
        )

        self.rect_id = None
        self.canvas.bind("<ButtonPress-1>", self._on_press)
        self.canvas.bind("<B1-Motion>", self._on_drag)
        self.canvas.bind("<ButtonRelease-1>", self._on_release)
        self.top.bind("<Escape>", lambda _: self._cancel())

        # 모달처럼 동작
        self.top.grab_set()
        self.top.focus_force()

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
        if x2 - x1 < 5 or y2 - y1 < 5:
            self.region = None
        else:
            self.region = (x1, y1, x2 - x1, y2 - y1)
        self._close()

    def _cancel(self):
        self.region = None
        self._close()

    def _close(self):
        try:
            self.top.grab_release()
        except Exception:
            pass
        self.top.destroy()

    def select(self):
        # 자체 mainloop 가 아니라 wait_window 로 대기 (메인 mainloop 안에서 동작)
        self.master.wait_window(self.top)
        return self.region


# ===========================================================================
# 클릭 위치 선택 오버레이 (다음 페이지 버튼 좌표 지정)
# ===========================================================================
class PointSelector:
    """전체 화면 위에 반투명 오버레이를 띄워 한 번 클릭으로 좌표를 지정"""

    def __init__(self, master):
        self.master = master
        self.point = None  # (x, y)

        self.top = tk.Toplevel(master)
        self.top.attributes("-fullscreen", True)
        self.top.attributes("-alpha", 0.30)
        self.top.attributes("-topmost", True)
        self.top.configure(bg="black")
        self.top.config(cursor="cross")

        sw = self.top.winfo_screenwidth()
        self.canvas = tk.Canvas(
            self.top, bg="black", highlightthickness=0, cursor="cross"
        )
        self.canvas.pack(fill=tk.BOTH, expand=True)

        self.canvas.create_text(
            sw // 2,
            40,
            text="다음 페이지 버튼 위치를 클릭하세요 (ESC: 취소)",
            fill="white",
            font=("맑은 고딕", 16, "bold"),
        )

        self.canvas.bind("<ButtonPress-1>", self._on_click)
        self.top.bind("<Escape>", lambda _: self._cancel())

        self.top.grab_set()
        self.top.focus_force()

    def _on_click(self, e):
        self.point = (e.x_root, e.y_root)
        self._close()

    def _cancel(self):
        self.point = None
        self._close()

    def _close(self):
        try:
            self.top.grab_release()
        except Exception:
            pass
        self.top.destroy()

    def select(self):
        self.master.wait_window(self.top)
        return self.point


# ===========================================================================
# 캡처 + 저장 + 변환을 담당하는 워커
# ===========================================================================
class CaptureWorker:
    """백그라운드 스레드에서 실행될 캡처 작업"""

    def __init__(self, config, log_callback, done_callback):
        """
        config: dict — GUI 에서 모은 모든 설정값
        log_callback(msg): GUI 로그 영역에 메시지 추가
        done_callback(success, message): 작업 종료 시 호출
        """
        self.cfg = config
        self.log = log_callback
        self.done = done_callback

    # -----------------------------------------------------------------------
    def run(self):
        try:
            self._do_run()
        except Exception as e:
            self.log(f"[오류] {e}")
            self.done(False, str(e))

    def _do_run(self):
        cfg = self.cfg
        region = cfg["region"]              # (l, t, w, h)
        nav_mode = cfg["nav_mode"]          # "click" or "hotkey"
        nav_click = cfg.get("nav_click")    # (x, y) or None
        nav_hotkey = cfg.get("nav_hotkey")  # str or None
        page_count = cfg["pages"]
        wait_sec = cfg["wait"]
        save_dir = Path(cfg["save_dir"])
        filename = cfg["filename"]
        save_jpeg = cfg["save_jpeg"]
        save_png = cfg["save_png"]
        convert_md = cfg["convert_md"]

        save_dir.mkdir(parents=True, exist_ok=True)

        # 시작 전 카운트다운 — 사용자가 캡처 대상 창을 활성화 할 시간
        for i in range(3, 0, -1):
            self.log(f"{i}초 후 캡처를 시작합니다... (대상 창을 활성화하세요)")
            time.sleep(1)

        # ------- 페이지 캡처 루프 -------
        images = []  # PIL.Image 리스트 (PDF 저장용)
        bbox = {
            "left": region[0],
            "top": region[1],
            "width": region[2],
            "height": region[3],
        }

        with mss.mss() as sct:
            for page_idx in range(1, page_count + 1):
                self.log(f"페이지 {page_idx}/{page_count} 캡처 중...")

                # 캡처 (mss 가 빠르고 정확함)
                shot = sct.grab(bbox)
                img = Image.frombytes("RGB", shot.size, shot.rgb)
                images.append(img)

                # 마지막 페이지면 다음 이동 X
                if page_idx == page_count:
                    break

                # 다음 페이지 이동
                if nav_mode == "click":
                    if not nav_click:
                        raise RuntimeError("클릭 좌표가 지정되지 않았습니다.")
                    x, y = nav_click
                    pyautogui.click(x, y)
                    self.log(f"  → ({x}, {y}) 클릭")
                elif nav_mode == "hotkey":
                    if not nav_hotkey:
                        raise RuntimeError("단축키가 지정되지 않았습니다.")
                    self._press_hotkey(nav_hotkey)
                    self.log(f"  → 단축키 [{nav_hotkey}] 입력")
                else:
                    raise RuntimeError(f"알 수 없는 이동 방식: {nav_mode}")

                # 페이지 로딩 대기
                time.sleep(wait_sec)

        # ------- PDF 저장 (기본 출력) -------
        pdf_path = save_dir / f"{filename}.pdf"
        dpi = cfg.get("dpi", 200)
        self.log(f"PDF 저장 준비 중 (목표 DPI={dpi})...")

        # 업스케일링: 캡처 원본 해상도 대비 부족할 때, 이미지 자체를
        # LANCZOS 보간으로 키워 PDF 의 실효 해상도를 높인다.
        # 기준: 100 DPI 를 1.0배로 가정하고 dpi/100 만큼 키운다.
        scale = max(1.0, dpi / 100.0)
        if scale > 1.001:
            self.log(f"  이미지 업스케일링 ×{scale:.2f} (LANCZOS)")
            scaled = []
            for img in images:
                w, h = img.size
                nw, nh = int(w * scale), int(h * scale)
                scaled.append(img.resize((nw, nh), Image.LANCZOS))
            pdf_images = scaled
        else:
            pdf_images = images

        # PIL PDF 저장 옵션:
        # - resolution: PDF 메타데이터의 DPI (OCR 도구가 픽셀→포인트 환산에 사용)
        save_kwargs = {"resolution": float(dpi)}

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

        # ------- JPEG 저장 (옵션) -------
        if save_jpeg:
            jpeg_dir = save_dir / "jpeg"
            jpeg_dir.mkdir(exist_ok=True)
            for i, img in enumerate(images, 1):
                p = jpeg_dir / f"{filename}_{i:03d}.jpg"
                img.save(p, "JPEG", quality=92)
            self.log(f"JPEG 저장 완료: {jpeg_dir}")

        # ------- PNG 저장 (옵션) -------
        if save_png:
            png_dir = save_dir / "png"
            png_dir.mkdir(exist_ok=True)
            for i, img in enumerate(images, 1):
                p = png_dir / f"{filename}_{i:03d}.png"
                img.save(p, "PNG")
            self.log(f"PNG 저장 완료: {png_dir}")

        # ------- 마크다운 변환 -------
        if convert_md:
            self.log("OpenDataLoader 로 마크다운 변환을 시작합니다...")
            self._convert_to_markdown(pdf_path, save_dir, filename)

        self.done(True, f"완료: {pdf_path}")

    # -----------------------------------------------------------------------
    def _press_hotkey(self, hotkey_str):
        """
        '+' 로 묶인 단축키 문자열을 pyautogui 로 입력
        예) "right", "page down", "ctrl+right"
        """
        keys = [k.strip().lower() for k in hotkey_str.split("+")]
        # pyautogui 가 인식하는 키 매핑
        alias = {
            "page down": "pagedown",
            "page up": "pageup",
            "page-down": "pagedown",
            "page-up": "pageup",
            "→": "right",
            "←": "left",
            "↑": "up",
            "↓": "down",
        }
        keys = [alias.get(k, k) for k in keys]
        if len(keys) == 1:
            pyautogui.press(keys[0])
        else:
            pyautogui.hotkey(*keys)

    # -----------------------------------------------------------------------
    def _convert_to_markdown(self, pdf_path: Path, save_dir: Path, filename: str):
        """
        OpenDataLoader hybrid 모드로 PDF -> Markdown 변환

        스캔/이미지 PDF 에서 OCR 을 동작시키려면 별도의 hybrid 백엔드 서버가
        필요하다. 이 함수는 다음을 자동으로 수행한다:
            1) opendataloader-pdf[hybrid] 패키지가 없으면 설치
            2) opendataloader-pdf-hybrid 백엔드를 서브프로세스로 실행 (--force-ocr)
            3) Python API 로 변환 호출 (hybrid='docling-fast')
            4) 변환이 끝나면 백엔드 서브프로세스 종료
            5) 결과 .md 파일을 원하는 위치/이름으로 이동
        """
        # ---- 1) 패키지 import 보장 ----
        try:
            import opendataloader_pdf  # noqa: F401
        except ImportError:
            self.log("opendataloader-pdf[hybrid] 자동 설치를 시도합니다...")
            r = subprocess.run(
                [sys.executable, "-m", "pip", "install",
                 "opendataloader-pdf[hybrid]"],
                capture_output=True, text=True,
            )
            if r.returncode != 0:
                self.log("[경고] opendataloader-pdf 설치 실패. 변환을 건너뜁니다.")
                self.log((r.stderr or "")[-500:])
                return

        # hybrid 추가 의존성(docling 등) 까지 설치되었는지 확인
        try:
            import importlib
            importlib.import_module("docling")
        except Exception:
            self.log("hybrid 의존성(docling)을 설치합니다... (수 분 소요)")
            r = subprocess.run(
                [sys.executable, "-m", "pip", "install",
                 "opendataloader-pdf[hybrid]", "--upgrade"],
                capture_output=True, text=True,
            )
            if r.returncode != 0:
                self.log("[경고] hybrid 의존성 설치 실패. 일반 모드로 변환합니다.")
                self.log((r.stderr or "")[-500:])
                return self._convert_local_only(pdf_path, save_dir, filename)

        # ---- 2) hybrid 백엔드 서버 기동 ----
        # opendataloader-pdf-hybrid 콘솔 스크립트가 PATH 에 설치된다.
        backend_proc = None
        backend_cmd = None
        for candidate in ["opendataloader-pdf-hybrid",
                          "opendataloader-pdf-hybrid.exe"]:
            if shutil.which(candidate):
                backend_cmd = candidate
                break

        if backend_cmd is None:
            self.log(
                "[경고] opendataloader-pdf-hybrid 실행 파일을 찾지 못했습니다."
                " 일반 모드로 변환합니다."
            )
            return self._convert_local_only(pdf_path, save_dir, filename)

        ocr_lang = self.cfg.get("ocr_lang", "ko,en")
        port = 5002
        self.log(f"hybrid 백엔드 서버 시작 (포트 {port}, 언어 '{ocr_lang}')...")

        try:
            backend_proc = subprocess.Popen(
                [backend_cmd,
                 "--port", str(port),
                 "--force-ocr",
                 "--ocr-lang", ocr_lang],
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                # Windows 에서 창이 뜨지 않도록
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            )
        except Exception as e:
            self.log(f"[경고] 백엔드 시작 실패: {e}. 일반 모드로 변환합니다.")
            return self._convert_local_only(pdf_path, save_dir, filename)

        # 서버가 준비될 때까지 대기 (최대 60초)
        if not self._wait_backend_ready(port, timeout=60):
            self.log("[경고] 백엔드 서버 응답 없음. 일반 모드로 변환합니다.")
            self._kill_proc(backend_proc)
            return self._convert_local_only(pdf_path, save_dir, filename)

        self.log("백엔드 서버 준비 완료. OCR 변환을 진행합니다...")

        # ---- 3) 변환 ----
        tmp_out = save_dir / "_odl_tmp"
        if tmp_out.exists():
            shutil.rmtree(tmp_out)
        tmp_out.mkdir()

        try:
            import opendataloader_pdf
            opendataloader_pdf.convert(
                input_path=[str(pdf_path)],
                output_dir=str(tmp_out),
                format="markdown",
                hybrid="docling-fast",
            )
        except Exception as e:
            self.log(f"[경고] hybrid 변환 실패: {e}. 일반 모드로 재시도합니다.")
            self._kill_proc(backend_proc)
            shutil.rmtree(tmp_out, ignore_errors=True)
            return self._convert_local_only(pdf_path, save_dir, filename)
        finally:
            self._kill_proc(backend_proc)

        # ---- 4) 결과 파일 이동 ----
        self._move_md_result(tmp_out, save_dir, filename)

    # -----------------------------------------------------------------------
    def _convert_local_only(self, pdf_path: Path, save_dir: Path, filename: str):
        """hybrid 가 불가능할 때, 로컬(텍스트만) 모드로 변환 — 이미지 PDF 면 결과 빈약"""
        try:
            import opendataloader_pdf
        except ImportError:
            self.log("[경고] opendataloader-pdf 가 없습니다. 변환을 건너뜁니다.")
            return

        tmp_out = save_dir / "_odl_tmp"
        if tmp_out.exists():
            shutil.rmtree(tmp_out)
        tmp_out.mkdir()

        try:
            opendataloader_pdf.convert(
                input_path=[str(pdf_path)],
                output_dir=str(tmp_out),
                format="markdown",
            )
        except Exception as e:
            self.log(f"[경고] 마크다운 변환 실패: {e}")
            shutil.rmtree(tmp_out, ignore_errors=True)
            return

        self._move_md_result(tmp_out, save_dir, filename)

    # -----------------------------------------------------------------------
    def _move_md_result(self, tmp_out: Path, save_dir: Path, filename: str):
        md_files = list(tmp_out.rglob("*.md"))
        if not md_files:
            self.log("[경고] 변환 결과에 .md 파일이 없습니다.")
            shutil.rmtree(tmp_out, ignore_errors=True)
            return
        target_md = save_dir / f"{filename}.md"
        shutil.copy2(md_files[0], target_md)
        shutil.rmtree(tmp_out, ignore_errors=True)
        self.log(f"마크다운 저장 완료: {target_md}")

    # -----------------------------------------------------------------------
    def _wait_backend_ready(self, port: int, timeout: int = 60) -> bool:
        """hybrid 백엔드 서버가 응답할 때까지 폴링."""
        import socket
        deadline = time.time() + timeout
        last_log = 0
        while time.time() < deadline:
            try:
                with socket.create_connection(("127.0.0.1", port), timeout=1):
                    return True
            except OSError:
                pass
            now = time.time()
            if now - last_log > 5:
                remain = int(deadline - now)
                self.log(f"  ...백엔드 준비 대기 중 (잔여 {remain}초)")
                last_log = now
            time.sleep(1)
        return False

    # -----------------------------------------------------------------------
    def _kill_proc(self, proc):
        if proc is None:
            return
        try:
            proc.terminate()
            try:
                proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                proc.kill()
        except Exception:
            pass


# ===========================================================================
# 메인 GUI
# ===========================================================================
class App:
    def __init__(self, root):
        self.root = root
        root.title("Multi-Page Document Capturer")
        root.geometry("620x780")
        root.resizable(False, False)

        self.region = None              # (l, t, w, h)
        self.click_point = None         # (x, y)

        self._build_ui()

    # -----------------------------------------------------------------------
    def _build_ui(self):
        pad = {"padx": 10, "pady": 6}

        # ---- 1. 캡처 영역 ----
        f1 = ttk.LabelFrame(self.root, text="1. 캡처 영역")
        f1.pack(fill="x", **pad)
        self.region_label = ttk.Label(f1, text="영역이 선택되지 않았습니다.")
        self.region_label.pack(side="left", padx=8, pady=8)
        ttk.Button(f1, text="영역 선택", command=self._select_region).pack(
            side="right", padx=8, pady=8
        )

        # ---- 2. 다음 페이지 이동 방식 ----
        f2 = ttk.LabelFrame(self.root, text="2. 다음 페이지 이동 방식")
        f2.pack(fill="x", **pad)

        self.nav_mode = tk.StringVar(value="click")

        row1 = ttk.Frame(f2); row1.pack(fill="x", padx=8, pady=4)
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

        row2 = ttk.Frame(f2); row2.pack(fill="x", padx=8, pady=4)
        ttk.Radiobutton(
            row2, text="단축키", value="hotkey",
            variable=self.nav_mode, command=self._on_nav_change
        ).pack(side="left")
        self.hotkey_entry = ttk.Entry(row2, width=20)
        self.hotkey_entry.insert(0, "right")
        self.hotkey_entry.pack(side="left", padx=10)
        ttk.Label(
            row2, text="예: right / pagedown / ctrl+right"
        ).pack(side="left")

        # ---- 3. 페이지 수 + 대기 시간 ----
        f3 = ttk.LabelFrame(self.root, text="3. 페이지 / 대기 시간")
        f3.pack(fill="x", **pad)
        ttk.Label(f3, text="페이지 수:").grid(row=0, column=0, sticky="e", padx=8, pady=4)
        self.page_entry = ttk.Spinbox(f3, from_=1, to=999, width=8)
        self.page_entry.set(10)
        self.page_entry.grid(row=0, column=1, sticky="w", padx=4, pady=4)

        ttk.Label(f3, text="페이지 간 대기(초):").grid(row=0, column=2, sticky="e", padx=8, pady=4)
        self.wait_entry = ttk.Entry(f3, width=8)
        self.wait_entry.insert(0, "1.0")
        self.wait_entry.grid(row=0, column=3, sticky="w", padx=4, pady=4)

        # ---- 4. 저장 위치 + 파일명 ----
        f4 = ttk.LabelFrame(self.root, text="4. 저장 정보")
        f4.pack(fill="x", **pad)

        ttk.Label(f4, text="저장 위치:").grid(row=0, column=0, sticky="e", padx=8, pady=4)
        self.save_dir_var = tk.StringVar(value=str(Path.home() / "Documents"))
        ttk.Entry(f4, textvariable=self.save_dir_var, width=46).grid(
            row=0, column=1, padx=4, pady=4
        )
        ttk.Button(f4, text="…", width=3, command=self._browse_dir).grid(
            row=0, column=2, padx=4
        )

        ttk.Label(f4, text="파일명:").grid(row=1, column=0, sticky="e", padx=8, pady=4)
        self.filename_var = tk.StringVar(value="captured")
        ttk.Entry(f4, textvariable=self.filename_var, width=46).grid(
            row=1, column=1, padx=4, pady=4
        )

        # ---- 5. 출력 옵션 ----
        f5 = ttk.LabelFrame(self.root, text="5. 추가 출력 옵션")
        f5.pack(fill="x", **pad)
        ttk.Label(
            f5, text="* PDF 는 항상 저장됩니다."
        ).pack(anchor="w", padx=8, pady=(4, 0))

        # PDF 화질 (DPI)
        dpi_row = ttk.Frame(f5); dpi_row.pack(fill="x", padx=8, pady=4)
        ttk.Label(dpi_row, text="PDF 화질:").pack(side="left")
        self.dpi_var = tk.IntVar(value=200)
        for label, val in [("표준 100 DPI", 100),
                           ("고화질 200 DPI", 200),
                           ("최고화질 300 DPI", 300)]:
            ttk.Radiobutton(
                dpi_row, text=label, value=val, variable=self.dpi_var
            ).pack(side="left", padx=6)

        self.opt_jpeg = tk.BooleanVar(value=False)
        self.opt_png = tk.BooleanVar(value=False)
        self.opt_md = tk.BooleanVar(value=True)
        opts = ttk.Frame(f5); opts.pack(fill="x", padx=8, pady=4)
        ttk.Checkbutton(opts, text="JPEG 폴더 저장", variable=self.opt_jpeg).pack(side="left", padx=6)
        ttk.Checkbutton(opts, text="PNG 폴더 저장", variable=self.opt_png).pack(side="left", padx=6)
        ttk.Checkbutton(opts, text="마크다운(.md) 변환 (OCR)", variable=self.opt_md).pack(side="left", padx=6)

        # OCR 언어
        lang_row = ttk.Frame(f5); lang_row.pack(fill="x", padx=8, pady=4)
        ttk.Label(lang_row, text="OCR 언어:").pack(side="left")
        self.ocr_lang_var = tk.StringVar(value="ko,en")
        ttk.Entry(lang_row, textvariable=self.ocr_lang_var, width=20).pack(side="left", padx=6)
        ttk.Label(
            lang_row,
            text="예: ko,en / ja / ch_sim / en"
        ).pack(side="left", padx=4)

        # ---- 실행 버튼 ----
        self.run_btn = ttk.Button(
            self.root, text="▶ 실행", command=self._on_run
        )
        self.run_btn.pack(fill="x", padx=10, pady=(8, 4))

        # ---- 로그 ----
        f6 = ttk.LabelFrame(self.root, text="로그")
        f6.pack(fill="both", expand=True, **pad)
        self.log_text = tk.Text(f6, height=10, wrap="word", state="disabled")
        self.log_text.pack(fill="both", expand=True, padx=4, pady=4)

        self._on_nav_change()

    # -----------------------------------------------------------------------
    # UI 핸들러
    # -----------------------------------------------------------------------
    def _select_region(self):
        # 메인 창을 잠깐 숨겨 캡처 대상이 보이게 한 뒤 오버레이를 띄운다.
        self.root.withdraw()
        self.root.update()
        time.sleep(0.25)
        sel = RegionSelector(self.root).select()
        self.root.deiconify()
        self.root.lift()
        if sel is None:
            self.log("영역 선택이 취소되었습니다.")
            return
        self.region = sel
        l, t, w, h = sel
        self.region_label.config(text=f"({l}, {t})  {w} × {h} px")

    def _select_click_point(self):
        self.root.withdraw()
        self.root.update()
        time.sleep(0.25)
        pt = PointSelector(self.root).select()
        self.root.deiconify()
        self.root.lift()
        if pt is None:
            self.log("좌표 선택이 취소되었습니다.")
            return
        self.click_point = pt
        self.click_label.config(text=f"({pt[0]}, {pt[1]})")

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

    def log(self, msg):
        def _append():
            self.log_text.config(state="normal")
            self.log_text.insert("end", msg + "\n")
            self.log_text.see("end")
            self.log_text.config(state="disabled")
        self.root.after(0, _append)

    # -----------------------------------------------------------------------
    def _on_run(self):
        # 입력값 검증
        if not self.region:
            messagebox.showwarning("입력 필요", "캡처 영역을 먼저 선택하세요.")
            return

        nav_mode = self.nav_mode.get()
        nav_click = None
        nav_hotkey = None
        if nav_mode == "click":
            if not self.click_point:
                messagebox.showwarning("입력 필요", "다음 페이지 클릭 좌표를 선택하세요.")
                return
            nav_click = self.click_point
        else:
            nav_hotkey = self.hotkey_entry.get().strip()
            if not nav_hotkey:
                messagebox.showwarning("입력 필요", "단축키를 입력하세요.")
                return

        try:
            pages = int(self.page_entry.get())
            assert pages >= 1
        except Exception:
            messagebox.showwarning("입력 오류", "페이지 수는 1 이상의 정수여야 합니다.")
            return

        try:
            wait_sec = float(self.wait_entry.get())
            assert wait_sec >= 0
        except Exception:
            messagebox.showwarning("입력 오류", "대기 시간은 0 이상의 숫자여야 합니다.")
            return

        save_dir = self.save_dir_var.get().strip()
        if not save_dir:
            messagebox.showwarning("입력 필요", "저장 위치를 지정하세요.")
            return

        filename = self.filename_var.get().strip()
        if not filename:
            messagebox.showwarning("입력 필요", "파일명을 입력하세요.")
            return
        # 파일명에서 위험 문자 제거
        for ch in r'\/:*?"<>|':
            filename = filename.replace(ch, "_")

        config = {
            "region": self.region,
            "nav_mode": nav_mode,
            "nav_click": nav_click,
            "nav_hotkey": nav_hotkey,
            "pages": pages,
            "wait": wait_sec,
            "save_dir": save_dir,
            "filename": filename,
            "save_jpeg": self.opt_jpeg.get(),
            "save_png": self.opt_png.get(),
            "convert_md": self.opt_md.get(),
            "dpi": self.dpi_var.get(),
            "ocr_lang": self.ocr_lang_var.get().strip() or "ko,en",
        }

        self.run_btn.state(["disabled"])
        self.log("=" * 40)
        self.log("캡처를 시작합니다.")

        worker = CaptureWorker(config, self.log, self._on_done)
        threading.Thread(target=worker.run, daemon=True).start()

    # -----------------------------------------------------------------------
    def _on_done(self, success, message):
        def _ui():
            self.run_btn.state(["!disabled"])
            if success:
                messagebox.showinfo("완료", message)
            else:
                messagebox.showerror("실패", message)
        self.root.after(0, _ui)


# ===========================================================================
def main():
    # pyautogui 안전장치 (모서리로 마우스를 보내면 중단)
    pyautogui.FAILSAFE = True
    pyautogui.PAUSE = 0.05

    root = tk.Tk()
    App(root)
    root.mainloop()


if __name__ == "__main__":
    main()