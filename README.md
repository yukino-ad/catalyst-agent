# Catalyst Agent

面向电催化高熵合金研究的 LangGraph 后端。系统从自然语言开始，经过任务理解、文献证据审查、候选组合设计、FCC bulk/slab 建模、VASP 输入审核、超算异步计算、结果解析和吸附能计算，最终输出可追溯的 JSON 状态与计算文件。

本项目是科研流程编排器和研究辅助工具，不把模型预测、候选排序或人工批准自动解释为催化活性证明。真正的科学结论仍需要检查输入、计算收敛性、参考能量和人工审查结果。

## 1. 当前状态

| 范围 | 状态 | 说明 |
| --- | --- | --- |
| A1-A4 | 可用 | 自然语言分析、反应档案、能力门、路由和计划 |
| B1-B6 | 可用 | 本地/在线文献、质量评分、Crossref/Semantic Scholar、证据和人工审查 |
| C1-C4 | 可用 | 硬约束、软评分、候选生成、最多三个候选的人工选择 |
| C5-C10 | 可用初始框架 | bulk、形成能路由、稳定性、(111) slab 和 VASP 五文件 |
| C11.1-C11.7 | 可用初始框架 | 预检、上传、Slurm 提交、监控、下载、解析、形成能回填 |
| C11.8 | 不采用 | 不建立弛豫后的静态单点链 |
| C11.9 | 可用初始框架 | 持久化任务记录连接主图和异步作业图 |
| C12.1-C12.7 | 可用初始框架 | 单中间体吸附建模、VASP、异步执行、三能量计算和人工审查 |
| 前端 F4 | 可用 | assistant-ui 聊天、完整时间线、人工审查、咨询、报告、文件、结构和 DFT 面板 |

“可用初始框架”表示代码路径、状态契约和测试已经建立；真实超算最终结果还取决于集群排队、VASP 收敛、文件下载和用户确认。

## 2. 总体数据流

```text
自然语言
  |
  +-- A: task_analysis -> capability_gate -> router -> planner
  |       |
  |       +-- normal: B1-B6 literature evidence
  |       +-- direct_c: 明确五元 HEA 建模请求，跳过文献进入 C
  |       +-- external_c: 用户提供 POSCAR/CIF，进入 C6/C7 判据
  |
  +-- B: local retrieval -> online policy -> Crossref/Semantic Scholar
  |       -> merge/deduplicate -> human review -> evidence summary
  |
  +-- C: constraints -> scoring -> candidates -> human candidate review
          -> C5 bulk -> C6 prediction or bulk DFT
          -> C7 stability -> C8 slab -> C9 review -> C10 VASP inputs
          -> C11 upload/submit/monitor/download/parse
          -> C12.1-C12.6 adsorption -> C12.7 adsorption energy review
```

主图负责从任务理解推进到作业提交和阶段桥接。长时间超算任务不应阻塞主图；提交后保存 `task_id`、Slurm job ID、远程路径和 `resume_stage`，由恢复 CLI 进入对应异步图。

## 3. A 阶段：任务理解和分支选择

### A1 任务分析

`app/task_analyzer.py` 读取自然语言，输出 `task_analysis`：

- `reaction_id`、`reaction_family`、`target_product`。
- `material_family` 和用户约束。
- 是否需要候选设计、结构建模、形成能预测和 DFT。
- `analysis_mode` 为 `llm` 或 `rule_fallback`。
- LLM 失败时保留 `analysis_warning`，确定性规则继续工作。

### A2 Reaction Profile 和能力门

`app/domain/reaction_profiles.py` 定义 CO2RR-CO、CO2RR-HCOOH、一般 CO2RR、HER、OER、ORR、NRR 和 UNKNOWN 的科学元数据。`app/capability_gate.py` 把用户请求映射为工具能力：

- OER 与其他已支持反应使用同等级的文献、候选、FCC bulk 和形成能流程；FCC 模型仍表示初始金属模型，不等同于工作态氧化物晶相。
- CO2RR-CO 的 FCC 高熵金属探索路径可以进入 C。
- 能生成结构不等于能预测反应活性。

### A3 路由

`app/graph/routes.py` 中的 `route_after_task_analysis` 有三条入口：

1. `normal`：普通科研请求，按 A -> B -> C 顺序执行。
2. `direct_c`：用户明确说“构造高熵 CuFeNiCoMn 催化剂”等五元组合，跳过 B，进入 C；仍保留 C 阶段科学边界和人工门。
3. `external_c`：用户提供 POSCAR/CIF 路径，结构先被解析，再根据是否已有形成能进入 C6 或 C7。

外部结构入口只接受实际结构文件；形成能不要求用户提供，C 阶段可以走 CGCNN 预测或后续 Bulk DFT。输入结构的坐标不能被自然语言修订随意修改。

### A4 计划

`app/planner.py` 生成阶段计划和 RAG 决策。LLM 负责理解复杂表达，规则回退负责可运行性。结构建模、性质预测和 DFT 不是自然语言一出现就强行执行，计划会把它们作为后续能力和人工确认范围。

## 4. B 阶段：可追溯文献证据

### B1 质量评分

`app/domain/literature_quality.py` 对每条文献输出维度分数和总分，重点包括：

- `metadata_quality`：题名、作者、年份、期刊、DOI、URL 是否完整。
- `task_relevance`：是否对应反应、材料和目标产物。
- `claim_evidence_quality`：是否有可引用的组成、性能和结论原文。
- 是否明确写出四元/五元金属组合，并明确属于高熵合金。
- 期刊影响力约占总评分的 20%，只作为质量维度，不替代正文证据。
- Cu、Fe、Ni、Co、Cr、Mn 等常用过渡金属有额外的组成实用性维度。

B1 是排序工具，不会把分数变成科学事实。论文不能靠多篇拼接成一个组合，也不能用常识补齐论文没有写出的元素。

### B2 本地召回

`database/literature/` 保存本地文献数据。高熵合金 Excel 数据库通过 `scripts/import_hea_xlsx.py` 导入 SQLite，并保留源文件、工作表、行号、原始组成、反应标签和证据来源。B2 默认召回 100 条、预选 60 条；本地结果不占在线配额。若本地为空，流程仍可由在线检索补充。

### B3 在线策略

`tools/literature/online_search_policy.py` 根据本地真实论文数、独立 DOI/题名数、A 级数量和反应直接匹配数决定是否联网。本地充分时返回 `local_sufficient` 并跳过 B4；本地不足时返回 `online_supplement`。用户明确要求最新/联网时最多执行 2 个查询，否则最多 1 个查询。

### B4 在线检索

`tools/literature/academic_search_tools.py` 注册 `search_crossref` 和 `search_semantic_scholar`。Crossref 用于正式出版元数据，Semantic Scholar 用于摘要、引用和开放获取链接。Kimi 的工具调用负责发起搜索，实际网络请求由本地工具执行，因此不能仅凭 Kimi 的一句话判断“已经联网”。

