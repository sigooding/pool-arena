// The printable marker sheet.
//
// The bit patterns are baked in rather than generated, which matters more
// than it sounds: printing the markers is the first thing a new user does,
// and it would be perverse to require OpenCV — a few gigabytes of computer
// vision — before they can print four squares. Drawn as SVG so they stay
// crisp at any size and any printer.
//
// Patterns are ArUco DICT_4X4_50 ids 0-3, including the one-bit black
// border, taken straight from OpenCV so the detector recognises them.

const PATTERNS = {
  0: [[0,0,0,0,0,0],[0,1,0,1,1,0],[0,0,1,0,1,0],[0,0,0,1,1,0],[0,0,0,1,0,0],[0,0,0,0,0,0]],
  1: [[0,0,0,0,0,0],[0,0,0,0,0,0],[0,1,1,1,1,0],[0,1,0,0,1,0],[0,1,0,1,0,0],[0,0,0,0,0,0]],
  2: [[0,0,0,0,0,0],[0,0,0,1,1,0],[0,0,0,1,1,0],[0,0,0,1,0,0],[0,1,1,0,1,0],[0,0,0,0,0,0]],
  3: [[0,0,0,0,0,0],[0,1,0,0,1,0],[0,1,0,0,1,0],[0,0,1,0,0,0],[0,0,1,1,0,0],[0,0,0,0,0,0]],
};

const NAMES = { 0: 'top-left', 1: 'top-right', 2: 'bottom-right', 3: 'bottom-left' };

//: White border around the marker, as a fraction of it. ArUco needs a quiet
//: zone to find the outer black edge; on paper that is just margin.
const QUIET = 0.25;

function markerSvg(id, sizeMm) {
  const bits = PATTERNS[id];
  const n = bits.length;
  const quiet = sizeMm * QUIET;
  const total = sizeMm + quiet * 2;
  const cell = sizeMm / n;
  const svg = document.createElementNS('http://www.w3.org/2000/svg', 'svg');
  svg.setAttribute('width', `${total}mm`);
  svg.setAttribute('height', `${total}mm`);
  svg.setAttribute('viewBox', `0 0 ${total} ${total}`);
  svg.setAttribute('shape-rendering', 'crispEdges');

  const bg = document.createElementNS(svg.namespaceURI, 'rect');
  bg.setAttribute('width', total);
  bg.setAttribute('height', total);
  bg.setAttribute('fill', '#fff');
  svg.appendChild(bg);

  for (let r = 0; r < n; r++) {
    for (let c = 0; c < n; c++) {
      if (bits[r][c]) continue;              // 0 is black in these patterns
      const rect = document.createElementNS(svg.namespaceURI, 'rect');
      rect.setAttribute('x', quiet + c * cell);
      rect.setAttribute('y', quiet + r * cell);
      // a hair of overlap, or printers leave white seams between cells
      rect.setAttribute('width', cell + 0.02);
      rect.setAttribute('height', cell + 0.02);
      rect.setAttribute('fill', '#000');
      svg.appendChild(rect);
    }
  }
  return svg;
}

function render(sizeMm) {
  const sheet = document.getElementById('sheet');
  sheet.textContent = '';
  for (const id of [0, 1, 2, 3]) {
    const wrap = document.createElement('div');
    wrap.className = 'marker';
    wrap.appendChild(markerSvg(id, sizeMm));
    const label = document.createElement('div');
    label.className = 'who';
    label.textContent = `${id} · ${NAMES[id]} · ${sizeMm} mm`;
    wrap.appendChild(label);
    sheet.appendChild(wrap);
  }
}

document.getElementById('size').onchange = (e) => render(Number(e.target.value));
document.getElementById('print').onclick = () => window.print();
render(Number(document.getElementById('size').value));
