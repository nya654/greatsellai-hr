import type { ScoreDimensionCreateInput } from "../../types";

export interface TemplateDraftDimension extends ScoreDimensionCreateInput {
  id: string;
}

export interface ScoreTemplatePreset {
  id: string;
  name: string;
  description: string;
  dimensions: ScoreDimensionCreateInput[];
}

export const scoreTemplatePresets: ScoreTemplatePreset[] = [
  {
    id: "general-screening",
    name: "通用候选人初筛",
    description: "适用于尚未绑定具体 JD 的首轮简历筛选，只根据可验证的简历事实评分。",
    dimensions: [
      {
        label: "技能匹配",
        weight: 40,
        guidance: "重点看核心技能、工具与目标岗位场景的可验证匹配。",
      },
      {
        label: "经历深度",
        weight: 35,
        guidance: "重点看工作或实习职责范围、成果、复杂度与持续时间。",
      },
      {
        label: "教育与基础条件",
        weight: 25,
        guidance: "重点看明确记载的学历、专业及岗位必要的基础条件。",
      },
    ],
  },
  {
    id: "technical-screening",
    name: "技术岗位初筛",
    description: "适用于软件、算法、数据与 AI 等技术岗位，重点识别真实工程与项目实践。",
    dimensions: [
      {
        label: "核心技术匹配",
        weight: 40,
        guidance: "重点看岗位所需语言、框架、模型、工具和技术方向的明确记录。",
      },
      {
        label: "项目与工程实践",
        weight: 35,
        guidance: "重点看项目职责、技术方案、交付结果、复杂问题和工程规模。",
      },
      {
        label: "技术深度与成长证据",
        weight: 25,
        guidance: "重点看明确记载的性能优化、质量保障、研究、开源或持续技术投入。",
      },
    ],
  },
  {
    id: "business-screening",
    name: "销售与业务岗位初筛",
    description: "适用于销售、商务与业务拓展岗位，重点关注可验证的客户场景和业务成果。",
    dimensions: [
      {
        label: "行业与客户场景匹配",
        weight: 30,
        guidance: "重点看明确记载的行业、客户类型、产品或业务场景是否相关。",
      },
      {
        label: "业绩与目标达成",
        weight: 45,
        guidance: "重点看明确记载的营收、签约、增长、目标完成或其他业务结果。",
      },
      {
        label: "业务推进与协作",
        weight: 25,
        guidance: "重点看客户推进、跨团队协作、渠道或项目协调等可验证职责。",
      },
    ],
  },
];

export const defaultScoreTemplatePreset = scoreTemplatePresets[0];
let templateDraftDimensionSequence = 0;

export function createTemplateDraftDimensionId(): string {
  return `score-dimension-${Date.now()}-${++templateDraftDimensionSequence}`;
}

export function createTemplateDraftDimensions(
  preset: Pick<ScoreTemplatePreset, "dimensions">,
): TemplateDraftDimension[] {
  return preset.dimensions.map((dimension) => ({
    ...dimension,
    id: createTemplateDraftDimensionId(),
  }));
}