系统要求查询可追溯，提示词禁止编造 DOI、题名、年份、性能和结论。在线补充默认每个查询最多 5 条。`CROSSREF_MAILTO` 和 `SEMANTIC_SCHOLAR_API_KEY` 只放在 `.env`，不能写入源码。

### B5 合并和核验

`tools/literature/online_retriever.py` 合并本地与在线结果，优先按 DOI、再按规范化题名去重。Crossref 和 Semantic Scholar 可通过 DOI 或规范化题名标记 `cross_verified`；接口限流时允许保留单源结果，但必须保留 `verification_level` 和警告，不得伪装成双源互证。

### B6 人工论文门和 RAG

用户对论文选择 `accept`、`reject` 或 `defer`。接受断言可以进入 C；当前不要求再次二次人工核验。历史的 `unverified` 状态可被保留作为记录，但建模假设应明确标记为“理想建模假设”，不把它写成已验证科学事实。若所有论文被拒绝，系统按不同搜索轮次重新联网搜索，避免重复第一次结果；达到最大轮次后停止并报告原因。

## 5. C1-C4：候选组合

### C1 硬约束

`app/domain/candidate_constraints.py` 生成五元、32 原子、FCC `2x2x2` 的结构约束。明确指定元素是 `required`，文献支持元素是 `preferred`，用户排除元素不得出现。P 区元素最多一种。

常见计数规则：含 Cu 时 Cu 为 8；含 P 区元素时该元素为 3；无特殊元素时使用 8/6/6/6/6 或 7/7/6/6/6 等确定性分配。

### C2 软评分

`app/domain/candidate_scoring.py` 综合文献支持、用户约束、丰度、价格、毒性/环境风险和合成难度。形成能和结构稳定性不在 C2 中替代计算，留给 C6/C7。

### C3 候选生成

`app/domain/candidate_generation.py` 枚举符合 C1 的组合，使用 C2 排序并输出维度分数、总分、证据说明和候选 ID。C3 当前最多向人工门展示/选择三个候选。

### C4 人工候选门

`candidate_review` 记录选择、拒绝、暂缓和备注。没有选择时 C5 之后会安全跳过；这不是异常。选择后才进入结构建模。

## 6. C5-C10：结构和 VASP 输入

### C5 bulk

`app/domain/structure_modeling.py` 依据候选创建 FCC 32 原子 bulk，输出 CIF/POSCAR 和科学身份。默认结构目录为 `data/structures/`。

### C6 形成能路线

`app/domain/formation_energy.py` 和图节点对当前 CGCNN 元素域内结构进行形成能预测。网页可选择生产模型，或只在当前任务隔离目录临时训练一个 CGCNN，并查看原始训练日志、两套预测值及差值。形成能来源必须经 C6 人工门选择，C7 只消费被选择的来源；缺失结果不会被填成零。

### C6D Bulk DFT

`app/domain/bulk_dft_input.py` 生成 INCAR、KPOINTS、POSCAR、POTCAR、`vasp.slurm`。POTCAR 从 `database/PBE/` 按元素顺序拼接，预览只显示元素和势标签，不泄露完整 POTCAR。其他四个文件完整展示。用户可以提出受控自然语言修改，但不能修改 POSCAR 坐标；人工确认后才写正式目录。

### C7 稳定性

`app/domain/stability.py` 联合判断：

```text
formation_energy < 0.05 eV/atom
delta <= 6.6%
Omega >= 1.1
```

只有 `eligible_for_slab=true` 才能继续 C8。形成能缺失时为 pending，不自动通过。

### C8-C9 slab

`app/domain/slab_generation.py` 从原始 bulk POSCAR 切 `(111)` slab，目标 48 原子、真空 18 Å，写入 `data/screening_and_slabs/`。C9 检查文件、原子数、元素组成、真空层和几何质量；自动通过后仍需要人工确认。C8 使用原始 bulk POSCAR，不用错误的旧路径替代。

### C10 五文件

`app/domain/dft_input.py` 生成 slab DFT 五文件。用户确认 INCAR、KPOINTS、POSCAR、Slurm 和 POTCAR 清单后，写入 `data/dft_inputs/`。文件生成成功不代表已经提交超算。

## 7. C11：超算执行和恢复

| 小阶段 | 作用 |
| --- | --- |
| C11.1 | 选择执行模式和精度，允许暂缓 |
| C11.2 | 本地五文件预检，只读 |
| C11.3 | SSH、known_hosts、远程命令和目录预检，只读 |
| C11.4 | 生成远程计划和 SHA-256 身份 |
| C11.5.1 | 保存 task/job/scientific identity，避免重复提交 |
| C11.5.2 | `squeue`/`sacct` 查询状态 |
| C11.5.3 | 区分 Slurm 完成和 VASP 收敛 |
| C11.5.4 | 人工确认后下载 |
| C11.5.5 | 解析 OUTCAR、OSZICAR、CONTCAR |
| C11.5.6 | 失败诊断和受控重算计划 |
| C11.6 | 小型真实集群链路验证 |
| C11.7 | Bulk DFT 形成能、参考态和 C7 回填 |
| C11.9 | 用持久化记录连接主图、监控图和恢复图 |

提交需要两个独立开关：`CLUSTER_REMOTE_WRITE_ENABLED=true` 才允许上传，`CLUSTER_SUBMISSION_ENABLED=true` 才允许 `sbatch`。任何真实提交前都要人工确认。不要把私钥、POTCAR 内容或 API key 写入 `data/workflow_runs/`。

常用只读命令：

```powershell
Set-Location "C:\Users\chenheli\Documents\agent开发\catalyst-agent"
\.venv-repro\Scripts\Activate.ps1
python -u -m app.cluster_jobs_cli poll
python -u -m app.workflow_resume_cli <task_id> --show-only
python -u -m app.job_status_watch_cli <task_id>
```

监控输出 `*_empty` 表示当前持久化记录没有可轮询作业，不表示 VASP 已失败。`result_download_review_required` 表示作业已完成且等待人工输入下载确认短语。

## 8. C12：单中间体吸附

### C12.1-C12.2 计划和位点

吸附流程必须继承 slab DFT 弛豫后的 `CONTCAR` 和 clean slab 能量。每个任务只允许一个 `selected_adsorbate`，不做共吸附。用户可选择 CO、H、NH、NH2、NO、CHO/HCO、OOH/HO2 等；没有内置参考能量的中间体必须由用户提供。

### C12.3-C12.5 结构和输入

`app/domain/adsorbate_structure_builder.py` 在 clean slab 上增加一个中间体。位点生成是确定性规则，不是无记录随机坐标；吸附物类型、位点、锚定元素、距离和方向都会保存。slab 晶胞和原子坐标不能被擅自修改，吸附物数量可以按中间体原子数动态变化，不再固定 50 原子。

### C12.6 执行

