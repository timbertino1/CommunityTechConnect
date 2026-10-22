// The home page's decorative header map (T153; research R15, design direction B): a tilted
// outline of Nebraska with a faint dot grid, small points for towns, and pulsing scarlet pins at
// upcoming events' cities. The only module that imports three.js. Loaded by home.js after the
// page has loaded; the canvas is aria-hidden, and the page works fully without it.

import {
  AdditiveBlending,
  AmbientLight,
  BufferGeometry,
  CylinderGeometry,
  DirectionalLight,
  DoubleSide,
  EdgesGeometry,
  ExtrudeGeometry,
  Float32BufferAttribute,
  Group,
  LineBasicMaterial,
  LineSegments,
  Mesh,
  MeshBasicMaterial,
  MeshStandardMaterial,
  PerspectiveCamera,
  Points,
  PointsMaterial,
  RingGeometry,
  Scene,
  Shape,
  SphereGeometry,
  Vector2,
  WebGLRenderer,
} from "/vendor/three.js";

// Nebraska's outline (lon, lat), simplified; the Missouri River on the east.
const OUTLINE = [
  [-104.05, 43.0], [-98.5, 43.0], [-98.1, 42.84], [-97.4, 42.86], [-96.9, 42.75], [-96.6, 42.5],
  [-96.44, 42.49], [-96.3, 42.2], [-96.1, 41.8], [-96.05, 41.5], [-95.92, 41.27], [-95.86, 41.0],
  [-95.76, 40.6], [-95.31, 40.0], [-102.05, 40.0], [-102.05, 41.0], [-104.05, 41.0],
];
const SCARLET = 0xff5c5c;
const CREAM = 0xf2eee6;
// Half the state's width in scene units, plus room for the sway and the tilt's perspective.
const MAP_HALF_WIDTH = 4.3;
// The static image is mostly map: drawn larger than the live header's.
const CENTERED_SCALE = 1.3;
// Behind the copy on wide screens (as in the design mockup), and centered in its own row.
const RIGHT_SCALE = 1.0;
const RIGHT_Y = 0.1;
const CENTER_SCALE = 1.15;

// Longitude is scaled by about cos(41.5°) so the state keeps its shape.
function xy(lon, lat) {
  return [(lon + 99.7) * 0.76, lat - 41.5];
}

function inside([x, y], poly) {
  let hit = false;
  for (let i = 0, j = poly.length - 1; i < poly.length; j = i++) {
    const [ax, ay] = poly[i];
    const [bx, by] = poly[j];
    if (ay > y !== by > y && x < ((bx - ax) * (y - ay)) / (by - ay) + ax) hit = !hit;
  }
  return hit;
}

function points(coords, size, opacity) {
  const geometry = new BufferGeometry();
  geometry.setAttribute("position", new Float32BufferAttribute(coords, 3));
  return new Points(geometry, new PointsMaterial({ color: CREAM, size, transparent: true, opacity }));
}

function pin(x, y) {
  const node = new Group();
  node.position.set(x, y, 0.15);
  const glow = { color: SCARLET, transparent: true, blending: AdditiveBlending, depthWrite: false };
  const dot = new Mesh(new SphereGeometry(0.055, 20, 16), new MeshBasicMaterial({ color: SCARLET }));
  dot.position.z = 0.06;
  const beam = new Mesh(
    new CylinderGeometry(0.008, 0.008, 1.1, 8),
    new MeshBasicMaterial({ ...glow, opacity: 0.45 }),
  );
  beam.rotation.x = Math.PI / 2;
  beam.position.z = 0.6;
  const ring = new Mesh(
    new RingGeometry(0.06, 0.085, 48),
    new MeshBasicMaterial({ ...glow, opacity: 0.8, side: DoubleSide }),
  );
  ring.position.z = 0.01;
  node.add(dot, beam, ring);
  return { node, ring };
}

/**
 * Draw the map on `canvas` from /data/map.json's `towns` and `pins`.
 * Options: `animate` (false: one still frame, no animation loop); `centered` (the map fills the
 * canvas, for the static image) and `capture` (keep the frame readable by toDataURL).
 * Throws when WebGL is unavailable. Returns `stop()`.
 */
