/**
 * Engine spans are Unicode code-point offsets; a textarea's selection is in
 * UTF-16 code units. They differ once an astral-plane character (an emoji, a
 * rare CJK or historic-script letter) precedes the offset.
 */
export function codePointToUtf16(text: string, codePointOffset: number): number {
  let units = 0;
  let points = 0;
  for (const char of text) {
    if (points >= codePointOffset) break;
    units += char.length;
    points += 1;
  }
  return units;
}

/** The inverse: a UTF-16 index (a textarea's selectionStart) as a code-point offset. */
export function utf16ToCodePoint(text: string, utf16Offset: number): number {
  return Array.from(text.slice(0, Math.max(0, utf16Offset))).length;
}
