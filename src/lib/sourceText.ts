import { bridge } from "./api/bridgeClient";
import type { AlignmentContext } from "./types/finding";

/**
 * The original-language text beside the translation (#67, requirement 8
 * Option A). It comes from the alignment contexts the engine already serves
 * (`alignment.getRange`): the source tokens, their direction, and the groups
 * that say which target words each source word is aligned to. A chapter is
 * fetched once and kept here, so opening the panel or moving between verses
 * is immediate (Tier A); a verse whose alignment or text changed is fetched
 * again on its own (`alignment.get`).
 */

export interface SourceWord {
  id: string;
  word: string;
  lemma?: string;
  strong?: string;
  morph?: string;
  /** The target words aligned to this source word, in their order; empty when
   * the word has no counterpart yet. */
  targets: string[];
}

export interface SourceVerse {
  verse: string;
  available: boolean;
  message: string;
  direction: "ltr" | "rtl";
  words: SourceWord[];
}

export interface SourceChapter {
  chapter: string;
  verses: SourceVerse[];
}

/** Only what the panel draws: a long chapter's contexts are about 1 MB
 * (PSA 119, 176 verses); this keeps a few kilobytes of it. */
export function sourceVerseOf(context: AlignmentContext): SourceVerse {
  const targetWord = new Map(context.bottomTokens.map((token) => [token.id, token.word]));
  const order = new Map(context.bottomTokens.map((token, at) => [token.id, at]));
  const targets = new Map<string, string[]>();
  for (const group of context.groups) {
    const words = [...group.bottomIds]
      .sort((a, b) => (order.get(a) ?? 0) - (order.get(b) ?? 0))
      .map((id) => targetWord.get(id))
      .filter((word): word is string => !!word);
    for (const top of group.topIds) targets.set(top, [...(targets.get(top) ?? []), ...words]);
  }
  return {
    verse: context.verse,
    available: context.sourceAvailable,
    message: context.sourceMessage,
    direction: context.sourceDirection,
    words: context.topTokens.map((token) => ({
      id: token.id, word: token.word, lemma: token.lemma, strong: token.strong, morph: token.morph,
      targets: targets.get(token.id) ?? [],
    })),
  };
}

/** Chapters kept, most recently used last. */
const LIMIT = 12;
const cache = new Map<string, SourceChapter>();
const keyOf = (projectPath: string, chapter: string): string => `${projectPath}\u0000${chapter}`;

function remember(key: string, value: SourceChapter): SourceChapter {
  cache.delete(key);
  cache.set(key, value);
  while (cache.size > LIMIT) cache.delete(cache.keys().next().value as string);
  return value;
}

/** The chapter if it has been read already: no engine call. */
export function cachedSourceChapter(projectPath: string, chapter: string): SourceChapter | undefined {
  const key = keyOf(projectPath, chapter);
  const value = cache.get(key);
  return value ? remember(key, value) : undefined;
}

/** The chapter, read once per chapter. `verses` are the chapter's verse
 * strings, in order (bridges and segments as written). */
export async function loadSourceChapter(projectPath: string, chapter: string, verses: string[]): Promise<SourceChapter> {
  const cached = cachedSourceChapter(projectPath, chapter);
  if (cached) return cached;
  const range = await bridge.getAlignmentRange(chapter, verses);
  return remember(keyOf(projectPath, chapter), { chapter, verses: range.verses.map(sourceVerseOf) });
}

/** Read one verse again (its alignment or its text changed) and put it in the
 * kept chapter. Nothing happens for a chapter that is not kept. */
export async function refreshSourceVerse(projectPath: string, chapter: string, verse: string): Promise<SourceChapter | undefined> {
  const key = keyOf(projectPath, chapter);
  if (!cache.has(key)) return undefined;
  const fresh = sourceVerseOf(await bridge.getAlignment(chapter, verse));
  const kept = cache.get(key);
  if (!kept) return undefined;
  return remember(key, { ...kept, verses: kept.verses.map((row) => (row.verse === verse ? fresh : row)) });
}

/** For tests, and when the project changes. */
export function clearSourceCache(): void {
  cache.clear();
}