export function start(canvas, data, { animate = true, centered = false, capture = false } = {}) {
  const renderer = new WebGLRenderer({
    canvas,
    antialias: true,
    alpha: true,
    preserveDrawingBuffer: capture,
  });
  renderer.setPixelRatio(Math.min(window.devicePixelRatio || 1, 2));

  const scene = new Scene();
  const camera = new PerspectiveCamera(32, 1, 0.1, 100);
  camera.position.set(0, 0, 10);
  scene.add(new AmbientLight(0xffffff, 0.55));
  const sun = new DirectionalLight(0xffffff, 0.7);
  sun.position.set(-3, -4, 6);
  scene.add(sun);

  const map = new Group();
  map.rotation.x = -0.95;
  scene.add(map);

  const outline = OUTLINE.map(([lon, lat]) => xy(lon, lat));
  const slab = new ExtrudeGeometry(new Shape(outline.map(([x, y]) => new Vector2(x, y))), {
    depth: 0.14,
    bevelEnabled: false,
  });
  map.add(new Mesh(slab, new MeshStandardMaterial({ color: 0x1f1c1a, roughness: 0.9, metalness: 0.05 })));
  map.add(
    new LineSegments(
      new EdgesGeometry(slab),
      new LineBasicMaterial({ color: SCARLET, transparent: true, opacity: 0.6 }),
    ),
  );

  const grid = [];
  for (let gx = -3.4; gx <= 3.4; gx += 0.105) {
    for (let gy = -1.55; gy <= 1.55; gy += 0.105) {
      if (inside([gx, gy], outline)) grid.push(gx, gy, 0.145);
    }
  }
  map.add(points(grid, 0.022, 0.22));
  map.add(points(data.towns.flatMap((t) => [...xy(t.lon, t.lat), 0.16]), 0.06, 0.85));

  const pins = data.pins.map((p, i) => {
    const made = pin(...xy(p.lon, p.lat));
    map.add(made.node);
    return { ring: made.ring, phase: i / data.pins.length };
  });

  const state = { frame: 0, visible: true, t0: performance.now() };

  function layout() {
    const w = canvas.clientWidth || 1;
    const h = canvas.clientHeight || 1;
    renderer.setSize(w, h, false);
    camera.aspect = w / h;
    camera.updateProjectionMatrix();
    if (centered) {
      map.position.set(0, 0, 0);
      map.scale.setScalar(CENTERED_SCALE);
      return;
    }
    // The stylesheet says where the map goes (--map-align): "right", behind the copy on wide
    // screens, shifted only as far as keeps its east edge (and the sway) in view; or "center",
    // in its own row. The visible half-width at the map's depth sets both.
    const halfView = Math.tan((camera.fov * Math.PI) / 360) * camera.position.z * camera.aspect;
    const right = getComputedStyle(canvas).getPropertyValue("--map-align").trim() === "right";
    const scale = Math.min(right ? RIGHT_SCALE : CENTER_SCALE, halfView / MAP_HALF_WIDTH);
    const x = right ? Math.min(2.0, Math.max(0, halfView - MAP_HALF_WIDTH * scale)) : 0;
    map.position.set(x, right ? RIGHT_Y : 0, 0);
    map.scale.setScalar(scale);
  }

  function draw(now) {
    const t = (now - state.t0) / 1000;
    if (animate) {
      map.rotation.z = Math.sin(t * 0.12) * 0.22;
      map.rotation.y = Math.sin(t * 0.09) * 0.06;
      for (const p of pins) {
        const k = (t * 0.45 + p.phase) % 1;
        p.ring.scale.setScalar(1 + k * 3.2);
        p.ring.material.opacity = 0.8 * (1 - k);
      }
    } else {
      map.rotation.z = -0.12;
      for (const p of pins) {
        p.ring.scale.setScalar(2.2);
        p.ring.material.opacity = 0.35;
      }
    }
    renderer.render(scene, camera);
  }

  function loop(now) {
    state.frame = 0;
    draw(now);
    if (animate && state.visible) state.frame = requestAnimationFrame(loop);
  }

  const resize = new ResizeObserver(() => {
    layout();
    draw(performance.now());
  });
  resize.observe(canvas);
  // Paused while scrolled out of view.
  const seen = new IntersectionObserver(([entry]) => {
    state.visible = entry.isIntersecting;
    if (state.visible && animate && !state.frame) state.frame = requestAnimationFrame(loop);
  });
  seen.observe(canvas);

  layout();
  draw(performance.now());
  if (animate) state.frame = requestAnimationFrame(loop);

  return {
    stop() {
      if (state.frame) cancelAnimationFrame(state.frame);
      resize.disconnect();
      seen.disconnect();
      renderer.dispose();
    },
  };
}