`app/graph/adsorption_execution_workflow.py` 和 `app/graph/adsorption_job_operations.py` 负责吸附体系五文件、上传、Slurm 提交、监控、下载和解析。主图与恢复图都通过 `task_id` 和 `resume_stage` 共享持久化记录。

### C12.7 三能量计算

`app/domain/adsorption_energy.py` 只做三项数值运算，不自动评价吸附强弱或催化活性：

```text
E_ads = E_adsorbed_system - E_clean_slab - E_reference_adsorbate
```

参考值位于 `configs/adsorbates/reference_energy_values_v1.json`，同时保存数据版本。当前已提供的典型值包括 CO、H、NH2、NO、NH、CHO/HCO、OOH/HO2；未提供的中间体由用户输入。C12.7 输出完整计算过程、输入来源和人工 `approve`、`reject` 或 `defer`。

## 9. 人工确认点

人工输入不是隐含状态，而是流程数据的一部分：

1. B6 论文 accept/reject/defer 和备注。
2. C4 候选组合选择，最多三个。
3. C 阶段执行范围：只建模、稳定性筛选或 DFT 验证。
4. C9 slab 结构批准。
5. C10/C6D VASP 文件批准或受控修订。
6. C11.4 远程写入确认短语。
7. C11.4.3 Slurm 提交确认。
8. C11.5.4 结果下载确认短语。
9. C12.1 单一中间体选择。
10. C12.5 吸附 VASP 文件确认。
11. C12.7 吸附能批准、拒绝或暂缓。

若没有批准，图会返回清晰的 `*_review_required`、`*_skipped` 或 `*_deferred` 状态，不应把跳过误读为成功。

## 10. 目录、产物和文件追踪

### 10.1 代码和配置目录

```text
app/
  main.py                         正式自然语言入口
  task_analyzer.py                A1 任务分析
  task_router.py                  A3 路由
  planner.py                      A4 计划
  capability_gate.py              A2 能力检查
  workflow_resume_cli.py          统一恢复入口
  cluster_jobs_cli.py             C11 监控/下载相关 CLI
  graph/
    workflow.py                   主图
    routes.py                     主图路由
    nodes.py                      主图节点实现
    state.py                      LangGraph State
    services.py                   领域服务注册
    job_operations.py             C11/bulk/slab 异步图
    adsorption_workflow.py        C12.1-C12.5 建模图
    adsorption_execution_workflow.py C12.6 执行图
    adsorption_job_operations.py  C12.6/C12.7 作业图
  domain/
    reaction_profiles.py          反应档案和 C 能力
    candidate_*.py                C1-C4 约束、评分、生成和审核
    structure_modeling.py         C5 bulk
    slab_generation.py            C8 slab
    dft_input_bundle.py           C10 clean slab VASP 输入
    bulk_dft_input_bundle.py      C6D bulk VASP 输入
    adsorption_dft_input_bundle.py C12.5 吸附体系 VASP 输入
    adsorption_*.py               C12 建模、质量、能量和参考值
    submitted_job_repository.py   C11.5.1 持久化
    workflow_consultation.py      任务感知咨询、Kimi/规则回退和暂停记录
    task_report.py                确定性报告、结构静态图和建议层

  api/
    server.py                     FastAPI 统一入口
    task_manager.py               后台图执行、节点边界暂停和恢复
    workflow_timeline.py          A1-C12.7 前端阶段契约
    research_assets.py            task_id 文件与 ASE 结构解析
    job_monitor.py                只读 Slurm/OUTCAR 状态接口

tools/
  llm_client.py                   Kimi/OpenAI-compatible 客户端
  literature/                     Crossref、Semantic Scholar、本地 RAG

database/
  literature/                     本地文献、在线原始缓存
  PBE/                            POTCAR 泛函目录

configs/
  adsorbates/                     中间体和参考能量版本
  cluster/                        超算配置

data/
  structures/                     bulk CIF/POSCAR
  screening_and_slabs/            C7 记录和 C8 slab
  dft_formation_inputs/           bulk VASP 输入
  dft_inputs/                     clean slab VASP 输入
  adsorption_structures/          吸附结构
  adsorption_dft_inputs/          吸附 VASP 输入
  cluster_results/                从超算下载的真实计算结果
  cluster_jobs/                   已提交作业和 Slurm ID 记录
  workflow_runs/                  跨进程持久化任务 JSON
  reports/<task_id>/              report.html/md/json 和结构静态图

tests/                             单元、集成和端到端测试
scripts/run_tests.py               fast/integration/e2e/all 分组
scripts/encoding_audit.py          UTF-8 和路径编码审计
app/encoding.py                    Windows CLI UTF-8 配置
```

### 10.2 文件生命周期总览

模型结构、提交输入和计算结果是三类不同产物，不应互相替代：

```text
候选组成
  -> data/structures                         初始 FCC bulk CIF/POSCAR
  -> data/dft_formation_inputs               bulk DFT 五文件
  -> data/cluster_results                    下载后的 bulk CONTCAR/OUTCAR

C7 通过的 bulk
  -> data/screening_and_slabs                初始 (111) slab CIF/POSCAR
  -> data/dft_inputs                         clean slab DFT 五文件
  -> data/cluster_results                    弛豫后的 clean slab CONTCAR/能量

弛豫后的 clean slab
  -> data/adsorption_structures              加入一个中间体后的结构候选
  -> data/adsorption_dft_inputs               已选吸附结构 DFT 五文件
  -> data/cluster_results                    弛豫后的吸附体系 CONTCAR/能量
  -> C12.7                                   吸附体系 - clean slab - 参考物
```

这里的 `task_id` 是一次工作流的主追踪键，`job_id` 是该工作流中的具体计算任务，`slurm_job_id` 是超算提交后返回的数字编号。

### 10.3 FCC bulk 模型

默认根目录：

```text
data/structures/
  cif/<structure_id>.cif
  POSCAR/<structure_id>.vasp
  manifests/manifest_*.json
```

- `.cif` 便于可视化和交换。
- `.vasp` 是 POSCAR 格式，只是使用 `structure_id` 作为文件名。
- manifest 保存结构身份、组成和输出路径。
- 该目录保存建模得到的初始 bulk，不等于 DFT 弛豫后的结构。

当前示例：

```text
data/structures/cif/Cu_HEA_FCC_00001_Co6_Cu8_Fe6_Mn6_Ni6_9a22cd98.cif
data/structures/POSCAR/Cu_HEA_FCC_00001_Co6_Cu8_Fe6_Mn6_Ni6_9a22cd98.vasp
data/structures/cif/external_bb74a2856d55.cif
```

输出实现：[app/domain/structure_modeling.py](app/domain/structure_modeling.py)。

### 10.4 C8 初始 (111) slab

默认根目录：

```text
data/screening_and_slabs/
  cif/<slab_id>.cif
  POSCAR/<slab_id>.vasp
  latest_screening.json
  latest_c8_result.json
  latest_c9_quality_result.json
```

