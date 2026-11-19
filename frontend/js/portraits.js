// Portrait derivation from portrait_seed. Pure, DOM-free.

/**
 * Derive portrait visuals for a person.
 * @param {{id: string, name: string, portrait_seed: number}} person
 * @returns {{hue: number, initial: string, isVictim: boolean,
 *            bg: string, fg: string, emoji: string|null}}
 */
export function portraitOf(person) {
  const isVictim = person.id === 'victim';
  const hue = Number(person.portrait_seed) % 360;
  if (isVictim) {
    return {
      hue,
      initial: '☠',
      isVictim: true,
      bg: 'hsl(0, 0%, 12%)',
      fg: '#fff',
      emoji: '☠',
    };
  }
  const n = suspectNumber(person.id);
  return {
    hue,
    initial: 'П' + n,
    isVictim: false,
    bg: `hsl(${hue}, 70%, 45%)`,
    fg: '#fff',
    emoji: null,
  };
}

/** "suspect_3" -> 3; returns null for non-suspect ids. */
export function suspectNumber(id) {
  const m = /^suspect_(\d+)$/.exec(String(id));
  return m ? Number(m[1]) : null;
}
