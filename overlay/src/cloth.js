// Projected colour, adapted to the cloth it lands on.
//
// A projector adds light to a surface that then reflects it selectively, so
// the colour a player sees is the projected colour MULTIPLIED by the cloth's
// reflectance. Red on green cloth is nearly invisible — the cloth absorbs red
// — while the same red on pale blue is merely dull. A palette that works on
// one table can be unreadable on another.
//
// The palettes below were chosen by computing, for each candidate, the CIE76
// distance in Lab between the lit patch and the unlit cloth beside it, then
// greedily picking colours that are far from the cloth AND far from each
// other. Contrast with the cloth alone is not enough: on blue cloth a
// projected blue scores highly but reads as "the cloth got brighter", and two
// such colours cannot be told apart.
//
// The surprise from that exercise: pale cloth is a BETTER projection surface
// for colour than tournament green, because a desaturated surface reflects
// broadly and renders hues faithfully. What it loses is black level — unlit
// pale blue sits around L* 34 against green's 16, so "off" is never dark and
// ambient light matters far more.

const DEFAULT_CLOTH = '#1B6E54';

let cloth = DEFAULT_CLOTH;
let clothLin = null;
let unlitLab = null;
let family = 'green';
const adapted = new Map();

// --- colour maths ---------------------------------------------------------
function hexToRgb(h) {
  const s = String(h).replace('#', '');
  const n = s.length === 3 ? s.split('').map((c) => c + c).join('') : s;
  return [parseInt(n.slice(0, 2), 16), parseInt(n.slice(2, 4), 16),
          parseInt(n.slice(4, 6), 16)];
}

const toHex = (rgb) =>
  '#' + rgb.map((v) => Math.max(0, Math.min(255, Math.round(v)))
    .toString(16).padStart(2, '0')).join('').toUpperCase();

const srgbToLin = (rgb) => rgb.map((c) => {
  const x = c / 255;
  return x <= 0.04045 ? x / 12.92 : Math.pow((x + 0.055) / 1.055, 2.4);
});

function linToLab(lin) {
  const [r, g, b] = lin;
  const x = (0.4124 * r + 0.3576 * g + 0.1805 * b) / 0.95047;
  const y = (0.2126 * r + 0.7152 * g + 0.0722 * b) / 1.0;
  const z = (0.0193 * r + 0.1192 * g + 0.9505 * b) / 1.08883;
  const f = (t) => (t > 0.008856 ? Math.cbrt(t) : 7.787 * t + 16 / 116);
  const [fx, fy, fz] = [f(x), f(y), f(z)];
  return [116 * fy - 16, 500 * (fx - fy), 200 * (fy - fz)];
}

const dist = (a, b) => Math.hypot(a[0] - b[0], a[1] - b[1], a[2] - b[2]);

/** How a projected colour actually looks once the cloth has reflected it. */
function rendered(hex, ambient = 0.18) {
  const p = srgbToLin(hexToRgb(hex));
  return linToLab(clothLin.map((c, i) => Math.min(1, c * (ambient + p[i]))));
}

/** CIE76 separation between a projected colour and the bare cloth. */
export function separation(hex) {
  return dist(rendered(hex), unlitLab);
}

// --- palettes -------------------------------------------------------------
// Two families, each computed for its cloth. Keys match what the games ask
// for by name, so a game never needs to know what colour the table is.
const FAMILIES = {
  green: {
    fire:     ['#FFF3B0', '#FFB703', '#FB8500', '#E63946'],
    gold:     ['#FFFBE6', '#FFE066', '#FFC300', '#FF8F00'],
    electric: ['#E0FBFC', '#90E0EF', '#00B4D8', '#0077B6'],
    neon:     ['#F72585', '#B5179E', '#7209B7', '#4361EE'],
    mint:     ['#D8F3DC', '#95D5B2', '#52B788', '#2D6A4F'],
    rainbow:  ['#FF006E', '#FB5607', '#FFBE0B', '#8338EC', '#3A86FF', '#06D6A0'],
    ash:      ['#ADB5BD', '#6C757D', '#495057'],
    key:      '#A3E635',   // best separation on green
    alt:      '#FF00FF',
    warn:     '#FF2D55',
    good:     '#A3E635',
  },
  blue: {
    // Reds and oranges are the weak end on blue cloth, so the warm palettes
    // lean amber rather than scarlet, and magenta does the work red would.
    fire:     ['#FFF0B0', '#FFB200', '#FF8A00', '#FF0080'],
    gold:     ['#FFFBE6', '#FFD24A', '#FFB200', '#FF8A00'],
    electric: ['#CCFFF4', '#00FFCC', '#00D2FF', '#409FFF'],
    neon:     ['#FF00FF', '#FF0080', '#B026FF', '#409FFF'],
    mint:     ['#D7FFE9', '#7CFFB2', '#00FF80', '#00C853'],
    rainbow:  ['#FF00FF', '#FFB200', '#00FF00', '#00FFCC', '#409FFF', '#FF0080'],
    ash:      ['#C4CBD2', '#8A939B', '#5B646C'],
    key:      '#00FF00',   // best separation on pale blue, by a long way
    alt:      '#FF00FF',
    warn:     '#FF0080',   // scarlet is absorbed; rose is not
    good:     '#00FF00',
  },
};

export function setCloth(hex) {
  cloth = hex || DEFAULT_CLOTH;
  clothLin = srgbToLin(hexToRgb(cloth));
  unlitLab = linToLab(clothLin.map((c) => Math.min(1, c * 0.18)));
  // Which family: anything from cyan through violet counts as "blue cloth",
  // and so does a pale neutral, where the same broad-reflectance argument
  // applies.
  const [r, g, b] = hexToRgb(cloth);
  const max = Math.max(r, g, b), min = Math.min(r, g, b);
  const sat = max ? (max - min) / max : 0;
  family = (b >= g && sat > 0.08) || sat <= 0.08 ? 'blue' : 'green';
  adapted.clear();
  return family;
}

