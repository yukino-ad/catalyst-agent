from __future__ import annotations

import queue
import re
import threading
import tkinter as tk
from tkinter import messagebox, scrolledtext, ttk

from app.legacy.agent import CatalystAgent


class CatalystAgentGUI:
    def __init__(
        self,
        root: tk.Tk,
        initial_question: str | None = None,
        auto_run: bool = False,
        epochs: int = 60,
        candidate_count: int = 1,
        structures_per_candidate: int = 1,
        seed: int = 42,
    ) -> None:
        self.root = root
        self.root.title("Catalyst Agent - CGCNN + OVITO")
        self.root.geometry("1120x780")
        self.root.minsize(900, 640)
        self.events: queue.Queue[tuple[str, object]] = queue.Queue()
        self.running = False
        self._build_ui()
        if initial_question:
            self.question_var.set(initial_question)
        self.epochs_var.set(epochs)
        self.candidate_count_var.set(candidate_count)
        self.structures_per_candidate_var.set(structures_per_candidate)
        self.seed_var.set(seed)
        self.root.after(100, self._drain_events)
        if auto_run:
            self.root.after(500, self.start)

    def _build_ui(self) -> None:
        outer = ttk.Frame(self.root, padding=14)
        outer.pack(fill=tk.BOTH, expand=True)
        ttk.Label(
            outer,
            text="高熵催化剂结构、形成能与 OVITO 可视化",
            font=("Microsoft YaHei UI", 16, "bold"),
        ).pack(anchor="w")
        ttk.Label(
            outer,
            text="批量生成候选，使用现有模型预测，在 OVITO 中展示，并在后台重新训练。",
            foreground="#555555",
        ).pack(anchor="w", pady=(2, 12))

        input_frame = ttk.LabelFrame(outer, text="任务设置", padding=10)
        input_frame.pack(fill=tk.X)
        ttk.Label(input_frame, text="科研问题").grid(row=0, column=0, sticky="w")
        self.question_var = tk.StringVar(value="设计用于 CO2 还原生成 CO 的高熵催化剂")
        ttk.Entry(input_frame, textvariable=self.question_var).grid(
            row=1, column=0, columnspan=8, sticky="ew", pady=(4, 10)
        )

        self.candidate_count_var = tk.IntVar(value=1)
        self.structures_per_candidate_var = tk.IntVar(value=1)
        self.seed_var = tk.IntVar(value=42)
        self.epochs_var = tk.IntVar(value=60)
        labels = (
            ("候选材料数量", self.candidate_count_var, 1, 3),
            ("每候选排布数", self.structures_per_candidate_var, 1, 3),
            ("随机种子", self.seed_var, 0, 999999),
            ("训练轮数", self.epochs_var, 1, 500),
        )
        for index, (label, variable, minimum, maximum) in enumerate(labels):
            column = index * 2
            ttk.Label(input_frame, text=label).grid(row=2, column=column, sticky="w")
            ttk.Spinbox(
                input_frame, from_=minimum, to=maximum, textvariable=variable, width=8
            ).grid(row=2, column=column + 1, sticky="w", padx=(6, 20))
        input_frame.columnconfigure(0, weight=1)

        action_frame = ttk.Frame(outer)
        action_frame.pack(fill=tk.X, pady=10)
        self.start_button = ttk.Button(
            action_frame, text="运行 Agent 并重新训练", command=self.start
        )
        self.start_button.pack(side=tk.LEFT)
        self.status_var = tk.StringVar(value="就绪")
        ttk.Label(action_frame, textvariable=self.status_var).pack(side=tk.LEFT, padx=12)
        self.progress = ttk.Progressbar(action_frame, mode="determinate", maximum=100)
        self.progress.pack(side=tk.RIGHT, fill=tk.X, expand=True, padx=(20, 0))

        panes = ttk.Panedwindow(outer, orient=tk.VERTICAL)
        panes.pack(fill=tk.BOTH, expand=True)
        result_frame = ttk.LabelFrame(panes, text="候选结构与形成能", padding=8)
        log_frame = ttk.LabelFrame(panes, text="CGCNN 实时训练日志", padding=8)
        panes.add(result_frame, weight=2)
        panes.add(log_frame, weight=3)
        self.result_text = scrolledtext.ScrolledText(
            result_frame, wrap=tk.WORD, height=14, font=("Consolas", 10)
        )
        self.result_text.pack(fill=tk.BOTH, expand=True)
        self.log_text = scrolledtext.ScrolledText(
            log_frame, wrap=tk.WORD, height=18, font=("Consolas", 9)
        )
        self.log_text.pack(fill=tk.BOTH, expand=True)

    def start(self) -> None:
        if self.running:
            return
        question = self.question_var.get().strip()
        if not question:
            messagebox.showerror("输入错误", "请输入科研问题。")
            return
        try:
            candidate_count = self.candidate_count_var.get()
            arrangements = self.structures_per_candidate_var.get()
            seed = self.seed_var.get()
            epochs = self.epochs_var.get()
            if not 1 <= candidate_count <= 3 or not 1 <= arrangements <= 3 or epochs <= 0:
                raise ValueError
        except (tk.TclError, ValueError):
            messagebox.showerror("参数错误", "候选数量和排布数必须为 1-3，训练轮数必须大于 0。")
            return

        self.running = True
        self.start_button.configure(state=tk.DISABLED)
        self.result_text.delete("1.0", tk.END)
        self.log_text.delete("1.0", tk.END)
        self.progress["value"] = 0
        self.status_var.set("正在生成候选、预测形成能并启动 OVITO...")
        threading.Thread(
            target=self._workflow,
            args=(question, candidate_count, arrangements, seed, epochs),
            daemon=True,
        ).start()

    def _workflow(
        self, question: str, candidate_count: int, arrangements: int, seed: int, epochs: int
    ) -> None:
        try:
            agent = CatalystAgent()
            result = agent.run(
                question,
                candidate_count=candidate_count,
                build_params={"structures_per_candidate": arrangements, "seed": seed},
                predict_properties=True,
                open_ovito=True,
            )
            self.events.put(("result", result["text"]))
            self.events.put(("status", "预测和 OVITO 展示已完成，后台训练已启动..."))

            def log_callback(line: str) -> None:
                self.events.put(("log", line))
                match = re.search(r"Epoch:\s*\[(\d+)\]", line)
                if match:
                    self.events.put(
                        ("progress", min(99, (int(match.group(1)) + 1) * 100 / epochs))
                    )

            training = agent.cgcnn.train(epochs=epochs, log_callback=log_callback)
            metrics = training.get("metrics", {})
            summary = ["", "===== 后台训练完成 =====", f"实验模型：{training['model_path']}"]
            if metrics:
                summary.append(
                    f"测试集 MAE={metrics['mae']:.6f} eV/atom, "
                    f"RMSE={metrics['rmse']:.6f} eV/atom, R²={metrics['r2']:.6f}"
                )
            summary.append(
                "已替换生产模型。"
                if training["promoted_to_production"]
                else "新模型已保留，生产模型保持不变。"
            )
            self.events.put(("log", "\n".join(summary)))
            self.events.put(("done", "任务完成"))
        except Exception as error:
            self.events.put(("error", str(error)))

    def _drain_events(self) -> None:
        try:
            while True:
                event, payload = self.events.get_nowait()
                if event == "result":
                    self.result_text.insert(tk.END, str(payload))
                    self.result_text.see(tk.END)
                elif event == "log":
                    self.log_text.insert(tk.END, str(payload) + "\n")
                    self.log_text.see(tk.END)
                elif event == "status":
                    self.status_var.set(str(payload))
                elif event == "progress":
                    self.progress["value"] = float(payload)
                elif event == "done":
                    self.progress["value"] = 100
                    self.status_var.set(str(payload))
                    self.running = False
                    self.start_button.configure(state=tk.NORMAL)
                elif event == "error":
                    self.status_var.set("运行失败")
                    self.running = False
                    self.start_button.configure(state=tk.NORMAL)
                    messagebox.showerror("运行失败", str(payload))
        except queue.Empty:
            pass
        self.root.after(100, self._drain_events)


def main(
    question: str | None = None,
    auto_run: bool = False,
    epochs: int = 60,
    candidate_count: int = 1,
    structures_per_candidate: int = 1,
    seed: int = 42,
) -> None:
    root = tk.Tk()
    CatalystAgentGUI(
        root,
        initial_question=question,
        auto_run=auto_run,
        epochs=epochs,
        candidate_count=candidate_count,
        structures_per_candidate=structures_per_candidate,
        seed=seed,
    )
    root.mainloop()


if __name__ == "__main__":
    main()
