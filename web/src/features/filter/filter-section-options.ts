import type { FilterSectionKey } from "../../types";

export interface FilterSectionOption {
  key: FilterSectionKey;
  label: string;
  description: string;
}

/**
 * The "初筛条件板块" — the left filter panel's sections, treated as
 * pluggable blocks. This is the single source for both the settings-center
 * "初筛条件板块" panel and the FilterPanel render. The backend's
 * `VALID_FILTER_SECTION_KEYS` mirrors this exact key set — a PUT rejects any
 * key outside it — so labels must stay in lockstep with that key list.
 */
export const FILTER_SECTION_OPTIONS: FilterSectionOption[] = [
  {
    key: "condition_mode",
    label: "全局匹配方式",
    description: "精确匹配 / 模糊匹配",
  },
  {
    key: "institution",
    label: "院校等级",
    description: "院校等级与最高学历",
  },
  {
    key: "basic_profile",
    label: "基本资料",
    description: "性别与年龄范围",
  },
  {
    key: "academic",
    label: "学业表现",
    description: "最低成绩 / GPA 与成绩排名",
  },
  {
    key: "graduation",
    label: "毕业状态",
    description: "应届 / 往届与毕业时间窗口",
  },
  {
    key: "experience",
    label: "工作年限",
    description: "最低工作年限",
  },
  {
    key: "source_channel",
    label: "投递渠道",
    description: "简历来源渠道",
  },
  {
    key: "keywords",
    label: "匹配关键词",
    description: "岗位关键词与匹配方式",
  },
];

export const ALL_FILTER_SECTION_KEYS: FilterSectionKey[] =
  FILTER_SECTION_OPTIONS.map((option) => option.key);

export function filterSectionLabel(key: FilterSectionKey): string {
  return (
    FILTER_SECTION_OPTIONS.find((option) => option.key === key)?.label ?? key
  );
}
