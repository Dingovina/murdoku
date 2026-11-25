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

// --- composite portraits (ideas.md UI: face assembled from parts) ---

// Deterministic PRNG (mulberry32): the same portrait_seed always yields the
// same face, in the browser and in tests.
function mulberry32(seed) {
  let a = seed >>> 0;
  return function () {
    a |= 0;
    a = (a + 0x6D2B79F5) | 0;
    let t = Math.imul(a ^ (a >>> 15), 1 | a);
    t = (t + Math.imul(t ^ (t >>> 7), 61 | t)) ^ t;
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
  };
}

export const PORTRAIT_CATALOGS = {
  skin: ['#f6d7b8', '#eab98d', '#d19a6a', '#a9714b', '#8d5a3b'],
  hairColor: ['#2b2b2b', '#5a3a21', '#b98a3e', '#9c4a1e', '#7a7a80'],
  // rendered over the head circle (cx 20, cy 21, r 9) in a 40x40 viewBox
  hairForms: ['bald', 'short', 'long', 'mohawk'],
  collars: ['tshirt', 'shirt', 'turtleneck'],
};

function pick(rnd, list) {
  return list[Math.floor(rnd() * list.length)];
}

function hairSvg(form, color) {
  switch (form) {
    case 'bald':
      return '';
    case 'short':
      return `<path d="M11 21 a9 9 0 0 1 18 0 q-2 -4.5 -9 -4.5 q-7 0 -9 4.5 z" fill="${color}"/>`;
    case 'long':
      return `<path d="M11 21 a9 9 0 0 1 18 0 v7 h-3.4 v-5.4 h-11.2 v5.4 h-3.4 z" fill="${color}"/>`;
    case 'mohawk':
      return `<path d="M17.6 12.2 q2.4 -1.6 4.8 0 l-1 6.2 h-2.8 z" fill="${color}"/>`;
    default:
      return '';
  }
}

function collarSvg(form, color) {
  switch (form) {
    case 'tshirt':
      return `<path d="M7 40 c3.5 -6.5 22.5 -6.5 26 0 z" fill="${color}"/>`;
    case 'shirt':
      return `<path d="M8 40 c3 -5.5 10 -6.5 12 -4 l4 3 4 -3 c2 -2.5 9 -1.5 12 4 z" fill="${color}"/>`;
    case 'turtleneck':
      return `<path d="M9 40 c2.5 -5.5 19.5 -5.5 22 0 z" fill="${color}"/><rect x="15" y="31.5" width="10" height="6" rx="2" fill="${color}"/>`;
    default:
      return '';
  }
}

/**
 * Composite SVG portrait for a suspect: face + hair (form and color) +
 * optional glasses and beard + collar.  Deterministic per portrait_seed.
 * The victim keeps the plain skull rendering (portraitOf), so this returns
 * the SVG only for suspects.
 * @param {{id: string, name: string, portrait_seed: number}} person
 * @returns {string} an inline <svg> markup string filling the chip circle
 */
export function portraitSvg(person) {
  if (person.id === 'victim') return '';
  const rnd = mulberry32(Number(person.portrait_seed) >>> 0);
  const skin = pick(rnd, PORTRAIT_CATALOGS.skin);
  const hairColor = pick(rnd, PORTRAIT_CATALOGS.hairColor);
  const hairForm = pick(rnd, PORTRAIT_CATALOGS.hairForms);
  const hasGlasses = rnd() < 0.35;
  const hasBeard = rnd() < 0.3;
  const collar = pick(rnd, PORTRAIT_CATALOGS.collars);

  const glasses = hasGlasses
    ? `<g fill="none" stroke="#26262c" stroke-width="1.2">`
      + `<circle cx="16.6" cy="20.6" r="2.7"/><circle cx="23.4" cy="20.6" r="2.7"/>`
      + `<line x1="19.3" y1="20.6" x2="20.7" y2="20.6"/></g>`
    : `<circle cx="16.8" cy="20.4" r="1.1" fill="#26262c"/>`
      + `<circle cx="23.2" cy="20.4" r="1.1" fill="#26262c"/>`;
  const mouth = hasBeard
    ? ''
    : `<path d="M17.4 25.6 q2.6 1.8 5.2 0" stroke="#8a4a4a" stroke-width="1" fill="none" stroke-linecap="round"/>`;
  const beard = hasBeard
    ? `<path d="M12.4 24.4 a7.6 7.6 0 0 0 15.2 0 q0.6 7.4 -7.6 7.4 q-8.2 0 -7.6 -7.4 z" fill="${hairColor}"/>`
    : '';

  return '<svg viewBox="0 0 40 40" width="100%" height="100%" '
    + 'xmlns="http://www.w3.org/2000/svg" aria-hidden="true">'
    + collarSvg(collar, `hsl(${Number(person.portrait_seed) % 360}, 45%, 38%)`)
    + `<circle cx="20" cy="21" r="9" fill="${skin}"/>`
    + hairSvg(hairForm, hairColor)
    + glasses
    + mouth
    + beard
    + '</svg>';
}
