#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
파일명: convert_webp_gui_with_progress.py

설명:
    - 기존에 제공된 WebP 변환 GUI 코드를 확장하여, 
      “폴더 선택” / “파일 선택” 모드, GIF/JPEG 변환, 원본 삭제 옵션을 지원합니다.
    - 여기에 **진행 상황(Progress Bar + 처리 카운터)** 를 추가하여,
      변환 중 “현재 몇 개를 처리했는지 / 총 몇 개를 처리할 예정인지”를 실시간으로 보여줍니다.
    - 멀티프로세싱을 사용하되, 각 태스크를 apply_async+Callback 방식으로 실행하여 
      완료될 때마다 GUI 스레드에서 진행 상태를 업데이트합니다.
"""

import os
import tkinter as tk
from tkinter import filedialog, messagebox, ttk
from PIL import Image, ImageSequence
from multiprocessing import Pool, cpu_count, Manager


def convert_single_webp(args):
    """
    WebP 파일을 GIF 또는 JPEG로 변환하고, 필요 시 원본을 삭제하는 함수.
    args: (webp_path: str, output_format: str, delete_original: bool)
    반환: (True, webp_path, None) 또는 (False, webp_path, 오류메시지)
    """
    webp_path, output_format, delete_original = args
    try:
        dirname, filename = os.path.split(webp_path)
        base_name, _ = os.path.splitext(filename)

        if output_format == "JPEG":
            out_filename = base_name + ".jpg"
            out_path = os.path.join(dirname, out_filename)
            with Image.open(webp_path) as img:
                # 확실히 RGB 모드로 변환
                img_rgb = img.convert("RGB")
                img_rgb.save(
                    out_path,
                    format="JPEG",
                    quality=100,
                    subsampling=0,
                    optimize=True
                )

        else:  # output_format == "GIF"
            out_filename = base_name + ".gif"
            out_path = os.path.join(dirname, out_filename)
            with Image.open(webp_path) as img:
                frames_rgb = []
                durations = []

                # 첫 프레임을 RGB로 변환
                first_rgb = img.convert("RGB")
                # 첫 프레임에서 256색 팔레트 생성 (MEDIANCUT)
                paletted_first = first_rgb.quantize(
                    palette=None,
                    colors=256,
                    method=Image.MEDIANCUT
                )

                # 모든 프레임에 같은 팔레트 적용
                for frame in ImageSequence.Iterator(img):
                    f_rgb = frame.convert("RGB")
                    f_p = f_rgb.quantize(palette=paletted_first)
                    frames_rgb.append(f_p)
                    durations.append(frame.info.get("duration", 100))

                if len(frames_rgb) <= 1:
                    paletted_first.save(out_path, format="GIF")
                else:
                    frames_rgb[0].save(
                        out_path,
                        save_all=True,
                        append_images=frames_rgb[1:],
                        loop=0,
                        duration=durations,
                        disposal=2,
                        optimize=False
                    )

        # 변환 성공 시, delete_original=True면 WebP 삭제
        if delete_original:
            os.remove(webp_path)

        return True, webp_path, None

    except Exception as e:
        return False, webp_path, str(e)


class WebPConverterApp(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("WebP 변환기 (진행 바 추가)")
        self.geometry("700x750")
        self.resizable(True, True)

        # WebP 파일 경로 리스트
        self.webp_paths = []

        # GUI 상태를 저장하는 변수
        self.mode = tk.StringVar(value="폴더")        # "폴더" 또는 "파일"
        self.output_format = tk.StringVar(value="GIF")# "GIF" 또는 "JPEG"
        self.delete_original = tk.BooleanVar(value=False)
        # 진행 상태를 위한 변수: 총 파일 개수, 완료된 개수
        self.total_files = 0
        self.completed_files = 0

        self._create_widgets()

    def _create_widgets(self):
        # ─── (1) 모드 선택 ───────────────────────────────────────
        frame_mode = tk.LabelFrame(self,
                                   text="선택 모드",
                                   padx=10, pady=10,
                                   font=("맑은 고딕", 12))
        frame_mode.pack(fill="x", padx=20, pady=(20, 10))

        rb_folder = tk.Radiobutton(
            frame_mode,
            text="폴더 선택 (폴더 내 모든 .webp 스캔)",
            variable=self.mode,
            value="폴더",
            font=("맑은 고딕", 11),
            command=self._on_mode_change
        )
        rb_folder.pack(side="left", padx=(10, 20))

        rb_files = tk.Radiobutton(
            frame_mode,
            text="파일 선택 (여러 개 .webp 직접 선택)",
            variable=self.mode,
            value="파일",
            font=("맑은 고딕", 11),
            command=self._on_mode_change
        )
        rb_files.pack(side="left", padx=10)

        # ─── (2) 폴더/파일 선택 버튼 ─────────────────────────────
        self.btn_select = tk.Button(
            self,
            text="폴더 선택",
            font=("맑은 고딕", 12),
            width=25,
            command=self.select_items
        )
        self.btn_select.pack(pady=(0, 10))

        # ─── (3) 선택된 경로 표시 ───────────────────────────────
        self.lbl_selected = tk.Label(
            self,
            text="선택된 경로: 없음",
            font=("맑은 고딕", 11),
            fg="blue",
            anchor="w",
            justify="left"
        )
        self.lbl_selected.pack(fill="x", padx=20)

        # ─── (4) 리스트박스 + 스크롤바 (WebP 경로 목록) ───────────
        frame_list = tk.Frame(self)
        frame_list.pack(fill="both", expand=True, padx=20, pady=(10, 5))

        scrollbar = tk.Scrollbar(frame_list)
        scrollbar.pack(side="right", fill="y")

        self.listbox = tk.Listbox(
            frame_list,
            font=("맑은 고딕", 11),
            selectmode=tk.SINGLE,
            yscrollcommand=scrollbar.set
        )
        self.listbox.pack(side="left", fill="both", expand=True)
        scrollbar.config(command=self.listbox.yview)

        # ─── (5) 변환 옵션 (출력 형식 + 원본 삭제) ─────────────────
        frame_opts = tk.LabelFrame(self,
                                  text="변환 옵션",
                                  padx=10, pady=10,
                                  font=("맑은 고딕", 12))
        frame_opts.pack(fill="x", padx=20, pady=(5, 5))

        lbl_format = tk.Label(frame_opts,
                              text="출력 형식:",
                              font=("맑은 고딕", 11))
        lbl_format.pack(side="left", padx=(10, 5))

        opt_format = tk.OptionMenu(frame_opts,
                                   self.output_format,
                                   "GIF", "JPEG")
        opt_format.config(font=("맑은 고딕", 11), width=8)
        opt_format.pack(side="left", padx=(0, 20))

        chk_delete = tk.Checkbutton(
            frame_opts,
            text="원본 WebP 삭제",
            variable=self.delete_original,
            font=("맑은 고딕", 11)
        )
        chk_delete.pack(side="left", padx=10)

        # ─── (6) 진행 상태 표시 (Label + Progressbar) ─────────────
        frame_progress = tk.Frame(self)
        frame_progress.pack(fill="x", padx=20, pady=(10, 5))

        self.lbl_progress = tk.Label(
            frame_progress,
            text="진행 상황: 0 / 0",
            font=("맑은 고딕", 11),
            anchor="w"
        )
        self.lbl_progress.pack(fill="x")

        self.progress_var = tk.DoubleVar(value=0)
        self.pb = ttk.Progressbar(
            frame_progress,
            variable=self.progress_var,
            maximum=1,  # 나중에 실제 파일 수로 변경
            mode="determinate"
        )
        self.pb.pack(fill="x", pady=(5, 0))

        # ─── (7) 변환 시작 버튼 (항상 하단 고정) ─────────────────
        btn_convert = tk.Button(
            self,
            text="변환 시작",
            font=("맑은 고딕", 14),
            width=25,
            height=2,
            command=self.convert_all
        )
        btn_convert.pack(side="bottom", pady=(10, 20))

    def _on_mode_change(self):
        """
        모드 변경 시:
        - 버튼 텍스트를 "폴더 선택" 혹은 "파일 선택"으로 변경
        - 이전에 선택된 목록 초기화
        """
        mode = self.mode.get()
        if mode == "폴더":
            self.btn_select.config(text="폴더 선택")
        else:
            self.btn_select.config(text="파일 선택")

        # 리스트박스, 선택 정보 초기화
        self.webp_paths = []
        self.listbox.delete(0, tk.END)
        self.lbl_selected.config(text="선택된 경로: 없음")
        # 진행 상태 초기화
        self.total_files = 0
        self.completed_files = 0
        self.lbl_progress.config(text="진행 상황: 0 / 0")
        self.progress_var.set(0)
        self.pb.config(maximum=1)

    def select_items(self):
        """
        모드에 따라:
        - '폴더' 모드: askdirectory() 호출 → 폴더 내 모든 .webp 파일 경로 리스트 생성
        - '파일' 모드: askopenfilenames() 호출 → 사용자가 선택한 .webp 경로 리스트 생성
        생성된 경로 목록을 리스트박스와 라벨에 표시
        """
        mode = self.mode.get()
        if mode == "폴더":
            folder_path = filedialog.askdirectory(title="WebP 파일이 들어있는 폴더 선택")
            if not folder_path:
                return
            self.lbl_selected.config(text=f"선택된 폴더: {folder_path}")

            all_files = os.listdir(folder_path)
            webp_list = [
                os.path.join(folder_path, f)
                for f in all_files
                if os.path.splitext(f)[1].lower() == ".webp"
            ]
            self.webp_paths = webp_list

            self.listbox.delete(0, tk.END)
            if not webp_list:
                self.listbox.insert(tk.END, "(폴더에 .webp 파일이 없습니다)")
            else:
                for p in webp_list:
                    self.listbox.insert(tk.END, p)

        else:  # mode == "파일"
            file_paths = filedialog.askopenfilenames(
                title="WebP 파일 여러 개 선택",
                filetypes=[("WebP 이미지", "*.webp")]
            )
            if not file_paths:
                return
            self.lbl_selected.config(text=f"선택된 파일 개수: {len(file_paths)}개")
            self.webp_paths = list(file_paths)

            self.listbox.delete(0, tk.END)
            for p in file_paths:
                self.listbox.insert(tk.END, p)

        # “선택이 끝난 시점”에 총 파일 수를 계산해서 진행 바의 최대값을 설정
        self.total_files = len(self.webp_paths)
        self.completed_files = 0
        self.lbl_progress.config(text=f"진행 상황: 0 / {self.total_files}")
        self.progress_var.set(0)
        if self.total_files > 0:
            self.pb.config(maximum=self.total_files)
        else:
            self.pb.config(maximum=1)

    def _on_task_done(self, result):
        """
        개별 작업이 완료될 때마다 호출되는 콜백.
        result: (success: bool, webp_path: str, error_message: str or None)
        → 완료된 파일 수를 1 증가시키고, ProgressBar + Label을 갱신.
        """
        success, webp_path, err = result
        self.completed_files += 1
        # 진행 표시 업데이트
        self.lbl_progress.config(text=f"진행 상황: {self.completed_files} / {self.total_files}")
        self.progress_var.set(self.completed_files)

        # 모든 작업이 끝난 시, Pool 종료 후 알림을 띄울 수 있도록 확인
        if self.completed_files == self.total_files:
            messagebox.showinfo("완료", f"총 {self.total_files}개의 파일을 성공적으로 변환했습니다.")
            # 작업 완료 후 상태 초기화 (원한다면 여기서 리스트박스를 비워도 됩니다)
            # self.webp_paths = []
            # self.listbox.delete(0, tk.END)
            # self.lbl_selected.config(text="선택된 경로: 없음")

        # 만약 실패한 파일이 있었다면, 실패 메시지를 추가로 보여줄 수도 있습니다.
        # (예: if not success: ...)

    def convert_all(self):
        """
        선택된 WebP 파일들을:
        - 멀티프로세싱(Pool.apply_async + 콜백) 방식으로 병렬 변환 수행
        - 변환 옵션: output_format, delete_original
        - 진행 상황을 실시간으로 ProgressBar와 Label에 표시
        """
        if not self.webp_paths:
            messagebox.showwarning("경고", "먼저 변환할 WebP 파일(또는 폴더)을 선택하세요.")
            return

        if self.mode.get() == "폴더" and all(not p.lower().endswith(".webp") for p in self.webp_paths):
            messagebox.showwarning("경고", "선택된 폴더에 .webp 파일이 없습니다.")
            return

        output_format = self.output_format.get()    # "GIF" 또는 "JPEG"
        delete_original = self.delete_original.get()

        # Pool 생성 (CPU 코어 수만큼 프로세스)
        num_workers = cpu_count()
        pool = Pool(processes=num_workers)

        # 총 작업 개수를 미리 설정 (select_items 때 이미 설정됨)
        self.completed_files = 0
        # ProgressBar 최대값은 select_items에서 설정됨 (self.total_files)

        # 각 WebP 경로에 대해 apply_async 호출 → 태스크가 완료될 때마다 _on_task_done 콜백 실행
        for webp_path in self.webp_paths:
            args = (webp_path, output_format, delete_original)
            pool.apply_async(convert_single_webp, args=(args,), callback=self._on_task_done)

        # 모든 태스크가 Pool에 들어갔으면, 더 이상 태스크를 보내지 않으므로 close() 후 join()
        pool.close()
        # join()은 모든 워커 프로세스가 종료될 때까지 블록
        pool.join()

        # 이 시점에서 모든 콜백 ( _on_task_done ) 이 호출되었을 것 입니다.
        # _on_task_done 내부에서 “완료 메시지”를 띄우므로, 여기서는 추가 처리 불필요합니다.


if __name__ == "__main__":
    # Windows 환경에서 multiprocessing을 안전하게 쓰기 위해 보호 구문 사용
    app = WebPConverterApp()
    app.mainloop()
