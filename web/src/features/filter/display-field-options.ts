import type { CandidateSearchDisplayFieldKey } from "../../types";

/**
 * Chinese labels for the 22 candidate display fields. This is the single
 * source for both the settings-center "筛选显示字段" panel and the
 * auto-derived result columns in the filter results table. The backend's
 * `VALID_DISPLAY_FIELD_KEYS` mirrors this exact key set — a PUT rejects any
 * key outside it — so labels must stay in lockstep with that key list.
 */
export const DISPLAY_FIELD_LABELS: Record<
  CandidateSearchDisplayFieldKey,
  string
> = {
  institution_classifications: "院校类型",
  highest_degree: "最高学历",
  education_degree: "学历",
  graduation: "毕业时间",
  employment_months: "工作年限（不含实习）",
  employment_or_internship_months: "工作年限",
  gender: "性别",
  age: "年龄",
  school: "毕业院校",
  major: "专业",
  academic_performance: "学业表现",
  experience_type: "经历类型",
  experience_name: "经历名称",
  organization: "任职机构",
  title: "职位",
  experience_award: "经历奖项",
  skills: "核心技能",
  language: "语言能力",
  scholarship: "奖学金",
  competition: "竞赛获奖",
  leadership: "领导力",
  keywords: "关键词命中",
};

export function displayFieldLabel(
  key: CandidateSearchDisplayFieldKey,
): string {
  return DISPLAY_FIELD_LABELS[key];
}

export const DISPLAY_FIELD_OPTIONS: Array<{
  key: CandidateSearchDisplayFieldKey;
  label: string;
}> = (Object.entries(DISPLAY_FIELD_LABELS) as Array<
  [CandidateSearchDisplayFieldKey, string]
>).map(([key, label]) => ({ key, label }));