`latest_screening.json` 是 C7 结果，`latest_c8_result.json` 是最近一次切面结果，`latest_c9_quality_result.json` 是最近一次 slab 质量检查。这里的 slab 是从 bulk 切出的初始模型，尚未代表 DFT 弛豫结果。

当前外部结构示例：

```text
data/screening_and_slabs/cif/external_bb74a2856d55_slab111.cif
data/screening_and_slabs/POSCAR/external_bb74a2856d55_slab111.vasp
```

输出实现：[app/domain/slab_generation.py](app/domain/slab_generation.py)。

### 10.5 三类 VASP 输入目录

每个最终作业目录通常包含 `INCAR`、`KPOINTS`、`POSCAR`、`POTCAR` 和 `vasp.slurm`。目录按计算对象严格分开：

| 计算对象 | 本地根目录 | 路径模板 |
| --- | --- | --- |
| bulk 形成能/弛豫 | `data/dft_formation_inputs/` | `<task_id>/<bulk_job_id>/` |
| clean slab 弛豫 | `data/dft_inputs/` | `<task_id>/<slab_job_id>/` |
| 单中间体吸附体系 | `data/adsorption_dft_inputs/` | `<task_id>/<adsorption_job_id>/` |

当前真实目录示例：

```text
data/dft_formation_inputs/real-bulk-dft-20260725-011420/
data/dft_inputs/branch-abc-20260725-190412/
data/dft_inputs/external-c-dft-20260725-145226/
data/adsorption_dft_inputs/external-c-dft-20260725-145226/
```

五个输入文件的职责：

| 文件 | 作用 |
| --- | --- |
| `POSCAR` | 本次计算的初始原子结构 |
| `INCAR` | VASP 计算参数 |
| `KPOINTS` | k 点设置 |
| `POTCAR` | 按 POSCAR 元素顺序拼接的赝势，不应提交 Git |
| `vasp.slurm` | 超算资源和 VASP 启动命令 |

生成实现分别为 [app/domain/bulk_dft_input_bundle.py](app/domain/bulk_dft_input_bundle.py)、[app/domain/dft_input_bundle.py](app/domain/dft_input_bundle.py) 和 [app/domain/adsorption_dft_input_bundle.py](app/domain/adsorption_dft_input_bundle.py)。

### 10.6 单中间体吸附结构

所有枚举出的吸附结构按任务、clean slab 和中间体分层保存：

```text
data/adsorption_structures/
  <task_id>/
    <clean_slab_id>/
      <selected_adsorbate>/
        <adsorption_structure_id>/
          POSCAR
          metadata.json
```

每个任务只选择一个 `selected_adsorbate`，但可先生成多个 ontop、bridge、hollow 位点结构，再通过人工门选择一个进入 DFT。`metadata.json` 用于保存来源 slab、位点、吸附物和结构身份。

已完成 CO 案例：

```text
data/adsorption_structures/external-c-dft-20260725-145226/
  external-bb74a2856d55-fcc-01-slab111/CO/
```

进入真实 DFT 的结构为：

```text
external-bb74a2856d55-fcc-01-slab111-bridge-006-CO
```

输出实现：[app/domain/adsorbate_structure_builder.py](app/domain/adsorbate_structure_builder.py)。

### 10.7 超算目录和下载结果

上传到超算后的默认路径模板为：

```text
/work/home/acjjsbwrh5/catalyst-agent/runs/<task_id>/<job_id>/
```

具体根目录由 `.env` 中的 `CLUSTER_REMOTE_RUNS_ROOT` 控制。不要在 README 中写密码、私钥或 API Key。

只有在 C11.5.4 输入正确的 `DOWNLOAD <slurm_job_id>` 确认短语后，真实输出才下载到：

```text
data/cluster_results/<task_id>/<slurm_job_id>/
```

常见计算输出：

| 文件 | 使用方式 |
| --- | --- |
| `CONTCAR` | 弛豫后的最终结构；后续 clean slab/吸附建模应优先使用它 |
| `OUTCAR` | 完整运行、收敛和能量信息 |
| `OSZICAR` | 电子步/离子步和能量摘要 |
| `vasprun.xml` | 结构化 VASP 结果 |
| `XDATCAR` | 离子步轨迹 |
| `slurm-<id>.out` | Slurm 标准输出和运行错误 |

已完成的 clean slab 与 CO 案例：

```text
data/cluster_results/external-c-dft-20260725-145226/61817369/  clean slab
data/cluster_results/external-c-dft-20260725-145226/61822297/  slab + CO
```

已下载的 bulk 示例：

```text
data/cluster_results/real-bulk-dft-20260725-011420/61783491/
```

下载实现：[app/domain/result_download.py](app/domain/result_download.py)。

### 10.8 状态和身份追踪

```text
data/workflow_runs/<task_id>.json       工作流恢复状态和阶段身份
data/cluster_jobs/records/              每个已提交 Slurm 作业的持久化记录
data/cluster_jobs/latest_submission.json 最近一次提交摘要
data/checkpoints/                       LangGraph 检查点相关数据
```

追踪一次计算时，优先保存并核对以下字段：

```text
task_id
candidate_id
structure_id / source_clean_slab_id
adsorption_structure_id
job_id
slurm_job_id
remote_job_directory
local_result_directory
```

### 10.9 PowerShell 快速查找

从项目根目录执行：

```powershell
# 直接打开各类产物目录
explorer ".\data\structures"
explorer ".\data\screening_and_slabs"
explorer ".\data\dft_formation_inputs"
explorer ".\data\dft_inputs"
explorer ".\data\adsorption_structures"
explorer ".\data\adsorption_dft_inputs"
explorer ".\data\cluster_results"

# 按 task_id 查找所有本地文件
$taskId = "external-c-dft-20260725-145226"
Get-ChildItem .\data -Recurse -File -ErrorAction SilentlyContinue |
    Where-Object FullName -Like "*$taskId*" |
    Select-Object FullName

# 按 Slurm ID 查看下载结果
$slurmId = "61822297"
Get-ChildItem ".\data\cluster_results" -Recurse -File |
    Where-Object FullName -Like "*$slurmId*" |
    Select-Object FullName

# 列出所有 bulk、slab 和吸附 POSCAR
Get-ChildItem .\data\structures,.\data\screening_and_slabs,.\data\adsorption_structures `
    -Recurse -File -ErrorAction SilentlyContinue |
    Where-Object { $_.Name -eq "POSCAR" -or $_.Extension -eq ".vasp" } |
    Select-Object FullName

# 列出所有完整 VASP 五文件作业目录
Get-ChildItem .\data\dft_formation_inputs,.\data\dft_inputs,.\data\adsorption_dft_inputs `
    -Recurse -File -Filter "vasp.slurm" |
    Select-Object DirectoryName
```

不要使用 `data/dft_outputs/` 判断真实结果是否存在；当前正式下载位置是 `data/cluster_results/`。

## 11. 使用方式

### 11.1 只运行自然语言到 A/B

