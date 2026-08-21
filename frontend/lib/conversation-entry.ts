export type EntryIntent = "introduction" | "capabilities" | "help" | "clarification" | "research";

export type EntryDecision = {
  intent: EntryIntent;
  createTask: boolean;
  response?: string;
};

const RESEARCH_TERMS = [
  "催化",
  "高熵",
  "合金",
  "材料",
  "文献",
  "建模",
  "结构",
  "poscar",
  "cif",
  "dft",
  "vasp",
  "slab",
  "吸附",
  "形成能",
  "稳定性",
  "反应",
  "oer",
  "orr",
  "co2rr",
  "her",
  "catalyst",
  "alloy",
  "model",
];

const INTRO_PATTERNS = [
  /^(你好|您好|嗨|哈喽|hello|hi|hey)[!！。,.，\s]*$/i,
  /^(你是谁|请?自我介绍一下|介绍一下你自己|介绍一下自己)[?？!！。\s]*$/i,
];

const CAPABILITY_PATTERNS = [
  /^(你能做什么|你会做什么|谈谈你的功能|介绍一下你的功能|你有什么功能|你的功能是什么)[?？!！。\s]*$/i,
  /^(what can you do|what are your capabilities)[?!.\s]*$/i,
];

const HELP_PATTERNS = [
  /^(怎么使用|如何使用|使用帮助|帮助|help|怎么开始|如何开始)[?？!！。\s]*$/i,
  /^(我不知道(该)?从哪里开始|我该从哪里开始)[?？!！。\s]*$/i,
];

const TASK_ACTION_PATTERN =
  /(请|帮我|我要|我想|希望|需要|开始|执行|继续).{0,12}(检索|审查|设计|筛选|排序|构建|建模|生成|预测|计算|切面|弛豫|提交|监控|恢复|分析)/i;

const CAPABILITY_QUERY_PATTERN =
  /(你|agent|助手).{0,30}(能做什么|会做什么|有什么功能|功能是什么|可以做什么|能力|自我介绍)|介绍.{0,30}(功能|能力|你自己)|谈谈.{0,30}(功能|能力)/i;

const HELP_QUERY_PATTERN = /(怎么使用|如何使用|使用帮助|怎么开始|如何开始|从哪里开始)/i;

export function classifyConversationEntry(input: string): EntryDecision {
  const text = input.trim();
  const normalized = text.toLowerCase();
  if (!text)
    return { intent: "clarification", createTask: false, response: CLARIFICATION_RESPONSE };

  // An explicit scientific action wins even when the sentence starts with a greeting.
  if (TASK_ACTION_PATTERN.test(text) && RESEARCH_TERMS.some((term) => normalized.includes(term))) {
    return { intent: "research", createTask: true };
  }
  if (CAPABILITY_QUERY_PATTERN.test(text)) {
    return { intent: "capabilities", createTask: false, response: CAPABILITIES_RESPONSE };
  }
  if (HELP_QUERY_PATTERN.test(text)) {
    return { intent: "help", createTask: false, response: HELP_RESPONSE };
  }
  if (INTRO_PATTERNS.some((pattern) => pattern.test(text))) {
    return { intent: "introduction", createTask: false, response: INTRODUCTION_RESPONSE };
  }
  if (CAPABILITY_PATTERNS.some((pattern) => pattern.test(text))) {
    return { intent: "capabilities", createTask: false, response: CAPABILITIES_RESPONSE };
  }
  if (HELP_PATTERNS.some((pattern) => pattern.test(text))) {
    return { intent: "help", createTask: false, response: HELP_RESPONSE };
  }

  // Very short non-scientific input is safer to clarify than to start LangGraph.
  if (text.length <= 8) {
    return { intent: "clarification", createTask: false, response: CLARIFICATION_RESPONSE };
  }
  return { intent: "research", createTask: true };
}

const ENTRY_GUIDE = `
当前已完整实现的高熵合金示范工作流支持以下三种起点：

1. **从研究目标开始（A → B → C）**  
   示例：请检索并审查可靠文献，设计用于电化学 CO2 还原的五元高熵合金催化剂，并对候选组合评分和排序。

2. **直接构建指定五元组成（direct C）**  
   示例：我要构建 CuFeNiCoMn 五元高熵合金，生成三个 FCC 原子排布，并进行形成能和稳定性预筛。

3. **使用已有 POSCAR/CIF 继续计算（external structure）**  
   上传已有结构，执行形成能预筛、稳定性判据、slab、DFT 与吸附能流程。

关键步骤会等待你的人工确认，不会因为一句问候自动创建任务或提交超算。`;

export const INTRODUCTION_RESPONSE = `你好，我是 **Catalyst Agent**，一个面向电催化剂研究、设计与计算的科研 Agent。

我可以解释电催化理论与计算问题，并协助组织材料研究任务。当前以五元高熵合金电催化剂为完整示范：从可追溯文献检索和候选设计开始，继续完成 FCC bulk 建模、形成能与稳定性预筛、(111) slab 构建、VASP 输入准备、超算任务管理和单中间体吸附能计算。

从方法上看，这套“理解研究目标 → 检索证据 → 生成候选 → 低成本预筛 → DFT 验证 → 汇总结果”的闭环可以推广到各类电催化剂，用于制定面向特定反应和目标性能的靶向设计策略。不同材料体系仍需接入与其相匹配的结构模型、描述符、稳定性判据和反应中间体。

对尚未接入确定性工作流的其他电催化材料体系，我可以提供科研解释和方案建议，但不会把建议描述成已经执行的计算结果。
${ENTRY_GUIDE}`;

export const CAPABILITIES_RESPONSE = `我是面向电催化剂研究的科研 Agent。目前已经完整实现一套以五元高熵合金为例的工作流：

- **A 阶段**：理解自然语言、识别反应/材料/目标并选择分支。
- **B 阶段**：本地与在线文献检索、证据评分和人工审查。
- **C 阶段**：候选组合、bulk、CGCNN、稳定性、slab、VASP、超算和吸附能。
- **安全与追踪**：每个科研任务生成 task_id；候选、DFT 输入和远程操作保留人工门。
- **科研问答**：解释电催化、第一性原理、形成能、稳定性判据、吸附能和 VASP 参数。

网页已经支持自然语言任务创建、完整阶段时间线、人工审查、结构文件上传、结构与输入文件查看、Slurm 作业监控、历史任务恢复和结果下载。

高熵合金以外的材料体系目前主要由科研问答提供解释和建议；只有界面明确展示并由确定性节点处理的步骤，才表示系统已经实际执行。
${ENTRY_GUIDE}`;

export const HELP_RESPONSE = `当然可以。你不需要先学习命令行，只需选择一种起点并用自然语言描述目标。
${ENTRY_GUIDE}`;

export const CLARIFICATION_RESPONSE = `我还不能确定你想执行哪类科研任务，因此没有创建 task_id。

请补充电催化反应、目标产物、材料体系，或者说明你是否已有 POSCAR/CIF。若要运行当前完整示范工作流，请给出高熵合金研究目标或五元组成。你也可以输入“介绍一下你的功能”查看可用入口。
${ENTRY_GUIDE}`;
