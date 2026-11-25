// Russian clue text rendering. Pure, DOM-free (ARCHITECTURE.md §5).

const OBJ = {
  table:     { nom: 'стол',        prep: 'столе',        instr: 'со столом',        gen: 'стола' },
  tv:        { nom: 'телевизор',   prep: 'телевизоре',   instr: 'с телевизором',    gen: 'телевизора' },
  wardrobe:  { nom: 'шкаф',        prep: 'шкафу',        instr: 'со шкафом',        gen: 'шкафа' },
  fridge:    { nom: 'холодильник', prep: 'холодильнике', instr: 'с холодильником',  gen: 'холодильника' },
  bed:       { nom: 'кровать',     prep: 'кровати',      instr: 'с кроватью',       gen: 'кровати' },
  carpet:    { nom: 'ковёр',       prep: 'ковре',        instr: 'с ковром',         gen: 'ковра' },
  armchair:  { nom: 'кресло',      prep: 'кресле',       instr: 'с креслом',        gen: 'кресла' },
  sofa:      { nom: 'диван',       prep: 'диване',       instr: 'с диваном',        gen: 'дивана' },
};

const OPS = { eq: 'ровно', ne: 'не', gt: 'более', ge: 'не менее', lt: 'менее', le: 'не более' };

const DIR = { south: 'южнее', north: 'севернее', east: 'восточнее', west: 'западнее' };

/** 1 -> "человек"; 2–4 -> "человека"; 5+ and 11–14 -> "человек". */
export function peopleForm(k) {
  const n = Math.abs(Number(k));
  const mod10 = n % 10;
  const mod100 = n % 100;
  if (mod10 >= 2 && mod10 <= 4 && (mod100 < 11 || mod100 > 14)) return 'человека';
  return 'человек';
}

/**
 * Noun form after a D1 operator. For "более / не менее / менее / не более"
 * Russian requires the genitive: 1 -> "человека", everything else -> "человек"
 * (SPEC §4 D1 examples). For "ровно / не" the plain counting form applies.
 */
function d1Noun(k, op) {
  const comparative = op === 'gt' || op === 'ge' || op === 'lt' || op === 'le';
  if (!comparative) return peopleForm(k);
  const n = Math.abs(Number(k));
  const endsIn1 = n % 10 === 1 && n % 100 !== 11;
  return endsIn1 ? 'человека' : 'человек';
}

/** "Подозреваемый_3" -> "Подозреваемого_3"; "Убитый" -> "Убитого". */
export function personGenitive(name) {
  const s = String(name);
  const m = /^(.*)ый(_\d+)?$/.exec(s);
  if (m) return m[1] + 'ого' + (m[2] || '');
  return s;
}

function objForms(type) {
  const f = OBJ[type];
  if (!f) throw new Error('Unknown object type: ' + type);
  return f;
}

function personName(peopleMap, id) {
  const p = peopleMap.get(id);
  if (!p) throw new Error('Unknown person id: ' + id);
  return p.name;
}

/**
 * Render one clue to Russian text (no trailing period).
 * @param {object} clue clue dict (SPEC §4 format)
 * @param {Map<string, {id: string, name: string}>} peopleMap person_id -> person
 */
export function clueToText(clue, peopleMap) {
  const name = (id) => personName(peopleMap, id);
  switch (clue.kind) {
    case 'on':            return `${name(clue.person)} был на ${objForms(clue.object_type).prep}`;
    case 'not_on':        return `${name(clue.person)} был не на ${objForms(clue.object_type).prep}`;
    case 'adjacent':      return `${name(clue.person)} был рядом ${objForms(clue.object_type).instr}`;
    case 'not_adjacent':  return `${name(clue.person)} был не рядом ${objForms(clue.object_type).instr}`;
    case 'room_has_object':     return `${name(clue.person)} был в комнате, где есть ${objForms(clue.object_type).nom}`;
    case 'room_not_has_object': return `${name(clue.person)} был в комнате, где нет ${objForms(clue.object_type).gen}`;
    case 'south':
    case 'north':
    case 'east':
    case 'west':          return `${name(clue.person)} был ${DIR[clue.kind]} ${personGenitive(name(clue.person2))}`;
    case 'same_room':     return `${name(clue.person)} и ${name(clue.person2)} были в одной комнате`;
    case 'not_same_room': return `${name(clue.person)} и ${name(clue.person2)} были в разных комнатах`;
    case 'room_count': {
      const op = OPS[clue.op];
      if (!op) throw new Error('Unknown op: ' + clue.op);
      return `В комнате_${clue.room} было ${op} ${clue.count} ${d1Noun(clue.count, clue.op)}`;
    }
    case 'no_empty_rooms': return 'Пустых комнат не было';
    default: throw new Error('Unknown clue kind: ' + clue.kind);
  }
}

/**
 * Render a clue LIST for display, merging runs of same-person adjacent /
 * not_adjacent clues into one sentence: «X был рядом со столом и с креслом».
 * Merging is visual only (the clue list itself is untouched); a run is
 * consecutive same-kind + same-person clues in the given order, everything
 * else renders via clueToText one line per clue.
 * @param {object[]} clues clue dicts (SPEC §4 format)
 * @param {Map<string, {id: string, name: string}>} peopleMap
 * @returns {string[]} one string per displayed line, order preserved
 */
export function clueListToTexts(clues, peopleMap) {
  const out = [];
  let i = 0;
  while (i < clues.length) {
    const clue = clues[i];
    if (clue.kind === 'adjacent' || clue.kind === 'not_adjacent') {
      const group = [clue];
      let j = i + 1;
      while (j < clues.length && clues[j].kind === clue.kind
             && clues[j].person === clue.person) {
        group.push(clues[j]);
        j++;
      }
      if (group.length > 1) {
        const verb = clue.kind === 'adjacent' ? 'был рядом' : 'был не рядом';
        const objects = group.map((c) => objForms(c.object_type).instr);
        out.push(`${personName(peopleMap, clue.person)} ${verb} ${objects.join(' и ')}`);
        i = j;
        continue;
      }
    }
    out.push(clueToText(clue, peopleMap));
    i++;
  }
  return out;
}