```powershell
Set-Location "C:\Users\chenheli\Documents\agent开发\catalyst-agent"
\.venv-repro\Scripts\Activate.ps1
$env:PYTHONIOENCODING = "utf-8"
$taskId = "ab-demo-$(Get-Date -Format yyyyMMdd-HHmmss)"
$q = "请检索用于电化学CO2还原选择性生成CO的五元FCC高熵合金催化剂，只输出候选组合供人工审查，不继续建模。"
python -u -m app.main $q --thread-id $taskId
```

### 11.2 明确组合直接进入 C

```powershell
$taskId = "direct-c-$(Get-Date -Format yyyyMMdd-HHmmss)"
$q = "我要构造一个高熵CuFeNiCoMn催化剂，并进行FCC建模。"
python -u -m app.main $q --thread-id $taskId
```

### 11.3 外部 POSCAR/CIF 进入 C

自然语言中提供结构目录或文件路径，并说明“使用这个模型进行稳定性判据、slab 和 DFT”。系统先解析文件，再根据形成能是否存在选择 CGCNN/C6D 或 C7。不要手工伪造形成能；仅提供结构即可。

### 11.4 C12 恢复

```powershell
python -u -m app.workflow_resume_cli <task_id> --show-only
python -u -m app.adsorption_structure_resume_cli <task_id>
```

恢复前先确认 clean slab 的 CONTCAR、clean slab 能量、吸附体系 CONTCAR/OUTCAR 和参考能量均属于同一 `task_id`。恢复 CLI 不会因为主图结束而自动凭空得到超算结果。

## 12. 配置和安全

`.env` 只保存本机配置，不提交 API key、密码、私钥和 POTCAR：

```text
LLM_ENABLED=true
LLM_PROVIDER=kimi
CLUSTER_REMOTE_WRITE_ENABLED=false
CLUSTER_SUBMISSION_ENABLED=false
CROSSREF_MAILTO=your-email@example.com
SEMANTIC_SCHOLAR_API_KEY=your-key
```

真实任务时按顺序人工打开远程写入和提交开关；离线测试使用当前 PowerShell 会话临时关闭：

```powershell
$env:CLUSTER_REMOTE_WRITE_ENABLED = "false"
$env:CLUSTER_SUBMISSION_ENABLED = "false"
$env:CLUSTER_PREFLIGHT_ENABLED = "false"
```

私钥放在用户 `.ssh`，服务器指纹放在 `known_hosts`。真实提交前确认账号、端口、远程路径、POTCAR 来源、Slurm 分区和 walltime。

## 13. 测试和编码检查

```powershell
\.venv-repro\Scripts\python.exe scripts\run_tests.py fast --quiet
\.venv-repro\Scripts\python.exe scripts\run_tests.py integration --quiet
\.venv-repro\Scripts\python.exe scripts\run_tests.py e2e --quiet
\.venv-repro\Scripts\python.exe scripts\run_tests.py all --quiet
\.venv-repro\Scripts\python.exe scripts\encoding_audit.py
\.venv-repro\Scripts\python.exe -m compileall -q app tools scripts tests
```

集成/E2E 测试必须临时关闭远程写入和提交，避免测试向超算创建目录或提交作业。真实超算验证应单独使用人工创建的测试 task，不要把测试 task 混入主流程。

当前编码策略由 `app/encoding.py` 在 CLI 启动时设置 UTF-8；持久化 JSON 写入使用 UTF-8。PowerShell 5.1 直接读取无 BOM UTF-8 文件可能显示乱码，但不代表文件内容损坏；使用 Python、`encoding_audit.py` 或 UTF-8 编辑器查看。编码审计当前排除外部第三方 Edge 数据目录 `data/edge-qa-selection/`。

## 14. 优势和限制

### 主要优势

- LangGraph State 让阶段状态、人工中断和恢复位置可追踪。
- 正常、direct C、external structure 三种入口覆盖真实科研使用场景。
- 文献证据、候选设计、结构计算和超算执行彼此解耦，便于替换 LLM、检索源和集群。
- Crossref/Semantic Scholar 和本地缓存提供可追溯的双来源路线。
- C11 异步作业不阻塞主图，失败诊断和下载由状态驱动。
- C12 每个任务只计算一个中间体，三能量公式简单、透明、可人工复核。
- POTCAR、私钥、API key 与任务 JSON 分离，减少敏感信息泄露。
- 失败、空列表、暂缓和能力不足都有显式状态，不把缺失结果静默当成功。

### 当前限制

- 真实 DFT 仍需要用户提供可用的 VASP 环境、POTCAR、超算账号和正确参考能量。
- C2 排名和 CGCNN 预测不能代替 DFT 或实验。
- OER 当前与同类反应对等支持候选生成、FCC 建模和稳定性预筛，但不支持自动生成工作态高熵氧化物晶相，也不提供 OER 活性结论；反应活性仍需吸附能、DFT 或实验验证。
- 在线学术接口可能限流；单源结果会保留警告，不能假装双源互证。
- 网页已经覆盖低风险人工审查、文件查看、结构查看和只读 DFT 监控；远程写入、`sbatch` 和结果下载等高风险动作仍遵循后端独立确认门。
- `C11.8` 静态单点不在当前流程中，当前使用弛豫后的结果进入后续阶段。

## 15. 科学结果检查清单

在把结果用于论文或报告前，逐项检查：

1. 文献是否被人工接受，组合是否在同一篇论文中明确出现。
2. 候选元素和原子计数是否符合 C1，POSCAR 元素顺序是否与 POTCAR 一致。
3. C7 的形成能、delta、Omega 是否来自同一个结构和版本。
4. slab 是否由原始 bulk POSCAR 切出，弛豫后是否使用正确 CONTCAR。
5. Slurm `COMPLETED` 是否同时满足 VASP 正常结束和收敛。
6. clean slab、吸附体系和参考物能量是否有明确来源和版本。
7. C12.7 公式、三项数值和人工决定是否完整保存。
8. 任何“理想建模假设”是否仍被清楚标记，没有被写成实验结论。

这份 README 描述的是当前代码架构和真实边界；每次新增节点、状态字段、人工门或计算参数时，应同步更新本文件和对应测试。

## 16. 任务感知对话、Kimi 和报告

### 16.1 Kimi 在系统中的四类职责

Kimi 是自然语言与科研建议层，不是科学状态的唯一事实来源：

1. **VASP 参数咨询**：解释 INCAR、KPOINTS、POTCAR 标签和 Slurm 参数，区分当前设置、一般建议和需要收敛性测试的选择。回答不能直接改 POSCAR 或 VASP 文件；采用建议仍必须经过受控修订白名单校验和第二次人工批准。
2. **专业概念解释**：解释形成能、吸附能、delta/Omega、FCC 建模假设、DFT 与 CGCNN 的证据等级、公式、单位和边界。
3. **任务报告建议**：确定性代码先汇总真实结构、能量、作业和审查记录，Kimi 仅在单独标注的“科研建议”章节提出后续研究方向。Kimi 不得补造缺失结果。
4. **通用科研问答与意图理解**：属于项目能力的动作映射到工作流；工作流之外的问题由 Kimi 回答，并标注任务结果、项目规则、一般知识或建议。