export const palette = (name) =>
  FAMILIES[family][name] || FAMILIES[family].fire;

export const semantic = (name) => FAMILIES[family][name];
export const clothFamily = () => family;
export const clothColour = () => cloth;

// The colours the rule sets actually send, mapped per cloth family. These
// carry meaning — alarm, target, the black, a zone — so they are decided
// here rather than left to the generic nudge below, which knows about
// visibility but nothing about what a colour is for.
//
// The notable one is alarm. On green cloth red is almost perfectly absorbed
// (separation under 5, which is invisible), and rotating it by the smallest
// amount that works lands on amber — the colour already used for whose turn
// it is. Magenta costs the same rotation and keeps alarm distinct, so alarm
// is magenta on green and stays red on blue, where red works fine.
const SEMANTIC = {
  green: {
    // Green cloth reflects almost no red, so NO hue can look like an alarm on
    // it — magenta comes back as navy. The brightest thing available is a
    // near-white, and the meaning is carried by the strobe (table_flash
    // pulses) rather than by the colour.
    '#dc2626': '#FFFFFF', '#ef4444': '#FFFFFF', '#ff2d55': '#FFFFFF',
    '#f87171': '#FFD9F0', '#fb7185': '#FFD9F0',
    '#f472b6': '#F172F4', '#a78bfa': '#C77DFF',
    '#38bdf8': '#38EDF8', '#60a5fa': '#5CE1FF', '#22d3ee': '#24E2FF',
    '#0b5fd8': '#00D2FF',
    '#4ade80': '#A3E635', '#34d399': '#7CFF9E',
    '#f2b705': '#FFC300', '#ffc24a': '#FFD24A', '#f59e0b': '#FFB200',
    '#fb923c': '#FFB200', '#64748b': '#AEB7C2',
  },
  blue: {
    // Pale blue reflects broadly, so almost everything survives unchanged.
    // Only the washed-out mid-blues need help, because they sit on the
    // cloth's own hue and read as the cloth simply getting brighter.
    '#38bdf8': '#00FFCC', '#60a5fa': '#00E0FF', '#0b5fd8': '#409FFF',
    '#a78bfa': '#B026FF', '#64748b': '#C4CBD2',
    '#ef4444': '#FF0040', '#ff2d55': '#FF0080',
  },
};

/**
 * Nudge a colour until it is actually visible on this cloth.
 *
 * Games name their own colours, and those were chosen against green. Rather
 * than override them — which would throw away the meaning a game attached to
 * a colour — this keeps the hue and lifts saturation and value until the
 * rendered separation clears a floor. Only if that fails does it rotate the
 * hue away from the cloth's own.
 */
export function adapt(hex, floor = 26) {
  if (!hex || !clothLin) return hex;
  if (adapted.has(hex)) return adapted.get(hex);
  const known = SEMANTIC[family][String(hex).toLowerCase()];
  if (known) { adapted.set(hex, known); return known; }
  let out = hex;
  if (separation(hex) < floor) {
    const [h, s, v] = rgbToHsv(hexToRgb(hex));
    // Try the smallest change that works, not the biggest improvement. Hue
    // carries meaning — a foul flash has to stay alarming — so saturation and
    // value are spent first and rotation is capped at 45 degrees. Red on
    // green cloth therefore lands on magenta or orange, never on green.
    const tries = [];
    for (const dh of [0, 15, -15, 30, -30, 45, -45]) {
      for (const ds of [0, 0.2, 0.4]) {
        for (const dv of [0, 0.15, 0.3]) {
          tries.push([Math.abs(dh) / 45 + ds + dv, dh, ds, dv]);
        }
      }
    }
    // Score every candidate, then take the least-changed one that clears the
    // floor, breaking ties on separation. The tie-break matters: red on green
    // can rotate to amber or to magenta at equal cost, and amber would
    // collide with the gold already used for "your turn".
    const scored = tries.map(([cost, dh, ds, dv]) => {
      const cand = toHex(hsvToRgb((h + dh + 360) % 360,
                                  Math.min(1, s + ds), Math.min(1, v + dv)));
      return { cost, cand, sep: separation(cand) };
    });
    const ok = scored.filter((c) => c.sep >= floor);
    if (ok.length) {
      const cheapest = Math.min(...ok.map((c) => c.cost));
      out = ok.filter((c) => c.cost <= cheapest + 1e-6)
              .sort((a, b) => b.sep - a.sep)[0].cand;
    } else {
      out = scored.sort((a, b) => b.sep - a.sep)[0].cand;
    }
  }
  adapted.set(hex, out);
  return out;
}

function rgbToHsv([r, g, b]) {
  r /= 255; g /= 255; b /= 255;
  const max = Math.max(r, g, b), min = Math.min(r, g, b), d = max - min;
  let h = 0;
  if (d) {
    if (max === r) h = ((g - b) / d) % 6;
    else if (max === g) h = (b - r) / d + 2;
    else h = (r - g) / d + 4;
    h *= 60;
  }
  return [(h + 360) % 360, max ? d / max : 0, max];
}

function hsvToRgb(h, s, v) {
  const c = v * s, x = c * (1 - Math.abs(((h / 60) % 2) - 1)), m = v - c;
  const t = [[c, x, 0], [x, c, 0], [0, c, x], [0, x, c], [x, 0, c], [c, 0, x]];
  const [r, g, b] = t[Math.floor(h / 60) % 6];
  return [(r + m) * 255, (g + m) * 255, (b + m) * 255];
}

setCloth(DEFAULT_CLOTH);
