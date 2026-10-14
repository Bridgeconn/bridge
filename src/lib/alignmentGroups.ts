// Pure helpers over one verse's AlignmentContext (topTokens / bottomTokens /
// groups), shared by AlignmentModal.svelte and CrossVerseAlignmentModal.svelte
// so both surfaces agree on what "aligned", "unaligned" and "gap" mean.
import type { AlignmentContext, AlignmentGroupView, AlignmentToken } from "./types/finding";

type GroupsView = Pick<AlignmentContext, "groups" | "topTokens" | "bottomTokens">
  & Partial<Pick<AlignmentContext, "crossVerseAccountedIds" | "crossVerseRealizedIds" | "nullDecisions">>;

/** Ids of this verse's active null decisions on one side (#216): a word with
 *  no counterpart for a stated reason is accounted for, not a gap. */
export function nullDecidedIds(context: GroupsView, side: "source" | "target"): Set<string> {
  return new Set(
    (context.nullDecisions?.[side] ?? [])
      .filter((entry) => entry.state === "active" && entry.id)
      .map((entry) => entry.id as string),
  );
}

/** The group a target (bottom) token belongs to, if any. */
export function groupForTarget(context: GroupsView, bottomId: string): AlignmentGroupView | undefined {
  return context.groups.find((group) => group.bottomIds.includes(bottomId));
}

/** The group a source (top) token belongs to, if any. */
export function groupForSource(context: GroupsView, topId: string): AlignmentGroupView | undefined {
  return context.groups.find((group) => group.topIds.includes(topId));
}

/** Target tokens aligned to a source token, in group order. */
export function alignedTargetsFor(context: GroupsView, topId: string): AlignmentToken[] {
  const group = groupForSource(context, topId);
  if (!group) return [];
  return group.bottomIds
    .map((id) => context.bottomTokens.find((token) => token.id === id))
    .filter((token): token is AlignmentToken => Boolean(token));
}

/** Target tokens in no group -- the word bank as the editor shows it. */
export function unalignedTargets(context: GroupsView): AlignmentToken[] {
  return context.bottomTokens.filter((token) => !groupForTarget(context, token.id));
}

/** Source tokens with no target word: in no group, or in a group whose
 *  bottomIds is empty (tC keeps an empty group for an unaligned source). */
export function unmatchedSources(context: GroupsView): AlignmentToken[] {
  return context.topTokens.filter((token) => {
    const group = groupForSource(context, token.id);
    return !group || group.bottomIds.length === 0;
  });
}

/** Unaligned target tokens that no cross-verse link (#117) or null decision
 *  (#216) accounts for either: what the "not fully aligned" flag counts. */
export function unaccountedTargets(context: GroupsView): AlignmentToken[] {
  const accounted = new Set([...(context.crossVerseAccountedIds ?? []), ...nullDecidedIds(context, "target")]);
  return unalignedTargets(context).filter((token) => !accounted.has(token.id));
}

/** Unmatched source tokens that are not realized in another verse either. */
export function unrealizedSources(context: GroupsView): AlignmentToken[] {
  const realized = new Set([...(context.crossVerseRealizedIds ?? []), ...nullDecidedIds(context, "source")]);
  return unmatchedSources(context).filter((token) => !realized.has(token.id));
}

export interface GapCounts {
  sourceUnmatched: number;
  targetUnmatched: number;
}

/** Client-side mirror of the engine's per-verse `gaps` (alignment.getRange),
 *  net of cross-verse links like the engine's. */
export function gapCounts(context: GroupsView): GapCounts {
  return {
    sourceUnmatched: unrealizedSources(context).length,
    targetUnmatched: unaccountedTargets(context).length,
  };
}

/**
 * The full bottomIds to send with alignment.realign when `bottomId` is dropped
 * onto `topId`'s column. realign() replaces whatever group the top id belongs
 * to, so the words already there must be resent or they'd be bumped back to
 * the word bank. Returns null when the token is already in that column.
 */
export function bottomIdsAfterDrop(context: GroupsView, topId: string, bottomId: string): string[] | null {
  const destination = groupForSource(context, topId);
  if (destination?.bottomIds.includes(bottomId)) return null;
  return [...(destination?.bottomIds ?? []).filter((id) => id !== bottomId), bottomId];
}

/** "(1/2)" for a repeated word; callers check occurrences > 1 before rendering. */
export function occurrenceLabel(token: Pick<AlignmentToken, "occurrence" | "occurrences">): string {
  return `(${token.occurrence}/${token.occurrences})`;
}

/** The source ids a drop on `topId`'s column realigns: every source word of
 *  its group, so a joined column (#207) stays joined, or the word alone. */
export function topIdsFor(context: GroupsView, topId: string): string[] {
  const group = groupForSource(context, topId);
  return group && group.topIds.length > 1 ? [...group.topIds] : [topId];
}

export interface SourceColumn {
  /** Every source id in the column: one, or the whole group's (#207). */
  ids: string[];
  tokens: AlignmentToken[];
}

/** The interlinear's columns in verse order: one per source word, except
 *  that a group with several source words (split source, joined target:
 *  `word1 word2` → `joinedword`, #207) is one column at the place of its
 *  first word, carrying all of them. Drawing one column per source word
 *  showed the same targets under each and a drop broke the group. */
export function sourceColumns(context: GroupsView): SourceColumn[] {
  const columns: SourceColumn[] = [];
  const placed = new Set<string>();
  for (const token of context.topTokens) {
    if (placed.has(token.id)) continue;
    const ids = topIdsFor(context, token.id);
    const tokens = ids.length > 1
      ? context.topTokens.filter((t) => ids.includes(t.id))
      : [token];
    tokens.forEach((t) => placed.add(t.id));
    columns.push({ ids: tokens.map((t) => t.id), tokens });
  }
  return columns;
}

/** What "Undo last change" restores (#122): the newest edit not yet undone.
 *  Each undo writes a `restore` row whose backup is the pre-undo state, and
 *  restoring the newest backup again re-applied the change. Walking past the
 *  leading `restore` rows, the n-th undo in a row restores the n-th newest
 *  edit's backup. `history` is newest first. null when nothing is left. */
export function undoTargetId(history: Array<{ id: string; operation: string }>): string | null {
  let undone = 0;
  while (undone < history.length && history[undone].operation === "restore") undone += 1;
  const edits = history.filter((entry) => entry.operation !== "restore");
  return edits[undone]?.id ?? null;
}