`app/domain/workflow_consultation.py` 负责意图、只读上下文、Kimi 调用和本地回退。发送给 Kimi 的上下文只包含阶段摘要和安全输出，不包含 API key、SSH 密钥、POTCAR 正文或任意本机路径。Kimi 不可直接修改 LangGraph State、结构坐标、能量、集群安全开关、上传或提交状态。

### 16.2 中途提问和继续规则

网页任务创建后，`/api/chat` 立即结束当前流式回复；`TaskManager` 在后台运行 LangGraph，页面每 1.5 秒刷新任务。这使用户在 A、B、C 或 C12 运行期间仍可继续输入自然语言。

```text
用户在聊天台提问
  -> 自动绑定当前 task_id
  -> Kimi 或本地规则只读回答
  -> consultation_history 持久化
  -> 当前节点完成后 paused_for_consultation
  -> 用户点击“继续工作流”或“保持暂停”
  -> 继续时从原 checkpoint 下一节点恢复
```

- 咨询不会抢占正在运行的 Python 函数，而是在节点边界暂停，避免生成半份结构或半写 JSON。
- 正在等待 B6/C4/C10 等人工审查时，咨询卡不会覆盖原审查卡。
- 已完成任务也会保存咨询与确认，但继续按钮不会重跑已完成图。
- 多轮咨询、阶段卡、审查卡和决定按 `created_at` 合并后永久留在中央聊天台。

### 16.3 完整任务报告

在选中任务后输入“生成本次任务报告”，或调用：

```powershell
Invoke-RestMethod -Method Post `
  -Uri "http://127.0.0.1:8000/api/tasks/<task_id>/report"
```

输出位于：

```text
data/reports/<task_id>/
  report.json                 结构化事实和来源
  report.md                   可读科研记录
  report.html                 带静态结构图的网页报告
  images/                     ASE 渲染的任务结构 PNG
```

报告包括原始任务、分支、A-C/C12 时间线、人工决定、结构清单、Slurm 状态、最终 TOTEN、最大力、形成能/吸附能公式、数据缺口、局限和后续建议。初始 POSCAR 标记为 `initial`，只有 CONTCAR 才标记为 `relaxed`；缺少 CONTCAR 时显示未获得，不会用初始模型冒充弛豫结果。

形成能数据和吸附能数据必须分开扩充训练集。吸附能记录至少同时保存吸附物、位点、吸附体系能量、clean slab 能量、参考能量、泛函/参数一致性和数据版本。

### 16.4 ASE 风格网页结构查看器

桌面 `ase gui` 不能嵌入可远程访问的网页。因此当前实现采用：

```text
ASE：后端读取 CIF/POSCAR、晶胞和元素
Three.js：浏览器旋转、缩放、平移、正交/透视和截图
```

蓝色“使用 ASE 风格查看器”链接可从 C5 bulk、C9 slab、C12 吸附结构、右侧文件中心打开。查看器支持 X/Y/Z/等轴视角、晶胞开关、固定原子区分、原子标签、视角重置和 PNG 下载，浏览器不需要安装桌面 ASE GUI。

## 17. C7 后 DFT 升级选择门

当用户在 C 阶段执行范围中选择 `[2] FCC + 形成能预测 + delta/Omega 稳定性预筛` 时，流程不会在 C7 通过后直接结束，也不会自动消耗超算资源。C7 会展示全部通过判据的结构及其 structure_id、candidate_id、形成能、delta、Omega、CIF/POSCAR 路径，由用户逐个选择进入 C8/DFT、拒绝或暂缓。只有人工选择的结构会进入 C8 切面及后续 C9-C11；远程上传和 `sbatch` 仍保留各自独立确认门。

选择 `[3] 继续完整 DFT 验证流程` 时，C7 通过结构按既定完整流程直接进入 C8，但上传和提交仍不会绕过人工确认。C7 没有通过结构，或模式 2 中没有批准任何结构时，流程安全停止并给出对应原因。

## 18. 三入口结果状态说明

- 正常 `A -> B -> C`：本地文献满足阈值时，B3 跳过联网检索属于正常决策，不再作为警告。`newly_stored_paper_count` 仅表示本轮新写入的纯在线论文；`accepted_existing_local_paper_count` 表示已接受但无需重复入库的本地或既有论文。
- 明确五元组成 direct C：例如 `CuFeNiCoMn` 被视为一个固定材料组成，三个输出是该组成的三个 FCC 原子排布，不是三个不同候选材料。此分支执行的是与反应无关的 bulk 稳定性预筛，因此 `scientific_scope=reaction_agnostic_bulk_stability`，不会伪造反应活性证据。
- 外部结构 direct C：必须传入真实存在的 POSCAR/CIF 文件，文件可以没有扩展名。路径不存在时，C6/C7 显示 `not_executed`，并记录 `workflow_stop_reason=external_structure_input_failed`，而不是输出空的 `status`。
- 最终摘要同时输出 `effective_status` 和 `raw_graph_status`。前者描述已完成的最高价值业务阶段，后者保留最后一个图节点的原始状态；因此关闭远程预检不会再掩盖本地 DFT 五文件已成功生成。
- 期刊影响指标仅在数值、来源和年份均可核验时参与 20% 维度评分。`journal_metric_coverage_count` 与 `journal_metric_missing_count` 显示覆盖情况，缺失时记零分但绝不补造数值。

## 19. assistant-ui 前端

项目在 `frontend/` 中使用 assistant-ui + Next.js，不使用历史 `web/` 原型。当前 F4 已连接真实 FastAPI/LangGraph，中央聊天台、左侧时间线和右侧工作台共享同一个 `task_id`。

### 19.1 从零启动

Node.js 已安装在 `C:\Program Files\nodejs`。若 PowerShell 不能直接识别 `node` 或 `npm`，在当前窗口临时补充 PATH：

```powershell
Set-Location "C:\Users\chenheli\Documents\agent开发\catalyst-agent\frontend"
$env:Path = "C:\Program Files\nodejs;" + $env:Path
$env:NEXT_TELEMETRY_DISABLED = "1"

node --version
npm.cmd --version
npm.cmd run dev
```

终端出现 `Ready` 后打开：

```text
http://localhost:3000
```

若 3000 已被占用，Next.js 会显示实际使用的端口，例如 `http://localhost:3001`。停止前端可以在运行窗口按 `Ctrl+C`，不会停止 Python Agent 或超算作业。

### 19.2 当前行为

