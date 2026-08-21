"use client";

import {
  CheckIcon,
  Clock3Icon,
  EyeIcon,
  FileCheck2Icon,
  PencilLineIcon,
  PlayIcon,
  XIcon,
} from "lucide-react";
import { useEffect, useMemo, useRef, useState } from "react";
import { Button } from "@/components/ui/button";
import {
  getTaskStructure,
  listTaskStructures,
  type CatalystTask,
  type StructureData,
} from "@/lib/catalyst-api";
import type { ReviewData, ReviewItem, ReviewOption, ReviewPayload } from "@/lib/review-types";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { StructureViewer } from "@/components/structure-viewer";
import { LiteratureBilingual } from "@/components/literature-bilingual";
import { decisionStatusLabel } from "@/lib/status-labels";
import { CandidateRadarChart } from "@/components/candidate-radar-chart";
import { useProgressiveCard } from "@/lib/use-progressive-card";

type DecisionAction = "accept" | "select" | "approve" | "revise" | "reject" | "defer";

export function ReviewCard({
  data,
  animate = false,
  onRevealComplete,
}: {
  data: ReviewData;
  animate?: boolean;
  onRevealComplete?: () => void;
}) {
  const review = data.review;
  const submitted = data.historyStatus === "submitted";
  const [choices, setChoices] = useState<Record<string, DecisionAction>>(() =>
    decisionChoices(data.submittedDecision),
  );
  const [assertionChoices, setAssertionChoices] = useState<Record<string, DecisionAction>>(() =>
    decisionChoices(data.submittedDecision, "assertions"),
  );
  const [fileConfirmations, setFileConfirmations] = useState<
    Record<string, Record<string, boolean>>
  >(() => submittedFileConfirmations(data.submittedDecision));
  const [revisionRequests, setRevisionRequests] = useState<Record<string, string>>(() =>
    submittedRevisionRequests(data.submittedDecision),
  );
  const [mode, setMode] = useState(
    String(data.submittedDecision?.mode ?? review.recommended_mode ?? ""),
  );
  const [note, setNote] = useState(String(data.submittedDecision?.note ?? ""));
  const [confirmationText, setConfirmationText] = useState(
    String(data.submittedDecision?.confirmation_text ?? ""),
  );
  const [status, setStatus] = useState<"ready" | "submitting" | "running" | "done" | "error">(
    "ready",
  );
  const [message, setMessage] = useState("");
  const config = useMemo(() => reviewConfig(review.type), [review.type]);
  const localizedReview = useMemo(() => localizeReview(review), [review]);
  const localizedOptions = useMemo(
    () => (review.options ?? []).map(localizeOption),
    [review.options],
  );
  const items = useMemo(() => review.items ?? [], [review.items]);
  const batchedItems = ["literature_review_required", "candidate_review_required"].includes(
    review.type,
  );
  const [headerRevealed, setHeaderRevealed] = useState(false);
  const [visibleItemCount, setVisibleItemCount] = useState(batchedItems ? 0 : items.length);
  const revealCompletionSent = useRef(false);
  const revealLines = useMemo(
    () => [
      config.stage,
      review.title ?? config.title,
      localizedReview.messageEn,
      localizedReview.messageZh,
      config.reason,
      ...localizedOptions.flatMap((option) => [
        option.labelEn,
        option.labelZh,
        option.explanationEn,
        option.explanationZh,
      ]),
      localizedReview.safetyEn,
      localizedReview.safetyZh,
    ],
    [config, localizedOptions, localizedReview, review.title],
  );
  const reveal = useProgressiveCard(revealLines, animate, () => {
    setHeaderRevealed(true);
    if (!batchedItems || items.length === 0) {
      revealCompletionSent.current = true;
      onRevealComplete?.();
    }
  });
  const optionOffset = 5;
  const safetyOffset = optionOffset + localizedOptions.length * 4;
  const selectedCount = Object.values(choices).filter((value) => value === config.primary).length;
  const maxSelected = review.max_selected ?? Number.POSITIVE_INFINITY;
  useEffect(() => {
    if (!batchedItems || !headerRevealed || visibleItemCount >= items.length) return;
    const timer = window.setTimeout(
      () => setVisibleItemCount((count) => Math.min(count + 3, items.length)),
      visibleItemCount === 0 ? 180 : 850,
    );
    return () => window.clearTimeout(timer);
  }, [batchedItems, headerRevealed, items.length, visibleItemCount]);

  useEffect(() => {
    if (
      !batchedItems ||
      !headerRevealed ||
      visibleItemCount < items.length ||
      revealCompletionSent.current
    ) {
      return;
    }
    revealCompletionSent.current = true;
    const timer = window.setTimeout(() => onRevealComplete?.(), 250);
    return () => window.clearTimeout(timer);
  }, [batchedItems, headerRevealed, items.length, onRevealComplete, visibleItemCount]);

  const contentRevealed = reveal.complete && (!batchedItems || visibleItemCount >= items.length);
  const allItemsDecided = items.every((item, index) =>
    Boolean(choices[String(item[config.idField] ?? `item-${index}`)]),
  );
  const approvedFilesConfirmed =
    !config.files ||
    items.every((item, index) => {
      const identifier = String(item[config.idField] ?? `item-${index}`);
      if (choices[identifier] !== config.primary) return true;
      const values = fileConfirmations[identifier] ?? {};
      return (review.required_files ?? []).every((file) => values[file] === true);
    });
  const revisionsComplete = items.every((item, index) => {
    const identifier = String(item[config.idField] ?? `item-${index}`);
    return choices[identifier] !== "revise" || Boolean(revisionRequests[identifier]?.trim());
  });
  const remoteReview = isRemoteReview(review.type);
  const phraseReview = remoteReview || review.type === "result_download_review_required";
  const hasPhraseApproval = phraseReview && Object.values(choices).includes("approve");
  const canSubmit =
    !submitted &&
    (review.actions?.includes("choose_mode")
      ? Boolean(mode)
      : items.length > 0 &&
        allItemsDecided &&
        approvedFilesConfirmed &&
        revisionsComplete &&
        (!hasPhraseApproval || confirmationText === review.confirmation_phrase));
  const submitLabel = decisionSubmitLabel(choices, config.primary, submitted);

  const submit = async () => {
    setStatus("submitting");
    setMessage("正在校验并提交人工决定...");
    try {
      const response = await fetch(`/api/tasks/${encodeURIComponent(data.taskId)}/reviews`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          review_id: review.review_id,
          review_type: review.type,
          decision: buildDecision(
            review,
            choices,
            assertionChoices,
            fileConfirmations,
            revisionRequests,
            mode,
            note,
            config,
            confirmationText,
          ),
          idempotency_key: crypto.randomUUID(),
        }),
      });
      if (!response.ok) throw await responseError(response);
      setStatus("running");
      setMessage("决定已接收，正在恢复同一个科研任务...");
      await pollTask();
    } catch (error) {
      setStatus("error");
      setMessage(error instanceof Error ? error.message : String(error));
    }
  };

  const pollTask = async () => {
    for (let attempt = 0; attempt < 900; attempt += 1) {
      const response = await fetch(`/api/tasks/${encodeURIComponent(data.taskId)}`, {
        cache: "no-store",
      });
      if (!response.ok) throw await responseError(response);
      const task = (await response.json()) as CatalystTask;
      setMessage(`${task.progress}% · ${task.stage_label}`);
      if (task.status === "waiting_for_human") {
        const next = task.review as unknown as ReviewPayload;
        if (next.review_id && next.review_id !== review.review_id) {
          setStatus("done");
          setMessage("本项决定已保存；下一项人工审查已追加到对话记录。 ");
        } else {
          setStatus("ready");
          setMessage("仍在等待本项人工审查。");
        }
        return;
      }
      if (task.status === "completed") {
        setStatus("done");
        setMessage(task.message || "工作流已完成。");
        return;
      }
      if (task.status === "failed") throw new Error(task.error || "工作流恢复失败。");
      await wait(1000);
    }
    throw new Error("等待任务恢复超时，请稍后通过 task_id 查询状态。");
  };

  return (
    <section className="my-4 border-y py-4" aria-label="人工审查">
      <div className="mb-4 flex items-start justify-between gap-3">
        <div>
          <p className="text-xs text-muted-foreground">{reveal.text(0)}</p>
          <h3 className="mt-1 min-h-6 text-base font-semibold">{reveal.text(1)}</h3>
          <BilingualText en={reveal.text(2)} zh={reveal.text(3)} className="mt-1" />
          <p className="mt-2 text-xs text-muted-foreground">{reveal.text(4)}</p>
        </div>
        <span className="shrink-0 text-xs text-muted-foreground">task_id: {data.taskId}</span>
      </div>

      {review.actions?.includes("choose_mode") ? (
        submitted ? (
          <div className="border-s-4 border-emerald-600 bg-emerald-50 px-4 py-3">
            <p className="text-sm font-semibold">{mode || "unknown"} · 已选择的执行模式</p>
            <BilingualText
              en={
                localizeOption((review.options ?? []).find((option) => option.mode === mode))
                  .explanationEn
              }
              zh={
                localizeOption((review.options ?? []).find((option) => option.mode === mode))
                  .explanationZh || "历史选择已保存。"
              }
              className="mt-1"
            />
          </div>
        ) : (
          <div className="grid gap-2">
            {(review.options ?? []).map((option, index) => {
              const offset = optionOffset + index * 4;
              const visible = reveal.text(offset);
              if (!visible) return null;
              return (
                <button
                  type="button"
                  key={option.mode}
                  onClick={() => setMode(option.mode)}
                  disabled={
                    !reveal.complete ||
                    option.disabled ||
                    (review.type === "formation_energy_source_review_required" &&
                      option.mode === "temporary_trained" &&
                      review.temporary_model_ready !== true)
                  }
                  className={`border px-3 py-3 text-left transition-colors disabled:cursor-not-allowed disabled:opacity-45 ${mode === option.mode ? "border-foreground bg-muted" : "hover:bg-muted/50"}`}
                >
                  <strong className="block font-serif">{visible}</strong>
                  {reveal.text(offset + 1) && (
                    <span className="mt-1 block text-sm font-semibold">
                      {reveal.text(offset + 1)}
                    </span>
                  )}
                  <BilingualText
                    en={reveal.text(offset + 2)}
                    zh={reveal.text(offset + 3)}
                    className="mt-2"
                  />
                </button>
              );
            })}
          </div>
        )
      ) : (
        <div className={reveal.complete ? "grid gap-3" : "hidden"}>
          {items.slice(0, batchedItems ? visibleItemCount : items.length).map((item, index) => {
            const identifier = String(item[config.idField] ?? `item-${index}`);
            const action = choices[identifier];
            return (
              <div key={identifier} className="border-b pb-3 last:border-b-0">
                <ReviewItemSummary
                  item={item}
                  identifier={identifier}
                  reviewType={review.type}
                  taskId={data.taskId}
                />
                {remoteReview && <RemoteJobDetails item={item} />}
                {submitted && <ReadOnlyDecision action={action} />}
                {config.files && (
                  <>
                    <VaspFilePreviews item={item} files={review.required_files ?? []} />
                    {submitted ? (
                      <ReadOnlyFileConfirmations
                        bundleId={identifier}
                        files={review.required_files ?? []}
                        values={fileConfirmations[identifier] ?? {}}
                      />
                    ) : (
                      <FileConfirmations
                        bundleId={identifier}
                        files={review.required_files ?? []}
                        values={fileConfirmations[identifier] ?? {}}
                        onChange={(file, checked) =>
                          setFileConfirmations((current) => ({
                            ...current,
                            [identifier]: { ...current[identifier], [file]: checked },
                          }))
                        }
                      />
                    )}
                  </>
                )}
                {!submitted && (
                  <ActionButtons
                    primary={config.primary}
                    value={action}
                    allowRevision={config.files}
                    allowReject={!remoteReview}
                    disablePrimary={action !== config.primary && selectedCount >= maxSelected}
                    onChange={(value) =>
                      setChoices((current) => ({ ...current, [identifier]: value }))
                    }
                  />
                )}
                {config.files && action === "revise" && !submitted && (
                  <ControlledRevisionEditor
                    item={item}
                    value={revisionRequests[identifier] ?? ""}
                    onChange={(value) =>
                      setRevisionRequests((current) => ({ ...current, [identifier]: value }))
                    }
                  />
                )}
                {review.type === "literature_review_required" && action === "accept" && (
                  <AssertionReview
                    item={item}
                    choices={assertionChoices}
                    onChange={(id, value) =>
                      setAssertionChoices((current) => ({ ...current, [id]: value }))
                    }
                    disabled={submitted}
                  />
                )}
              </div>
            );
          })}
        </div>
      )}

      {contentRevealed && review.type === "formation_energy_source_review_required" && (
        <FormationEnergyComparison items={items} />
      )}

      {(review.safety_notice || review.submission_safety) && (
        <p className="mt-3 border-s-2 ps-3 text-sm text-muted-foreground">
          <span className="font-serif">{reveal.text(safetyOffset)}</span>
          {reveal.text(safetyOffset + 1) && (
            <span className="mt-1 block text-xs">{reveal.text(safetyOffset + 1)}</span>
          )}
        </p>
      )}
      {contentRevealed && phraseReview && !submitted && hasPhraseApproval && (
        <label className="mt-4 block border-s-4 border-amber-500 bg-amber-50 px-4 py-3 text-sm font-semibold">
          输入完整确认短语
          <code className="mt-1 block break-all font-mono text-xs">
            {review.confirmation_phrase}
          </code>
          <input
            value={confirmationText}
            onChange={(event) => setConfirmationText(event.target.value)}
            autoComplete="off"
            spellCheck={false}
            className="mt-2 h-10 w-full border bg-background px-3 font-mono text-sm outline-none focus:border-foreground"
            placeholder={review.confirmation_phrase}
          />
          {confirmationText && confirmationText !== review.confirmation_phrase && (
            <span className="mt-1 block text-xs font-normal text-destructive">
              确认短语必须逐字一致。
            </span>
          )}
        </label>
      )}
      {contentRevealed &&
        (submitted ? (
          <div className="mt-4 border-s-4 border-emerald-600 bg-emerald-50 px-4 py-3">
            <p className="text-sm font-semibold">submitted · 历史记录，只读</p>
            <p className="mt-1 text-xs text-muted-foreground">
              {data.submittedAt
                ? `提交时间：${formatTimestamp(data.submittedAt)}`
                : "提交时间未记录"}
            </p>
            {note && <p className="mt-2 text-sm">审查备注：{note}</p>}
          </div>
        ) : (
          <>
            <label
              className="mt-4 block text-sm font-semibold"
              htmlFor={`note-${review.review_id}`}
            >
              审查备注（可选）
            </label>
            <textarea
              id={`note-${review.review_id}`}
              value={note}
              onChange={(event) => setNote(event.target.value)}
              disabled={status !== "ready"}
              className="mt-2 min-h-20 w-full resize-y border bg-background p-2 text-sm outline-none focus:border-foreground"
            />
            <div className="mt-3 flex items-center justify-between gap-3">
              <div>
                <p
                  className={`text-sm ${status === "error" ? "text-destructive" : "text-muted-foreground"}`}
                >
                  {message}
                </p>
                <p className="mt-1 text-xs text-muted-foreground">
                  {!allItemsDecided
                    ? "请先为每一项明确选择批准、修改、拒绝或暂缓。"
                    : !revisionsComplete
                      ? "请填写需要修改的具体参数。"
                      : `提交后：${review.next_stage ?? config.next}`}
                </p>
              </div>
              <Button onClick={submit} disabled={!canSubmit || status !== "ready"}>
                <PlayIcon className="size-4" />
                {submitLabel}
              </Button>
            </div>
          </>
        ))}
    </section>
  );
}

