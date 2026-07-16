/**
 * Pattern matching utilities for evaluating dialogue script coverage.
 * Ignores case, punctuation, and extra whitespace.
 * Supports slot-based patterns like "Where is ...?"
 */

/**
 * Normalize text: lowercase, strip punctuation, collapse whitespace.
 */
export function normalizeText(text: string): string {
  return text
    .toLowerCase()
    .replace(/[.,!?;:'"()\-]/g, ' ')
    .replace(/\s+/g, ' ')
    .trim();
}

/**
 * Check if a dialogue turn matches a target sentence pattern.
 *
 * Supports patterns with "..." as wildcard slots:
 *   "Where is ...?" matches "Where is the library?"
 *   "Go along ..." matches "Go along this street and turn left"
 *
 * Returns true if all non-wildcard words appear in order within the text.
 */
export function matchesPattern(turnText: string, pattern: string): boolean {
  const normText = normalizeText(turnText);
  const normPattern = normalizeText(pattern);

  // If pattern has "..." wildcard, split and check each segment
  if (normPattern.includes('...')) {
    const segments = normPattern.split('...').map(s => s.trim()).filter(Boolean);
    let searchFrom = 0;
    for (const seg of segments) {
      const idx = normText.indexOf(seg, searchFrom);
      if (idx === -1) return false;
      searchFrom = idx + seg.length;
    }
    return true;
  }

  // Exact match after normalization
  return normText.includes(normPattern);
}

/**
 * Check all target patterns against all dialogue turns.
 * Returns coverage stats: which patterns matched, which didn't.
 */
export function checkPatternCoverage(
  dialogue: Array<{ text: string }>,
  targetPatterns: string[],
): { matched: string[]; unmatched: string[]; coverage: number } {
  const matched: string[] = [];
  const unmatched: string[] = [];

  for (const pattern of targetPatterns) {
    const found = dialogue.some(turn => matchesPattern(turn.text, pattern));
    if (found) {
      matched.push(pattern);
    } else {
      unmatched.push(pattern);
    }
  }

  const coverage = targetPatterns.length > 0
    ? matched.length / targetPatterns.length
    : 1;

  return { matched, unmatched, coverage };
}