- 页面可以正常打开并输入消息。
- Next.js 服务端先判断会话入口；“你好”“自我介绍”“你能做什么”“怎么使用”等输入直接返回本地说明，不调用 Kimi、FastAPI 或 LangGraph，也不创建 `task_id`。
- 所有网页回复统一先显示简短的可验证处理状态，再逐段流式输出正文；任务创建、节点进度、人工门、完成结果和错误信息均使用相同机制。该状态只描述正在执行的操作，不暴露或伪造模型隐藏推理链。
- 阶段说明采用三级信息：A1-A4 和普通节点用实时简短状态行；节点完成时追加一条来自真实 State 的关键摘要；B6 等人工门才展开来源、评分、文献和科学断言详情。这样不会用长解释人为拖慢等待，后续可再增加按需展开详情。
- 前端全局字体约定为普通及浅色正文使用微软雅黑；加粗强调文字、标题和有序列表数字放大一级，其中英文使用 Times New Roman，中文因字体字形回退使用楷体。规则位于 `frontend/app/globals.css`，后续新增回复和组件自动继承，并为缺少指定字体的设备保留系统字体回退。
- 页头提供带二次确认的当前对话删除按钮。它只清空 assistant-ui 网页消息，不删除 Python 端 `task_id`、持久化科学状态、DFT 文件或正在运行的 Slurm 作业；回复生成期间按钮禁用。后续增加历史对话列表时，每条对话复用相同删除语义。
- 含明确科研动作和对象的输入仍创建真实任务；例如“你好，请帮我构建 CuFeNiCoMn 五元高熵合金”不会被误判成普通问候。
- 很短且无法判断用途的输入不会贸然启动工作流，而是要求用户补充反应、产物、组成或结构来源。
- 首页提供正常 `A -> B -> C`、指定五元组成 direct C、已有 POSCAR/CIF 三类示例。POSCAR/CIF 网页上传属于 F4，当前第三张卡只填充说明文本，不会直接发送任务。
- `/api/chat` 通过 FastAPI 连接 Python LangGraph。创建 `web-<time>-<id>` 后立即返回，不再阻塞到六分钟任务结束；浏览器后台刷新状态，因此用户可以继续提问。
- 中央聊天台保留 A1-A4、B1-B6、C1-C12.7 的阶段摘要、结果、人工审查决定、Kimi/本地咨询和报告入口。左侧时间线仅用于快速定位，不替代聊天记录。
- B6、C4、C6、C7、C9、C10、C11 选择门、C12.4、C12.5 和 C12.7 使用统一审查卡；历史决定只读保留。
- 右侧工作台提供历史任务、恢复定位、按 task_id 的文件列表、VASP 关键文件预览和只读 DFT 监控。
- bulk、slab 和吸附结构使用 ASE 后端解析语义 + Three.js 网页查看器，可切换标准视角、透视/正交、晶胞和原子标签，并下载 PNG。
- 工作流中的科研咨询会在一个节点完成后暂停，而不会切断正在执行的节点。回答后必须选择继续或保持暂停；已完成任务只记录确认，不会重复运行图。
- 前端没有连接 OpenAI，也不要求在 `frontend/` 保存 Kimi API Key。
- Web API 默认关闭集群预检、远程上传和 Slurm 提交。只有 `WEB_REMOTE_OPERATIONS_ENABLED`、`CLUSTER_REMOTE_WRITE_ENABLED` 和 `CLUSTER_SUBMISSION_ENABLED` 全部为真时，网页才允许进入真实远程操作；`UPLOAD <task_id>` 和 `SUBMIT <task_id>` 两个独立人工门仍然强制保留。
- Kimi Key、SSH 私钥、POTCAR 和超算配置只保留在 Python 服务端。

### 19.3 全球访问设计

- assistant-ui 是随项目构建的开源界面库，不依赖 assistant-ui Cloud。
- 页面不使用 Google Fonts 或运行时第三方字体 CDN。
- 浏览器只访问自己的 HTTPS 前端/API 域名，不直连 Kimi、Crossref、Semantic Scholar 或超算 SSH。
- Python 后端统一执行 LLM、学术检索、文件持久化和超算操作。
- 初期可把前后端部署到香港或新加坡节点；若需要中国大陆长期稳定访问，再增加已备案的大陆部署节点。
- “任意国家 IP 可访问”最终仍取决于部署商、域名、DNS、防火墙和当地网络政策，不能仅由前端代码绝对保证。

### 19.4 前端关键文件

```text
frontend/
  app/page.tsx                         首页
  app/assistant.tsx                    assistant-ui Runtime 和页面框架
  app/api/chat/route.ts                本地会话分流、SSE 输出和 FastAPI 转发
  app/layout.tsx                       中文页面元数据和系统字体
  components/assistant-ui/thread.tsx   消息、输入框和附件界面
  components/workflow-record.tsx       聊天台阶段、审查和咨询合并
  components/consultation-card.tsx     Kimi/规则回答与继续确认
  components/review-card.tsx           统一人工审查卡
  components/structure-viewer.tsx      ASE 风格 Three.js 查看器
  components/task-workbench.tsx        历史、文件和 DFT 右侧面板
  lib/conversation-entry.ts            问候、帮助、含糊输入与科研任务分类
  lib/catalyst-api.ts                  FastAPI 任务、咨询、报告和资产客户端
  package.json                         Node.js 依赖和启动命令
  .env.example                         未来 FastAPI 地址示例
```

### 19.5 双终端运行

终端一启动 FastAPI。Kimi 是否启用由项目根目录 `.env` 的 `LLM_ENABLED`、`LLM_API_KEY`、`LLM_BASE_URL` 和 `LLM_MODEL` 决定。网页默认不上传或提交超算；管理员完整演示时必须显式打开三项开关：

```dotenv
WEB_REMOTE_OPERATIONS_ENABLED=true
CLUSTER_PREFLIGHT_ENABLED=true
CLUSTER_REMOTE_WRITE_ENABLED=true
CLUSTER_SUBMISSION_ENABLED=true
```

只修改 `.env` 不会改变已经运行的进程，必须重启 FastAPI。启动命令：

```powershell
Set-Location "C:\Users\chenheli\Documents\agent开发\catalyst-agent"
.\.venv-repro\Scripts\Activate.ps1
$env:PYTHONIOENCODING = "utf-8"
python -m uvicorn app.api.server:app --host 127.0.0.1 --port 8000
```

终端二启动 assistant-ui：

```powershell
Set-Location "C:\Users\chenheli\Documents\agent开发\catalyst-agent\frontend"
$env:Path = "C:\Program Files\nodejs;" + $env:Path
$env:NEXT_TELEMETRY_DISABLED = "1"
npm.cmd run dev
```

浏览器访问 `http://localhost:3000`。API 文档位于 `http://127.0.0.1:8000/docs`，健康检查位于 `http://127.0.0.1:8000/api/health`。

### 19.6 远程部署与公网访问

完整部署后，用户通过任意支持现代浏览器的设备访问公网 HTTPS 域名：

```text
用户浏览器 -> assistant-ui/Next.js -> FastAPI -> LangGraph/Kimi/超算
```

