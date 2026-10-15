/**
 * A chapter's verse keys in reading order (#302), the same rule as the
 * engine's `verse_order_key` (tc_project.py): `front` first, then by the
 * leading verse number, so a bridge `3-4` sits after 2 and lettered segments
 * `5a`, `5b` after 4; keys with no leading number go last, by their text.
 *
 * A verse map that crossed the IPC boundary as an object has lost its order:
 * JavaScript enumerates integer-like keys ("1", "2", "6") first and other
 * strings ("3-4", "5a") after them, so `Object.keys` put bridges and segments
 * after the chapter's last verse. Bridges and segments are real input
 * (CLAUDE.md gotcha 12).
 */
type Key = [number, number, string];

function keyOf(verse: string): Key {
  if (verse === "front") return [-1, 0, ""];
  const match = /^\d+/.exec(verse);
  if (match) return [0, Number(match[0]), verse.slice(match[0].length)];
  return [1, 0, verse];
}

export function compareVerses(a: string, b: string): number {
  const [ga, na, ra] = keyOf(a);
  const [gb, nb, rb] = keyOf(b);
  if (ga !== gb) return ga - gb;
  if (na !== nb) return na - nb;
  return ra < rb ? -1 : ra > rb ? 1 : 0;
}

/** The verses in reading order; the same array when it already is. */
export function inReadingOrder(verses: string[]): string[] {
  for (let at = 1; at < verses.length; at += 1) {
    if (compareVerses(verses[at - 1], verses[at]) > 0) return [...verses].sort(compareVerses);
  }
  return verses;
}