function FormationEnergyComparison({ items }: { items: ReviewItem[] }) {
  if (!items.length) return null;
  return (
    <div className="mt-4 overflow-x-auto border-y py-2">
      <table className="w-full min-w-[680px] text-left text-xs">
        <thead className="text-muted-foreground">
          <tr>
            <th className="px-2 py-2">结构</th>
            <th className="px-2 py-2">生产模型 (eV/atom)</th>
            <th className="px-2 py-2">临时模型 (eV/atom)</th>
            <th className="px-2 py-2">差值 (临时 - 生产)</th>
          </tr>
        </thead>
        <tbody className="divide-y">
          {items.map((item, index) => (
            <tr key={String(item.structure_id ?? index)}>
              <td className="break-all px-2 py-2 font-semibold">
                {String(item.structure_id ?? "--")}
              </td>
              <td className="px-2 py-2">
                {energyValue(item.pretrained_formation_energy_ev_per_atom)}
              </td>
              <td className="px-2 py-2">
                {energyValue(item.temporary_formation_energy_ev_per_atom, "等待训练")}
              </td>
              <td className="px-2 py-2">
                {energyValue(item.prediction_difference_ev_per_atom, "--")}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function energyValue(value: unknown, fallback = "--") {
  const number = Number(value);
  return value != null && Number.isFinite(number) ? number.toFixed(6) : fallback;
}

function ReadOnlyFileConfirmations({
  bundleId,
  files,
  values,
}: {
  bundleId: string;
  files: string[];
  values: Record<string, boolean>;
}) {
  const confirmed = files.filter((file) => values[file] === true);
  return (
    <div className="mb-3 border-s-2 ps-3 text-sm">
      <p className="font-semibold">输入文件确认记录</p>
      <p className="mt-1 text-muted-foreground">
        {confirmed.length ? confirmed.join("、") : "未记录逐文件确认结果"}
      </p>
      <p className="mt-1 break-all text-xs text-muted-foreground">输入包：{bundleId}</p>
    </div>
  );
}

function VaspFilePreviews({ item, files }: { item: ReviewItem; files: string[] }) {
  const previews = item.file_previews;
  if (!previews || typeof previews !== "object") return null;
  return (
    <div className="mb-3 border-s-2 ps-3">
      <p className="mb-2 flex items-center gap-2 text-sm font-semibold">
        <EyeIcon className="size-4" />
        查看 VASP 输入内容
      </p>
      <div className="grid gap-2">
        {files.map((file) => {
          const value = previews[file];
          if (value == null || value === "") return null;
          return (
            <details key={file} className="border px-3 py-2">
              <summary className="cursor-pointer select-none text-sm font-semibold">
                查看 {file}
              </summary>
              <pre className="mt-2 max-h-80 overflow-auto whitespace-pre-wrap break-words bg-muted/40 p-3 font-mono text-xs leading-5">
                {formatFilePreview(file, value)}
              </pre>
            </details>
          );
        })}
      </div>
      <p className="mt-2 text-xs text-muted-foreground">
        POTCAR 仅显示赝势拼接顺序；vasp.slurm 仅显示计算资源和运行参数。
      </p>
    </div>
  );
}

function ControlledRevisionEditor({
  item,
  value,
  onChange,
}: {
  item: ReviewItem;
  value: string;
  onChange: (value: string) => void;
}) {
  const [encut, setEncut] = useState("");
  const [ediff, setEdiff] = useState("");
  const [ediffg, setEdiffg] = useState("");
  const [nsw, setNsw] = useState("");
  const [mesh, setMesh] = useState("");
  const [center, setCenter] = useState("");
  const [nodes, setNodes] = useState("");
  const [tasksPerNode, setTasksPerNode] = useState("");
  const [partition, setPartition] = useState("");
  const [extra, setExtra] = useState(value);
  const previews = item.file_previews ?? {};
  const onChangeRef = useRef(onChange);
  onChangeRef.current = onChange;

  useEffect(() => {
    const changes: string[] = [];
    if (encut) changes.push(`将 INCAR 的 ENCUT 修改为 ${encut}`);
    if (ediff) changes.push(`将 INCAR 的 EDIFF 修改为 ${ediff}`);
    if (ediffg) changes.push(`将 INCAR 的 EDIFFG 修改为 ${ediffg}`);
    if (nsw) changes.push(`将 INCAR 的 NSW 修改为 ${nsw}`);
    if (mesh) changes.push(`将 KPOINTS 的 mesh 修改为 ${mesh.trim().split(/\s+/).join("x")}`);
    if (center) changes.push(`将 KPOINTS 的 center 修改为 ${center}`);
    if (nodes) changes.push(`将 vasp.slurm 的 nodes 修改为 ${nodes}`);
    if (tasksPerNode) changes.push(`将 vasp.slurm 的 tasks_per_node 修改为 ${tasksPerNode}`);
    if (partition) changes.push(`将 vasp.slurm 的 partition 修改为 ${partition}`);
    if (extra.trim()) changes.push(extra.trim());
    onChangeRef.current(changes.join("；"));
  }, [center, ediff, ediffg, encut, extra, mesh, nodes, nsw, partition, tasksPerNode]);

  return (
    <fieldset className="mt-3 border-s-2 ps-3 text-sm">
      <legend className="font-semibold">受控修改 VASP 参数</legend>
      <p className="mt-1 text-xs text-muted-foreground">
        只填写需要改变的值。POSCAR、原子坐标和 POTCAR 在此保持只读。
      </p>
      <div className="mt-3 grid grid-cols-2 gap-3">
        <ParameterInput
          label="INCAR · ENCUT (eV)"
          value={encut}
          onChange={setEncut}
          placeholder={incarValue(previews.INCAR, "ENCUT")}
        />
        <ParameterInput
          label="INCAR · EDIFF"
          value={ediff}
          onChange={setEdiff}
          placeholder={incarValue(previews.INCAR, "EDIFF")}
        />
        <ParameterInput
          label="INCAR · EDIFFG"
          value={ediffg}
          onChange={setEdiffg}
          placeholder={incarValue(previews.INCAR, "EDIFFG")}
        />
        <ParameterInput
          label="INCAR · NSW"
          value={nsw}
          onChange={setNsw}
          placeholder={incarValue(previews.INCAR, "NSW")}
        />
        <ParameterInput
          label="KPOINTS · mesh"
          value={mesh}
          onChange={setMesh}
          placeholder="例如 3 3 1"
        />
        <label className="grid gap-1 text-xs font-semibold">
          KPOINTS · center
          <select
            className="h-9 border bg-background px-2 font-normal"
            value={center}
            onChange={(event) => setCenter(event.target.value)}
          >
            <option value="">保持原值</option>
            <option value="Gamma">Gamma</option>
            <option value="Monkhorst-Pack">Monkhorst-Pack</option>
          </select>
        </label>
        <ParameterInput
          label="Slurm · nodes"
          value={nodes}
          onChange={setNodes}
          placeholder="保持原值"
        />
        <ParameterInput
          label="Slurm · tasks_per_node"
          value={tasksPerNode}
          onChange={setTasksPerNode}
          placeholder="保持原值"
        />
        <ParameterInput
          label="Slurm · partition"
          value={partition}
          onChange={setPartition}
          placeholder="保持原值"
        />
      </div>
      <label className="mt-3 block text-xs font-semibold">
        其他白名单修改（可选）
        <textarea
          value={extra}
          onChange={(event) => setExtra(event.target.value)}
          maxLength={2000}
          placeholder="例如：将 INCAR 的 ISMEAR 修改为 1。"
          className="mt-1 min-h-20 w-full resize-y border bg-background p-2 font-normal outline-none focus:border-foreground"
        />
      </label>
      <div className="mt-3 border bg-muted/30 p-2">
        <p className="text-xs font-semibold">将提交的修改请求</p>
        <p className="mt-1 whitespace-pre-wrap text-xs text-muted-foreground">
          {value || "尚未填写修改值。"}
        </p>
      </div>
      <p className="mt-2 text-xs text-muted-foreground">
        后端会解析并校验数值范围，生成新版本预览；新版本仍需再次人工确认。
      </p>
    </fieldset>
  );
}

function ParameterInput({
  label,
  value,
  onChange,
  placeholder,
}: {
  label: string;
  value: string;
  onChange: (value: string) => void;
  placeholder: string;
}) {
  return (
    <label className="grid gap-1 text-xs font-semibold">
      {label}
      <input
        className="h-9 border bg-background px-2 font-normal outline-none focus:border-foreground"
        value={value}
        onChange={(event) => onChange(event.target.value)}
        placeholder={placeholder || "保持原值"}
      />
    </label>
  );
}

function incarValue(value: unknown, key: string) {
  if (typeof value !== "string") return "保持原值";
  const line = value
    .split(/\r?\n/)
    .find((entry) => entry.trim().startsWith(`${key} `) || entry.trim().startsWith(`${key}=`));
  return line?.split("=", 2)[1]?.trim() || "保持原值";
}

function formatFilePreview(file: string, value: unknown) {
  if (file === "POTCAR" && Array.isArray(value)) {
    return value
      .map((entry) => {
        const record = entry as Record<string, unknown>;
        return `${String(record.element ?? "")} → ${String(record.potential ?? "")}`;
      })
      .join("\n");
  }
  if (file === "vasp.slurm" && value && typeof value === "object") {
    const labels: Record<string, string> = {
      job_name: "作业名",
      nodes: "节点数",
      tasks_per_node: "每节点任务数",
      partition: "分区",
      module_name: "VASP 模块",
      command: "运行命令",
    };
    return Object.entries(value as Record<string, unknown>)
      .map(([key, entry]) => `${labels[key] ?? key}: ${String(entry)}`)
      .join("\n");
  }
  return typeof value === "string" ? value : JSON.stringify(value, null, 2);
}

function AssertionReview({
  item,
  choices,
  onChange,
  disabled = false,
}: {
  item: ReviewItem;
  choices: Record<string, DecisionAction>;
  onChange: (id: string, value: DecisionAction) => void;
  disabled?: boolean;
}) {
  return (
    <div className="mt-3 border-s-2 ps-3">
      <p className="mb-2 text-sm font-semibold">科学断言审查</p>
      {(item.assertions ?? []).length === 0 ? (
        <p className="text-sm text-muted-foreground">该论文没有可单独审查的结构化断言。</p>
      ) : (
        item.assertions?.map((assertion) => {
          const id = String(assertion.assertion_id ?? "");
          return (
            <div key={id} className="mb-3">
              <p className="text-sm">
                {String(assertion.kind ?? "科学断言")}：{formatValue(assertion.value)}
              </p>
              {disabled ? (
                <ReadOnlyDecision action={choices[id] ?? "defer"} />
              ) : (
                <ActionButtons
                  primary="accept"
                  value={choices[id] ?? "defer"}
                  onChange={(value) => onChange(id, value)}
                />
              )}
            </div>
          );
        })
      )}
    </div>
  );
}

function FileConfirmations({
  bundleId,
  files,
  values,
  onChange,
  disabled = false,
}: {
  bundleId: string;
  files: string[];
  values: Record<string, boolean>;
  onChange: (file: string, checked: boolean) => void;
  disabled?: boolean;
}) {
  return (
    <fieldset className="mb-3 border-s-2 ps-3">
      <legend className="mb-2 flex items-center gap-2 text-sm font-semibold">
        <FileCheck2Icon className="size-4" />
        确认 VASP 输入文件
      </legend>
      <div className="flex flex-wrap gap-x-4 gap-y-2">
        {files.map((file) => (
          <label key={file} className="flex items-center gap-2 text-sm">
            <input
              type="checkbox"
              checked={values[file] === true}
              disabled={disabled}
              onChange={(event) => onChange(file, event.target.checked)}
            />
            {file}
          </label>
        ))}
      </div>
      <p className="mt-2 text-xs text-muted-foreground">
        输入包：{bundleId}。批准前必须确认全部五个文件。
      </p>
    </fieldset>
  );
}

function ReviewItemSummary({
  item,
  identifier,
  reviewType,
  taskId,
}: {
  item: ReviewItem;
  identifier: string;
  reviewType: string;
  taskId: string;
}) {
  return (
    <div className="mb-3">
      {reviewType === "literature_review_required" ? (
        <LiteratureBilingual item={item} />
      ) : (
        <p className="font-semibold">{item.title ? String(item.title) : identifier}</p>
      )}
      {Array.isArray(item.elements) && (
        <p className="text-sm text-muted-foreground">
          元素：{(item.elements as string[]).join(", ")}
        </p>
      )}
      {item.composition != null && (
        <p className="text-sm text-muted-foreground">组成：{formatValue(item.composition)}</p>
      )}
      {item.total_score != null && (
        <p className="text-sm text-muted-foreground">综合评分：{String(item.total_score)}</p>
      )}
      {reviewType === "candidate_review_required" &&
        item.scores != null &&
        typeof item.scores === "object" && (
          <CandidateRadarChart scores={item.scores as Record<string, unknown>} />
        )}
      {item.quality_score != null && (
        <p className="text-sm text-muted-foreground">证据评分：{String(item.quality_score)}</p>
      )}
      {typeof item.doi === "string" && item.doi && (
        <p className="text-sm text-muted-foreground">DOI：{item.doi}</p>
      )}
      {reviewType !== "literature_review_required" &&
        typeof item.abstract === "string" &&
        item.abstract && (
          <p className="mt-2 line-clamp-4 text-sm text-muted-foreground">{item.abstract}</p>
        )}
      {item.formation_energy_ev_per_atom != null && (
        <p className="text-sm text-muted-foreground">
          形成能：{String(item.formation_energy_ev_per_atom)} eV/atom
        </p>
      )}
      {item.atom_count != null && (
        <p className="text-sm text-muted-foreground">原子数：{String(item.atom_count)}</p>
      )}
      {item.measured_vacuum_angstrom != null && (
        <p className="text-sm text-muted-foreground">
          真空层：{String(item.measured_vacuum_angstrom)} Å
        </p>
      )}
      {item.preview_digest != null && (
        <p className="break-all text-xs text-muted-foreground">
          输入摘要 SHA-256：{String(item.preview_digest)}
        </p>
      )}
      {reviewType === "slab_review_required" && (
        <SlabStructureLink taskId={taskId} slabId={String(item.structure_id ?? identifier)} />
      )}
      {reviewType === "adsorption_energy_review_required" && (
        <div className="mt-2 bg-muted/50 p-2 text-sm">
          <p>{String(item.substitution ?? "")}</p>
          <p className="mt-1 font-semibold">
            Eads = {String(item.adsorption_energy_ev)} {String(item.energy_unit ?? "eV")}
          </p>
        </div>
      )}
    </div>
  );
}

function ReadOnlyDecision({ action }: { action?: DecisionAction }) {
  return (
    <p className="mb-3 inline-flex border border-emerald-700 bg-emerald-50 px-2.5 py-1 text-xs font-semibold text-emerald-800">
      {decisionStatusLabel(action ?? "defer")}
    </p>
  );
}

function SlabStructureLink({ taskId, slabId }: { taskId: string; slabId: string }) {
  const [structure, setStructure] = useState<StructureData | null>(null);
  const [error, setError] = useState("");
  const open = async () => {
    try {
      const structures = await listTaskStructures(taskId);
      const compact = (value: string) => value.toLowerCase().replace(/[^a-z0-9]/g, "");
      const wanted = compact(slabId);
      const match =
        structures.find(
          (item) => compact(item.label).includes(wanted) || wanted.includes(compact(item.label)),
        ) ??
        structures.find(
          (item) => item.category === "slab 结构" || item.label.toLowerCase().includes("slab"),
        ) ??
        structures[0];
      if (!match) throw new Error("该任务尚未找到可视化结构文件。");
      setStructure(await getTaskStructure(taskId, match.structure_id));
      setError("");
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : String(reason));
    }
  };
  return (
    <>
      <button
        type="button"
        onClick={() => void open()}
        className="mt-2 text-sm font-semibold text-sky-700 underline underline-offset-4 hover:text-sky-900"
      >
        查看三维结构
      </button>
      {error && <p className="mt-1 text-xs text-destructive">{error}</p>}
      <Dialog open={Boolean(structure)} onOpenChange={(value) => !value && setStructure(null)}>
        <DialogContent className="sm:max-w-[min(1100px,calc(100vw-4rem))]">
          <DialogHeader>
            <DialogTitle>{slabId}</DialogTitle>
            <DialogDescription>
              只读 slab 结构预览：拖动旋转，滚轮缩放，右键平移。
            </DialogDescription>
          </DialogHeader>
          {structure && <StructureViewer structure={structure} />}
        </DialogContent>
      </Dialog>
    </>
  );
}

function ActionButtons({
  primary,
  value,
  disablePrimary = false,
  allowRevision = false,
  allowReject = true,
  disabled = false,
  onChange,
}: {
  primary: "accept" | "select" | "approve";
  value?: DecisionAction;
  disablePrimary?: boolean;
  allowRevision?: boolean;
  allowReject?: boolean;
  disabled?: boolean;
  onChange: (value: DecisionAction) => void;
}) {
  return (
    <div className="flex flex-wrap gap-2">
      <Button
        type="button"
        size="sm"
        variant={value === primary ? "default" : "outline"}
        disabled={disabled || disablePrimary}
        onClick={() => onChange(primary)}
      >
        <CheckIcon className="size-4" />
        {primaryLabel(primary)}
      </Button>
      {allowRevision && (
        <Button
          type="button"
          size="sm"
          variant={value === "revise" ? "secondary" : "outline"}
          disabled={disabled}
          onClick={() => onChange("revise")}
        >
          <PencilLineIcon className="size-4" />
          修改
        </Button>
      )}
      {allowReject && (
        <Button
          type="button"
          size="sm"
          variant={value === "reject" ? "destructive" : "outline"}
          disabled={disabled}
          onClick={() => onChange("reject")}
        >
          <XIcon className="size-4" />
          拒绝
        </Button>
      )}
      <Button
        type="button"
        size="sm"
        variant={value === "defer" ? "secondary" : "outline"}
        disabled={disabled}
        onClick={() => onChange("defer")}
      >
        <Clock3Icon className="size-4" />
        暂缓
      </Button>
    </div>
  );
}

function reviewConfig(type: string) {
  if (type === "literature_review_required")
    return {
      stage: "B6",
      title: "文献与科学断言审查",
      reason: "确认论文来源和科学断言能否作为后续候选设计证据。",
      idField: "evidence_id",
      primary: "accept" as const,
      next: "C1 候选条件准备",
      files: false,
    };
  if (type === "candidate_review_required")
    return {
      stage: "C4",
      title: "候选材料选择",
      reason: "选择要进入结构建模的五元金属组合。",
      idField: "candidate_id",
      primary: "select" as const,
      next: "C5 FCC bulk 建模",
      files: false,
    };
  if (type === "c_stage_execution_review_required")
    return {
      stage: "C4.6",
      title: "选择 C 阶段执行范围",
      reason: "确定候选材料允许执行到候选保留、FCC 建模、稳定性预筛或 DFT 验证中的哪一步。",
      idField: "candidate_id",
      primary: "select" as const,
      next: "C5 FCC bulk 建模或结束",
      files: false,
    };
  if (type === "formation_energy_source_review_required")
    return {
      stage: "C6",
      title: "形成能来源选择",
      reason: "整项任务必须使用同一个形成能来源，C7 不会混合两套模型结果。",
      idField: "structure_id",
      primary: "select" as const,
      next: "C7 稳定性判据",
      files: false,
    };
  if (type === "c7_dft_upgrade_review_required")
    return {
      stage: "C7",
      title: "DFT 升级选择",
      reason: "从通过形成能和稳定性预筛的结构中选择继续 DFT 的对象。",
      idField: "structure_id",
      primary: "select" as const,
      next: "C8 slab 构建或 bulk DFT",
      files: false,
    };
  if (type === "slab_review_required")
    return {
      stage: "C9",
      title: "slab 质量审查",
      reason: "确认自动质量检查通过的 slab 可以进入 VASP 输入准备。",
      idField: "slab_id",
      primary: "approve" as const,
      next: "C10 VASP 输入准备",
      files: false,
    };
  if (type === "adsorption_structure_review_required")
    return {
      stage: "C12.4",
      title: "吸附结构审查",
      reason: "确认吸附位点、距离和真空层质量后再准备 VASP 输入。",
      idField: "adsorption_structure_id",
      primary: "approve" as const,
      next: "C12.5 吸附 VASP 输入准备",
      files: false,
    };
  if (type === "result_download_review_required")
    return {
      stage: "C11.5.4",
      title: "DFT 结果下载确认",
      reason: "确认后下载只读结果、解析能量，并连接后续工作流。",
      idField: "slurm_job_id",
      primary: "approve" as const,
      next: "结果下载、解析与后续工作流",
      files: false,
    };
  if (type === "dft_execution_options_required")
    return {
      stage: "C11",
      title: "DFT 计算方式选择",
      reason: "选择计算方式不会直接上传或提交超算作业。",
      idField: "job_id",
      primary: "approve" as const,
      next: "C11 本地与集群只读预检查",
      files: false,
    };
  if (type === "adsorption_intermediate_review_required")
    return {
      stage: "C12.1",
      title: "单一吸附中间体选择",
      reason: "每个任务只选择一种中间体，避免混合不同参考能定义。",
      idField: "adsorbate",
      primary: "select" as const,
      next: "C12.2 吸附位点与结构生成",
      files: false,
    };
  if (type === "adsorption_dft_execution_required")
    return {
      stage: "C12.6",
      title: "吸附 DFT 执行选择",
      reason: "当前仅支持单中间体吸附结构弛豫。",
      idField: "job_id",
      primary: "approve" as const,
      next: "C12.6 超算上传与提交审查",
      files: false,
    };
  if (type === "remote_upload_review_required")
    return {
      stage: "C11.4.2",
      title: "远程上传确认",
      reason: "核对作业、远程目录和文件摘要后，才允许在超算创建目录并上传。",
      idField: "job_id",
      primary: "approve" as const,
      next: "远程 SHA-256 校验",
      files: false,
    };
  if (type === "remote_submission_review_required")
    return {
      stage: "C11.4.3",
      title: "Slurm 提交确认",
      reason: "上传文件通过远程摘要校验后，才允许对所选作业执行 sbatch。",
      idField: "job_id",
      primary: "approve" as const,
      next: "保存 Slurm 作业编号并启动监控",
      files: false,
    };
  if (
    [
      "bulk_dft_input_review_required",
      "dft_input_review_required",
      "adsorption_dft_input_review_required",
    ].includes(type)
  )
    return {
      stage: type === "adsorption_dft_input_review_required" ? "C12.5" : "C10",
      title: "VASP 输入审查",
      reason: "逐项确认计算输入；本操作不会自动提交真实超算任务。",
      idField: "bundle_id",
      primary: "approve" as const,
      next: "DFT 执行选项",
      files: true,
    };
  if (type === "adsorption_energy_review_required")
    return {
      stage: "C12.7",
      title: "吸附能审查",
      reason: "核对吸附体系、clean slab 和参考物三项能量及其相减过程。",
      idField: "adsorption_energy_id",
      primary: "approve" as const,
      next: "吸附结果汇总",
      files: false,
    };
  return {
    stage: "Review",
    title: "人工审查",
    reason: "核对当前工作流输出并选择后续操作。",
    idField: "id",
    primary: "approve" as const,
    next: "下一工作流节点",
    files: false,
  };
}

const C_STAGE_OPTION_ZH: Record<string, { label: string; explanation: string }> = {
  candidate_only: {
    label: "仅保留候选组合并停止",
    explanation: "仅保存已排序且经人工选择的候选组成，不继续结构建模。",
  },
  fcc_only: {
    label: "仅构建 FCC bulk 结构",
    explanation:
      "FCC 是金属高熵合金常用的实用起始模型，但它属于建模假设，不能证明真实材料一定形成单相 FCC。",
  },
  stability_screening: {
    label: "FCC 建模 + 形成能与稳定性预筛",
    explanation:
      "推荐：先进行成本较低的理论预筛，可减少昂贵的 DFT 计算。CGCNN 分布外结构会保持待定，不会自动提交 DFT。",
  },
  dft_validation: {
    label: "继续完整 DFT 验证流程",
    explanation: "DFT 可提供更高保真的理论验证，但计算成本更高，并可能需要独立的超算操作审批。",
  },
};

function localizeOption(option?: ReviewOption) {
  const fallback = option ? C_STAGE_OPTION_ZH[option.mode] : undefined;
  return {
    labelEn: option?.label ?? "Unknown option",
    labelZh: option?.label_zh || fallback?.label || "",
    explanationEn: option?.explanation ?? "",
    explanationZh: option?.explanation_zh || fallback?.explanation || "",
  };
}

function localizeReview(review: ReviewPayload) {
  const cStage = review.type === "c_stage_execution_review_required";
  return {
    messageEn: review.message ?? "",
    messageZh:
      review.message_zh ||
      (cStage ? "候选材料选择已完成，请选择后续理论计算允许执行到哪一步。" : ""),
    safetyEn: review.safety_notice || review.submission_safety || "",
    safetyZh:
      review.submission_safety_zh ||
      (cStage
        ? "选择 DFT 只允许准备后续计算流程；C11 的远程上传和 sbatch 提交仍需分别人工确认。"
        : ""),
  };
}

function BilingualText({ en, zh, className = "" }: { en: string; zh: string; className?: string }) {
  if (!en && !zh) return null;
  return (
    <div className={`${className} text-sm text-muted-foreground`}>
      {en && <p className="font-serif">{en}</p>}
      {zh && <p className={en ? "mt-1" : ""}>{zh}</p>}
    </div>
  );
}

function buildDecision(
  review: ReviewPayload,
  choices: Record<string, DecisionAction>,
  assertionChoices: Record<string, DecisionAction>,
  fileConfirmations: Record<string, Record<string, boolean>>,
  revisionRequests: Record<string, string>,
  mode: string,
  note: string,
  config: ReturnType<typeof reviewConfig>,
  confirmationText: string,
) {
  if (review.actions?.includes("choose_mode")) return { mode, note };
  if (isRemoteReview(review.type)) {
    const approvedJobIds = (review.items ?? [])
      .map((item) => String(item.job_id ?? ""))
      .filter((id) => choices[id] === "approve");
    return {
      action:
        approvedJobIds.length > 0
          ? review.type === "remote_upload_review_required"
            ? "approve_upload"
            : "approve_submission"
          : "defer",
      approved_job_ids: approvedJobIds,
      plan_digest: review.plan_digest ?? "",
      confirmation_text: approvedJobIds.length > 0 ? confirmationText : "",
      note,
    };
  }
  if (review.type === "result_download_review_required") {
    const decision: Record<string, unknown> = {
      approve: [],
      reject: [],
      defer: [],
      confirmation_text: confirmationText,
      note,
    };
    for (const item of review.items ?? []) {
      const id = String(item.slurm_job_id ?? "");
      const action = choices[id];
      if (!action) throw new Error(`请先为 Slurm ${id} 明确选择操作。`);
      (decision[action] as string[]).push(id);
    }
    return decision;
  }
  const decision: Record<string, unknown> = {
    action: Object.values(choices).includes("revise") ? "revise" : "finalize",
    [config.primary]: [],
    reject: [],
    defer: [],
    revision_requests: {},
    note,
  };
  for (const item of review.items ?? []) {
    const id = String(item[config.idField] ?? "");
    const action = choices[id];
    if (!action) throw new Error(`请先为 ${id} 明确选择操作。`);
    if (action === "revise") {
      const request = revisionRequests[id]?.trim();
      if (!request) throw new Error(`请填写 ${id} 的修改要求。`);
      (decision.revision_requests as Record<string, string>)[id] = request;
      continue;
    }
    (decision[action] as string[]).push(id);
  }
  if (review.type === "literature_review_required") {
    const assertions: Record<string, string[]> = { accept: [], reject: [], defer: [] };
    for (const item of review.items ?? []) {
      const evidenceId = String(item[config.idField] ?? "");
      if ((choices[evidenceId] ?? "defer") !== "accept") continue;
      for (const assertion of item.assertions ?? []) {
        const id = String(assertion.assertion_id ?? "");
        assertions[assertionChoices[id] ?? "defer"].push(id);
      }
    }
    decision.assertions = assertions;
  }
  if (config.files) decision.file_confirmations = fileConfirmations;
  return decision;
}

function isRemoteReview(type: string) {
  return ["remote_upload_review_required", "remote_submission_review_required"].includes(type);
}

function RemoteJobDetails({ item }: { item: ReviewItem }) {
  const files = Array.isArray(item.files) ? item.files : [];
  return (
    <div className="mb-3 border-s-2 ps-3 text-xs text-muted-foreground">
      {typeof item.remote_job_directory === "string" && (
        <p className="break-all">远程目录：{item.remote_job_directory}</p>
      )}
      {item.remote_hash_verified != null && (
        <p>远程 SHA-256：{item.remote_hash_verified ? "verified · 已验证" : "pending · 待验证"}</p>
      )}
      {files.length > 0 && (
        <details className="mt-2">
          <summary className="cursor-pointer font-semibold">查看文件 SHA-256</summary>
          <div className="mt-1 grid gap-1 font-mono">
            {files.map((entry, index) => {
              const file = entry as Record<string, unknown>;
              return (
                <p key={`${String(file.name)}-${index}`} className="break-all">
                  {String(file.name ?? "file")} · {String(file.sha256 ?? "")}
                </p>
              );
            })}
          </div>
        </details>
      )}
    </div>
  );
}
function decisionSubmitLabel(
  choices: Record<string, DecisionAction>,
  primary: "accept" | "select" | "approve",
  submitted: boolean,
) {
  if (submitted) return "决定已保存";
  const values = Object.values(choices);
  if (!values.length) return "请先选择决定";
  if (values.some((value) => value === "revise")) return "提交修改并重新审查";
  if (values.every((value) => value === "defer")) return "保存暂缓并结束";
  if (values.some((value) => value === primary)) return "确认批准并继续任务";
  return "确认决定并继续任务";
}

async function responseError(response: Response) {
  const payload = (await response.json().catch(() => ({}))) as { detail?: string };
  return new Error(payload.detail ?? `请求失败 (${response.status})`);
}
function primaryLabel(primary: "accept" | "select" | "approve") {
  return primary === "accept" ? "接受" : primary === "select" ? "选择" : "批准";
}
function formatValue(value: unknown) {
  return typeof value === "string" ? value : JSON.stringify(value, null, 0);
}
function decisionChoices(
  decision: Record<string, unknown> | undefined,
  source: "items" | "assertions" = "items",
) {
  const result: Record<string, DecisionAction> = {};
  const value = source === "assertions" ? decision?.assertions : decision;
  if (!value || typeof value !== "object") return result;
  for (const action of ["accept", "select", "approve", "reject", "defer"] as DecisionAction[]) {
    const identifiers = (value as Record<string, unknown>)[action];
    if (!Array.isArray(identifiers)) continue;
    for (const identifier of identifiers) result[String(identifier)] = action;
  }
  if (source === "items" && Array.isArray(decision?.approved_job_ids)) {
    for (const identifier of decision.approved_job_ids) result[String(identifier)] = "approve";
  }
  const revisions = decision?.revision_requests;
  if (revisions && typeof revisions === "object") {
    for (const identifier of Object.keys(revisions)) result[identifier] = "revise";
  }
  return result;
}
function submittedRevisionRequests(decision: Record<string, unknown> | undefined) {
  const value = decision?.revision_requests;
  if (!value || typeof value !== "object") return {};
  return Object.fromEntries(
    Object.entries(value as Record<string, unknown>).map(([key, entry]) => [key, String(entry)]),
  );
}
function submittedFileConfirmations(decision: Record<string, unknown> | undefined) {
  const value = decision?.file_confirmations;
  return value && typeof value === "object"
    ? (value as Record<string, Record<string, boolean>>)
    : {};
}
function formatTimestamp(value: string) {
  const date = new Date(value);
  return Number.isNaN(date.valueOf()) ? value : date.toLocaleString("zh-CN");
}
function wait(milliseconds: number) {
  return new Promise((resolve) => setTimeout(resolve, milliseconds));
}