- 用户端不安装 Python、Node.js、VASP 或 SSH 密钥。
- Kimi Key、超算私钥和 POTCAR 只位于服务器。
- FastAPI 不应直接裸露到公网，应由同域反向代理转发并增加登录、权限、速率限制和审计日志。
- 当前网页已接入远程上传和 `sbatch` 人工卡，但默认总开关关闭。开启后仍校验任务、作业编号、计划摘要、精确确认短语、幂等键和审查历史。
- 全球可访问还需要公网服务器、域名、HTTPS、DNS 和合适的部署地区；代码本身不能绕过各地区网络政策。

### 19.7 常见故障

- **8000/3000 端口被占用**：使用 `Get-NetTCPConnection -LocalPort 8000` 查进程，或改用 8001/3001，并同步 `CATALYST_API_BASE_URL`。
- **Python 依赖不一致**：确认 `Get-Command python` 和 `.venv-repro\Scripts\python.exe --version`，优先直接使用虚拟环境解释器运行。
- **Kimi 400 temperature**：Kimi K3 只允许 `temperature=1`；`tools/llm_client.py` 的 Kimi 路径必须保持该值。
- **Kimi 无输出**：先查 `LLM_ENABLED`、Base URL、模型名、Key 和超时；咨询会回退本地规则，不会因此篡改工作流。
- **Crossref/Semantic Scholar 限流**：填写 `CROSSREF_MAILTO` 和可选 Semantic Scholar Key；单源结果必须保留来源，不伪装成双源互证。
- **SSH 认证失败**：检查用户名、端口、私钥、`IdentitiesOnly=yes` 和 known_hosts；不要把密码或私钥写入项目。
- **缺少 CONTCAR 或能量**：保持 `pending/not available`，先下载并解析正确 task_id 的结果，不能用 POSCAR 或零值替代。
- **中文乱码**：设置 `$env:PYTHONIOENCODING='utf-8'`，使用 `Get-Content -Encoding utf8`，再运行 `python scripts/encoding_audit.py`。

前端生产构建、TypeScript 和 lint 已通过。正式公网部署前仍应增加登录、角色权限、速率限制、HTTPS、备份、审计日志和依赖漏洞扫描；不要使用会强制降级框架的 `npm audit fix --force`。

## 20. 连接状态、空间审计与 Docker/GitHub 部署

### 20.1 工作台连接状态

标题 `Catalyst Agent` 旁显示两个真实连接状态：

- `Kimi K3 已连接`：后端完成了一次 `temperature=1`、最多 8 token 的最小 API 请求。
- `超算已连接`：后端通过现有 SSH 密钥完成只读回显探针；没有创建目录、上传或调用 `sbatch`。
- `待检查`：配置存在但尚未发起实时检查。
- `未配置`：缺少必要环境变量、密钥或 known_hosts。
- `连接失败`：请求超时、认证失败、限流或网络不可达；将鼠标悬停可看经过脱敏的说明。

页面首次打开检查一次，之后只在点击刷新图标时重新检查，不会每 1.5 秒消耗 Kimi 请求。实现文件：

```text
app/api/connection_status.py
app/api/server.py
frontend/components/connection-status.tsx
frontend/app/api/system/connections/route.ts
```

后端直接检查：

```powershell
Invoke-RestMethod -Method Post http://127.0.0.1:8000/api/system/connections/check |
    ConvertTo-Json -Depth 6
```

返回值只含状态和脱敏说明，不返回 API Key、SSH 用户、主机、密钥路径或远程根目录。

### 20.2 当前空间结论

只读审计命令不会删除文件：

```powershell
Set-Location "C:\Users\chenheli\Documents\agent开发\catalyst-agent"
.\.venv-repro\Scripts\python.exe scripts\storage_audit.py
```

2026-07-26 实测主要占用如下：

| 路径 | 大小约 | 分类 | 建议 |
|---|---:|---|---|
| `data/checkpoints` | 2.26 GB | 恢复历史 | 不直接删除；停止后端、备份并筛选任务后再压缩 |
| `.venv-repro` | 1.36 GB | 当前统一环境 | 保留 |
| `.venv` | 1.36 GB | 重复环境 | 确认统一使用 `.venv-repro` 后可人工删除 |
| `models/cgcnn-master/venv` | 1.26 GB | 待迁移环境 | 当前仍通过 `PYTHONPATH` 间接使用；先切换 `.cgcnn-python` 并移除注入逻辑，验证 CGCNN 后才能删除 |
| `frontend/.next` | 0.62 GB | 构建缓存 | 可删，`npm.cmd run build` 可重建 |
| `frontend/node_modules` | 0.53 GB | Node 依赖 | 可删，`npm.cmd ci` 可重建；开发期间建议保留 |
| `database/PBE` | 0.11 GB | 许可科学资产 | 保留，不得发布到 GitHub/Docker |
| `data/edge-qa-selection` | 0.06 GB | 浏览器测试缓存 | 可人工删除 |

`web/` 是已被 `frontend/` 取代的早期原型，`archive/` 是旧备份；两者体积很小，删除收益几乎为零。`data/cluster_results`、`data/workflow_runs`、`data/cluster_jobs`、本地文献库和 CGCNN 模型都属于业务记录或科学资产，应保留。此次审计没有删除任何文件。

### 20.3 Docker 和远程部署

新增文件：

```text
Dockerfile.backend          Python/FastAPI 科学后端镜像
frontend/Dockerfile         Next.js/assistant-ui 前端镜像
docker-compose.yml          默认安全演示模式
docker-compose.hpc.yml      管理员真实 Kimi/HPC 叠加配置
.dockerignore               排除密钥、POTCAR、缓存和大体积运行记录
docs/DEPLOYMENT_BEGINNER_GUIDE.md
```

安装并启动 Docker Desktop 后，本机安全演示：

```powershell
Set-Location "C:\Users\chenheli\Documents\agent开发\catalyst-agent"
docker compose build
docker compose up -d
docker compose ps
```

管理员真实超算演示：

```powershell
docker compose -f docker-compose.yml -f docker-compose.hpc.yml up -d --build
```

完整小白教程、Linux 云服务器、HTTPS、远程 API、私钥/PBE 只读挂载和 GitHub 命令见 `docs/DEPLOYMENT_BEGINNER_GUIDE.md`。当前电脑尚未安装 Docker，因此本次没有实际构建镜像。

### 20.4 Git 与 GitHub

- Git 是本机代码版本历史，`commit` 是一个可命名、可回退的代码快照。
- GitHub 是保存 Git 仓库、展示 README、协作和发布的平台；它本身不等于运行环境。
- Docker 保存可复现运行方式；云服务器真正对外提供服务。
- 项目接入 GitHub 后更方便备份、提交给老师、展示迭代历史、协作和自动构建 Docker。

建议先建**私有仓库**。`.gitignore` 已排除 `.env`、虚拟环境、POTCAR、checkpoint、运行记录、`node_modules` 和 `.next`；首次提交前仍必须人工检查 `git status`，确认没有密钥或许可文件。
