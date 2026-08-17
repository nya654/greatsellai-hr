/**
 * Source-text reliability is distinct from ordinary extraction uncertainty,
 * such as an unresolved school. These flags suppress conclusions that would
 * otherwise look trustworthy because an older resume version was active.
 */
const SOURCE_TEXT_UNRELIABLE_FLAGS = new Set([
  "source_text_unreliable",
]);
const PAGE_SOURCE_TEXT_UNRELIABLE_FLAG = /^page_\d+_source_text_unreliable$/i;
const POSSIBLE_MOJIBAKE_FLAG = /^page_\d+_possible_mojibake$/i;
const REPARSE_SOURCE_SUPERSEDED_FLAG =
  "reparse_source_superseded_before_completion";

const NON_RESUME_DOCUMENT_FLAG = "non_resume_document";

export function hasNonResumeDocument(
  qualityFlags: readonly string[] | null | undefined,
): boolean {
  return Boolean(qualityFlags?.includes(NON_RESUME_DOCUMENT_FLAG));
}

export function hasSourceTextQualityIssue(
  qualityFlags: readonly string[] | null | undefined,
): boolean {
  return Boolean(
    qualityFlags?.some(
      (flag) =>
        SOURCE_TEXT_UNRELIABLE_FLAGS.has(flag) ||
        PAGE_SOURCE_TEXT_UNRELIABLE_FLAG.test(flag) ||
        POSSIBLE_MOJIBAKE_FLAG.test(flag),
    ),
  );
}

export function hasSupersededReparseVersion(
  qualityFlags: readonly string[] | null | undefined,
): boolean {
  return Boolean(qualityFlags?.includes(REPARSE_SOURCE_SUPERSEDED_FLAG));
}
