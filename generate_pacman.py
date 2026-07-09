import os
import random
import requests
from datetime import datetime, timedelta, date
from collections import deque

# ── Config ───────────────────────────────────────────────────────────────────
USERNAME = os.environ.get("GITHUB_USERNAME", "PROTOX11")
TOKEN    = os.environ.get("GITHUB_TOKEN", "")

COLS = 53; ROWS = 7; CELL = 11; GAP = 3; STEP = CELL + GAP
PAD_LEFT = 32; PAD_TOP = 28
W = PAD_LEFT + COLS * STEP + 6
H = PAD_TOP  + ROWS * STEP + 10

COLORS_DARK  = ["#161b22","#00ff7f","#00e650","#00cc2e","#39ff14"]
COLORS_LIGHT = ["#ebedf0","#85e89d","#34d058","#28a745","#00cc2e"]

# ── 20-second encounter cycle timeline ───────────────────────────────────────
#   0% – 62%  : PM2 travels to angel; PM1 bounces trapped; angel bobs normally
#   62% – 70% : PM2 arrives — both PM2 + angel slowly scale up 1 → 2.5
#   70% – 77% : PM2 gets eaten (scale 2.5 → 0, opacity 0)
#   77% – 85% : Angel → Devil transform; scales back down 2.5 → 1
#   85% – 96% : Devil visible and bobbing
#   96% – 100%: Reset — devil → angel, PM2 reappears at start (invisible → visible)
CYCLE = 20  # seconds

def to_level(count):
    if count == 0: return 0
    if count < 10: return 1
    if count < 20: return 2
    if count < 30: return 3
    return 4

# ── Fetch contributions ───────────────────────────────────────────────────────
def fetch_contributions():
    """Returns (grid 7×53, month_cols list of (label, col_index))."""
    if not TOKEN:
        print("No GITHUB_TOKEN — using empty grid fallback")
        return [[0] * COLS for _ in range(ROWS)], []

    end   = datetime.utcnow()
    start = end - timedelta(weeks=53)
    query = """
    query($login: String!, $from: DateTime!, $to: DateTime!) {
      user(login: $login) {
        contributionsCollection(from: $from, to: $to) {
          contributionCalendar {
            weeks {
              firstDay
              contributionDays { weekday date contributionCount }
            }
          }
        }
      }
    }
    """
    variables = {"login": USERNAME,
                 "from": start.strftime("%Y-%m-%dT00:00:00Z"),
                 "to":   end.strftime("%Y-%m-%dT23:59:59Z")}
    headers = {"Authorization": f"bearer {TOKEN}", "Content-Type": "application/json"}
    resp = requests.post("https://api.github.com/graphql",
                         json={"query": query, "variables": variables},
                         headers=headers, timeout=15)
    resp.raise_for_status()
    data  = resp.json()
    weeks = data["data"]["user"]["contributionsCollection"]["contributionCalendar"]["weeks"]

    raw = [[0] * COLS for _ in range(ROWS)]
    for col_idx, week in enumerate(weeks[:COLS]):
        for day in week["contributionDays"]:
            row_idx = day["weekday"]
            if row_idx < ROWS and col_idx < COLS:
                raw[row_idx][col_idx] = day["contributionCount"]

    grid = [[to_level(raw[r][c]) for c in range(COLS)] for r in range(ROWS)]

    month_cols = []
    seen = set()
    for col_idx, week in enumerate(weeks[:COLS]):
        fds = week.get("firstDay", "")
        if not fds:
            continue
        d   = date.fromisoformat(fds)
        key = (d.year, d.month)
        if key not in seen:
            seen.add(key)
            month_cols.append((d.strftime("%b"), col_idx))

    return grid, month_cols

# ── Grid helpers ──────────────────────────────────────────────────────────────
def cell_cx(c): return PAD_LEFT + c * STEP + CELL // 2
def cell_cy(r): return PAD_TOP  + r * STEP + CELL // 2

def make_is_open(grid):
    """Any cell with a commit (level >= 1) is a solid wall."""
    def fn(c, r):
        if c < 0 or c >= COLS or r < 0 or r >= ROWS:
            return False
        return grid[r][c] < 1
    return fn

# ── BFS: largest connected open component ────────────────────────────────────
def largest_component(is_open):
    open_cells = [(c, r) for r in range(ROWS) for c in range(COLS) if is_open(c, r)]
    visited = set()
    best    = []
    DIRS    = [(1,0),(-1,0),(0,1),(0,-1)]
    for seed in open_cells:
        if seed in visited:
            continue
        comp = []
        q    = deque([seed])
        seen = {seed}
        while q:
            cell = q.popleft()
            comp.append(cell)
            cc, cr = cell
            for dc, dr in DIRS:
                nb = (cc+dc, cr+dr)
                if nb not in seen and is_open(nb[0], nb[1]):
                    seen.add(nb)
                    q.append(nb)
        visited |= seen
        if len(comp) > len(best):
            best = comp
    return sorted(best)

# ── Natural biased random walk toward target (no BFS) ───────────────────────
def generate_natural_path(start, target, is_open, length=280, seed=42):
    """
    Natural-looking Pac-Man navigation:
    - 70% greedy: prefer direction that reduces distance to target
    - 30% explore: random direction (causes detours, mini-backtracks)
    - When stuck (all neighbours visited): backtrack 3-6 steps and retry
    This gives the look of Pac-Man genuinely searching the maze.
    """
    random.seed(seed)
    tc, tr      = target
    path        = [start]
    cur         = start
    window      = []      # recent cells to avoid tight loops
    stuck_count = 0
    DIRS        = [(1, 0), (-1, 0), (0, 1), (0, -1)]

    for _ in range(length * 30):
        if len(path) >= length or cur == target:
            break

        cc, cr = cur
        open_dirs = [(dc, dr) for dc, dr in DIRS if is_open(cc+dc, cr+dr)]
        if not open_dirs:
            break  # completely walled in

        # Sort by Manhattan distance to target (ascending = toward angel)
        open_dirs.sort(key=lambda d: abs(cc+d[0]-tc) + abs(cr+d[1]-tr))

        # Fresh = not in recent window (avoids tight circles)
        fresh = [(dc, dr) for dc, dr in open_dirs
                 if (cc+dc, cr+dr) not in window[-14:]]

        if fresh:
            if random.random() < 0.70:
                dc, dr = fresh[0]                              # greedy step
            else:
                dc, dr = random.choice(fresh[:min(2, len(fresh))])  # explore
            stuck_count = 0
        else:
            # All neighbours recently visited — backtrack naturally
            stuck_count += 1
            if stuck_count >= 3 and len(path) > 6:
                back_steps = random.randint(3, 6)
                for _ in range(back_steps):
                    if len(path) > 1:
                        path.pop()
                cur         = path[-1]
                window      = window[:-back_steps] if len(window) >= back_steps else []
                stuck_count = 0
                continue
            dc, dr = random.choice(open_dirs)  # forced random move

        nc, nr = cc+dc, cr+dr
        path.append((nc, nr))
        window.append((nc, nr))
        if len(window) > 35:
            window.pop(0)
        cur = (nc, nr)

    return path if len(path) > 1 else [start, start]

# ── Find nearest open cell to a target ───────────────────────────────────────
def nearest_open(target, is_open):
    if is_open(target[0], target[1]):
        return target
    visited = {target}
    q       = deque([target])
    DIRS    = [(1,0),(-1,0),(0,1),(0,-1)]
    while q:
        c, r = q.popleft()
        for dc, dr in DIRS:
            nc, nr = c+dc, r+dr
            if (nc, nr) not in visited:
                if is_open(nc, nr):
                    return (nc, nr)
                visited.add((nc, nr))
                if 0 <= nc < COLS and 0 <= nr < ROWS:
                    q.append((nc, nr))
    return target

# ── PM1: trapped random walk bounded to left columns ─────────────────────────
def generate_trapped_path(start, is_open, max_col=6, length=70, seed=7):
    """Bounce around in columns 0..max_col — looks like trapped in a pocket."""
    random.seed(seed)
    path   = [start]
    cur    = start
    window = []
    DIRS   = [(1,0),(-1,0),(0,1),(0,-1)]
    for _ in range(length * 20):
        if len(path) >= length:
            break
        cands = [(dc,dr) for dc,dr in DIRS
                 if is_open(cur[0]+dc, cur[1]+dr)
                 and cur[0]+dc <= max_col
                 and (cur[0]+dc, cur[1]+dr) not in window[-10:]]
        if not cands:
            cands = [(dc,dr) for dc,dr in DIRS
                     if is_open(cur[0]+dc, cur[1]+dr)
                     and cur[0]+dc <= max_col]
        if not cands:
            break
        dc, dr = random.choice(cands)
        nc, nr = cur[0]+dc, cur[1]+dr
        path.append((nc, nr))
        window.append((nc, nr))
        if len(window) > 25:
            window.pop(0)
        cur = (nc, nr)
    if len(path) < 2:
        path.append(start)
    return path + path[-2::-1]  # ping-pong

# ── Keyframe builder: PM1 ping-pong ──────────────────────────────────────────
def build_pm1_keyframes(path):
    n = len(path)
    if n < 2:
        return "@keyframes pm1move {}"
    lines = ["@keyframes pm1move {"]
    for i, (c, r) in enumerate(path):
        pct = round(i / (n-1) * 100, 3)
        x, y = cell_cx(c), cell_cy(r)
        if i < n-1:
            nc, nr = path[i+1]; dx, dy = nc-c, nr-r
        else:
            dx, dy = -1, 0
        angle = 0 if dx>0 else 180 if dx<0 else 90 if dy>0 else 270
        lines.append(f"  {pct}% {{ transform: translate({x}px,{y}px) rotate({angle}deg); }}")
    lines.append("}")
    return "\n".join(lines)

# ── Keyframe builder: PM2 encounter movement ──────────────────────────────────
def build_pm2_move_keyframes(path_to_angel):
    """
    PM2 travels start→angel over 0%–62% of cycle,
    pauses at angel 62%–90% (encounter happens there),
    then teleports back to start invisible at 90.01%.
    """
    n = len(path_to_angel)
    lines = ["@keyframes pm2move {"]
    for i, (c, r) in enumerate(path_to_angel):
        pct = round(i / max(n-1, 1) * 62, 3)
        x, y = cell_cx(c), cell_cy(r)
        if i < n-1:
            nc, nr = path_to_angel[i+1]; dx, dy = nc-c, nr-r
        else:
            dx, dy = 1, 0
        angle = 0 if dx>0 else 180 if dx<0 else 90 if dy>0 else 270
        lines.append(f"  {pct}% {{ transform: translate({x}px,{y}px) rotate({angle}deg); }}")
    lc, lr = path_to_angel[-1]
    lx, ly = cell_cx(lc), cell_cy(lr)
    lines.append(f"  62.1% {{ transform: translate({lx}px,{ly}px) rotate(0deg); }}")
    lines.append(f"  90%   {{ transform: translate({lx}px,{ly}px) rotate(0deg); }}")
    fc, fr = path_to_angel[0]
    fx, fy = cell_cx(fc), cell_cy(fr)
    lines.append(f"  90.01% {{ transform: translate({fx}px,{fy}px) rotate(0deg); }}")
    lines.append(f"  100%   {{ transform: translate({fx}px,{fy}px) rotate(0deg); }}")
    lines.append("}")
    return "\n".join(lines)

# ── SVG shape: Pac-Man with AI text ──────────────────────────────────────────
def pacman_svg(fill, chomp_dur=0.5, chomp_begin="0s", bg="#0d1117"):
    return f"""  <circle cx="0" cy="0" r="6" fill="{fill}"/>
  <path fill="{bg}">
    <animate attributeName="d"
      values="M 0 0 L 6 -4.4 A 6 6 0 1 1 6 4.4 Z;M 0 0 L 6 -0.5 A 6 6 0 0 1 6 0.5 Z;M 0 0 L 6 -4.4 A 6 6 0 1 1 6 4.4 Z"
      dur="{chomp_dur}s" begin="{chomp_begin}" repeatCount="indefinite"/>
  </path>
  <text x="-6.5" y="4" font-size="12" font-weight="900" fill="#ffffff"
        stroke="{bg}" stroke-width="1.5" paint-order="stroke fill"
        font-family="sans-serif">AI</text>"""

# ── SVG shape: Angel (white halo + wings + robe + kind face) ─────────────────
def angel_svg():
    return """
  <!-- Halo -->
  <ellipse cx="0" cy="-9" rx="4.5" ry="1.5" fill="none" stroke="#FFD700" stroke-width="1.4"/>
  <!-- Wings -->
  <path d="M -3 -2 C -8 -5 -10 0 -5 2 Z" fill="#ddefff" opacity="0.92"/>
  <path d="M  3 -2 C  8 -5  10 0  5 2 Z" fill="#ddefff" opacity="0.92"/>
  <!-- Robe -->
  <path d="M -3.5 7 L 0 -2 L 3.5 7 Z" fill="#c4e0ff"/>
  <!-- Head -->
  <circle cx="0" cy="-4" r="3" fill="#FFE0BD"/>
  <!-- Eyes (kind, closed/smiling) -->
  <path d="M -1.2 -4.4 Q -0.6 -5 0 -4.4" fill="none" stroke="#9a6748" stroke-width="0.6"/>
  <path d="M  1.2 -4.4 Q  0.6 -5 0 -4.4" fill="none" stroke="#9a6748" stroke-width="0.6"/>
  <!-- Smile -->
  <path d="M -1.2 -3.2 Q 0 -2.2 1.2 -3.2" fill="none" stroke="#c0856a" stroke-width="0.5"/>"""

# ── SVG shape: Devil (horns + bat-wings + red body + evil face + tail) ───────
def devil_svg():
    return """
  <!-- Horns -->
  <path d="M -2.8 -7 L -1.8 -11 L 0 -7.5 Z" fill="#CC0000"/>
  <path d="M  2.8 -7 L  1.8 -11 L 0 -7.5 Z" fill="#CC0000"/>
  <!-- Bat wings -->
  <path d="M -3.5 -1 C -9 -5 -11 1 -5 3 Q -8 3 -4.5 4 Z" fill="#880000" opacity="0.95"/>
  <path d="M  3.5 -1 C  9 -5  11 1  5 3 Q  8 3  4.5 4 Z" fill="#880000" opacity="0.95"/>
  <!-- Robe (red) -->
  <path d="M -3.5 7 L 0 -2 L 3.5 7 Z" fill="#CC1100"/>
  <!-- Head (red skin) -->
  <circle cx="0" cy="-4" r="3" fill="#FF3322"/>
  <!-- Evil eyes (glowing yellow) -->
  <ellipse cx="-1" cy="-4.3" rx="0.7" ry="0.65" fill="#FFD700"/>
  <ellipse cx=" 1" cy="-4.3" rx="0.7" ry="0.65" fill="#FFD700"/>
  <!-- Slit pupils -->
  <ellipse cx="-1" cy="-4.2" rx="0.3" ry="0.55" fill="#000"/>
  <ellipse cx=" 1" cy="-4.2" rx="0.3" ry="0.55" fill="#000"/>
  <!-- Fangs -->
  <polygon points="-0.8,-2.8 -0.5,-1.5 -0.2,-2.8" fill="#ffffff"/>
  <polygon points=" 0.8,-2.8  0.5,-1.5  0.2,-2.8" fill="#ffffff"/>
  <!-- Devil tail -->
  <path d="M 1 6 Q 5 9 4 12 Q 3 13.5 5.5 12.5 L 7 14" fill="none" stroke="#CC0000"
        stroke-width="1.4" stroke-linecap="round" stroke-linejoin="round"/>"""

# ── Build SVG ─────────────────────────────────────────────────────────────────
def build_svg(grid, month_cols, path1, path2, angel_pos,
              dur1, kf1, kf2,
              colors, bg, text_color, dark_mode=True):

    ax, ay = cell_cx(angel_pos[0]), cell_cy(angel_pos[1])
    p1x0,  p1y0  = cell_cx(path1[0][0]), cell_cy(path1[0][1])

    # ── CSS keyframes ──────────────────────────────────────────────────────────
    # PM2 encounter: opacity + scale (applied on inner child, outer handles movement)
    pm2_enc = """
@keyframes pm2enc {
  0%, 61%   { opacity: 1; transform: scale(1);   }
  70%       { opacity: 1; transform: scale(2.6);  }
  77%       { opacity: 0; transform: scale(0.05); }
  90%       { opacity: 0; transform: scale(0.05); }
  96%       { opacity: 1; transform: scale(1);    }
  100%      { opacity: 1; transform: scale(1);    }
}"""

    # Angel/Devil container: scale (scales from center of the group)
    angel_scale = f"""
@keyframes angelscale {{
  0%, 61%   {{ transform: scale(1);   }}
  70%       {{ transform: scale(2.6); }}
  84%       {{ transform: scale(1);   }}
  100%      {{ transform: scale(1);   }}
}}"""

    # Angel visibility: visible 0–70%, fades out 70–77%, gone until 96%
    angel_vis = """
@keyframes angelviz {
  0%, 61%   { opacity: 1; }
  70%       { opacity: 1; }
  77%       { opacity: 0; }
  96%       { opacity: 0; }
  100%      { opacity: 1; }
}"""

    # Devil visibility: hidden until 70%, fades in 70–77%, stays until 96%
    devil_vis = """
@keyframes devilviz {
  0%, 70%   { opacity: 0; }
  77%       { opacity: 1; }
  96%       { opacity: 1; }
  100%      { opacity: 0; }
}"""

    # Angel gentle bob: small translateY up/down (runs on the inner shape)
    angel_bob = """
@keyframes angelbob {
  0%, 100% { transform: translateY(0px);  }
  50%      { transform: translateY(-3px); }
}"""

    # ── Build SVG output ───────────────────────────────────────────────────────
    L = []
    L.append(f'<svg xmlns="http://www.w3.org/2000/svg" width="{W}" height="{H}" viewBox="0 0 {W} {H}">')
    L.append(f'<rect width="{W}" height="{H}" fill="{bg}" rx="6"/>')

    glow_def = ""
    if dark_mode:
        glow_def = """
  <filter id="glow" x="-30%" y="-30%" width="160%" height="160%">
    <feGaussianBlur in="SourceGraphic" stdDeviation="1.8" result="blur"/>
    <feMerge>
      <feMergeNode in="blur"/>
      <feMergeNode in="SourceGraphic"/>
    </feMerge>
  </filter>"""
    L.append(f"<defs>{glow_def}</defs>")

    L.append("<style>")
    L.append(kf1)
    L.append(kf2)
    L.append(pm2_enc)
    L.append(angel_scale)
    L.append(angel_vis)
    L.append(devil_vis)
    L.append(angel_bob)
    L.append(f"""
.pm1 {{
  animation: pm1move {dur1}s linear infinite;
  transform: translate({p1x0}px,{p1y0}px);
}}
.pm2-mover {{
  animation: pm2move {CYCLE}s linear infinite;
  transform: translate({cell_cx(path2[0][0])}px,{cell_cy(path2[0][1])}px);
}}
.pm2-scale {{
  animation: pm2enc {CYCLE}s ease-in-out infinite;
  transform-box: fill-box;
  transform-origin: center;
}}
.angel-encounter {{
  animation: angelscale {CYCLE}s ease-in-out infinite;
  transform-box: fill-box;
  transform-origin: center;
}}
.angel-body {{
  animation: angelviz {CYCLE}s ease-in-out infinite,
             angelbob 2.2s ease-in-out infinite;
}}
.devil-body {{
  animation: devilviz {CYCLE}s ease-in-out infinite;
  opacity: 0;
}}""")
    L.append("</style>")

    # ── Contribution grid ──────────────────────────────────────────────────────
    glow_attr = ' filter="url(#glow)"' if dark_mode else ''
    for r in range(ROWS):
        for c in range(COLS):
            x     = PAD_LEFT + c * STEP
            y     = PAD_TOP  + r * STEP
            level = grid[r][c]
            color = colors[level]
            ga    = glow_attr if (dark_mode and level > 0) else ''
            L.append(f'<rect x="{x}" y="{y}" width="{CELL}" height="{CELL}" rx="2" fill="{color}"{ga}/>')

    # ── Month labels ───────────────────────────────────────────────────────────
    prev_x = -99
    for label, col_idx in month_cols:
        x = PAD_LEFT + col_idx * STEP
        if x - prev_x < 20:
            continue
        L.append(f'<text x="{x}" y="20" font-size="9" fill="{text_color}" '
                 f'font-family="-apple-system,BlinkMacSystemFont,\'Segoe UI\',Helvetica,Arial,sans-serif">'
                 f'{label}</text>')
        prev_x = x

    # ── PM1: yellow, trapped bouncing in left pocket ───────────────────────────
    L.append(f'<g class="pm1">')
    L.append(pacman_svg("#FFD700", chomp_dur=0.45, bg=bg))
    L.append('</g>')

    # ── PM2: red neon, travels to angel, then encounter ────────────────────────
    L.append('<g class="pm2-mover">')
    L.append('  <g class="pm2-scale">')
    L.append(f'    {pacman_svg("#FF2222", chomp_dur=0.55, chomp_begin="0.15s", bg=bg)}')
    L.append('  </g>')
    L.append('</g>')

    # ── Angel / Devil at fixed position ───────────────────────────────────────
    # Outer <g> uses SVG transform attribute to position at (ax,ay).
    # Inner .angel-encounter handles the scale animation from that center.
    L.append(f'<g transform="translate({ax},{ay})">')
    L.append('  <g class="angel-encounter">')
    L.append('    <g class="angel-body">')
    L.append(angel_svg())
    L.append('    </g>')
    L.append('    <g class="devil-body">')
    L.append(devil_svg())
    L.append('    </g>')
    L.append('  </g>')
    L.append('</g>')

    L.append("</svg>")
    return "\n".join(L)


# ── Main ──────────────────────────────────────────────────────────────────────
def main():
    print(f"Fetching contributions for {USERNAME}...")
    grid, month_cols = fetch_contributions()

    is_open = make_is_open(grid)
    reach   = largest_component(is_open)
    print(f"Open cells: {len(reach)}")

    if len(reach) < 4:
        print("WARNING: very few open cells — grid may be very dense")
        # Emergency fallback: treat ALL cells as open
        is_open = lambda c, r: (0 <= c < COLS and 0 <= r < ROWS)
        reach   = [(c, r) for r in range(ROWS) for c in range(COLS)]

    left_cells  = sorted(reach, key=lambda cell: (cell[0], cell[1]))
    right_cells = sorted(reach, key=lambda cell: (-cell[0], cell[1]))

    # ── PM1: trapped in left pocket (columns 0 .. max_col_pm1) ────────────────
    p1_start    = left_cells[0]
    max_col_pm1 = min(7, COLS // 7)   # stays in left ~1/7 of the board
    path1 = generate_trapped_path(p1_start, is_open, max_col=max_col_pm1, length=70, seed=7)
    dur1  = round(len(path1) * 0.30, 1)

    # ── Angel: stand at the rightmost open cell ────────────────────────────────
    angel_cell = right_cells[0]

    # ── PM2: natural biased walk from start toward angel ─────────────────────
    p2_start   = left_cells[min(6, len(left_cells) - 1)]
    angel_open = nearest_open(angel_cell, is_open)
    path2      = generate_natural_path(p2_start, angel_open, is_open, length=280, seed=42)
    if len(path2) < 2:
        path2 = [p2_start, angel_open]

    print(f"PM1 path: {len(path1)} steps (trapped in cols 0-{max_col_pm1})")
    print(f"PM2 path: {len(path2)} steps (natural walk to angel at {angel_cell})")

    kf1 = build_pm1_keyframes(path1)
    kf2 = build_pm2_move_keyframes(path2)

    common = dict(
        grid=grid, month_cols=month_cols,
        path1=path1, path2=path2, angel_pos=angel_open,
        dur1=dur1, kf1=kf1, kf2=kf2,
    )

    dark_svg  = build_svg(**common, colors=COLORS_DARK,  bg="#0d1117", text_color="#8b949e", dark_mode=True)
    light_svg = build_svg(**common, colors=COLORS_LIGHT, bg="#ffffff",  text_color="#57606a", dark_mode=False)

    dark_file  = "pacman-contribution-dark.svg"
    light_file = "pacman-contribution-light.svg"

    with open(dark_file,  "w", encoding="utf-8") as f:
        f.write(dark_svg)
    with open(light_file, "w", encoding="utf-8") as f:
        f.write(light_svg)

    print(f"Written {dark_file}  ({len(dark_svg):,} bytes)")
    print(f"Written {light_file} ({len(light_svg):,} bytes)")
    print()
    print("=" * 60)
    print("Paste this into your README.md:")
    print("=" * 60)
    print(f"""
<picture>
  <source media="(prefers-color-scheme: dark)"  srcset="{dark_file}">
  <source media="(prefers-color-scheme: light)" srcset="{light_file}">
  <img alt="Pac-Man contribution graph" src="{dark_file}" width="100%">
</picture>
""")


if __name__ == "__main__":
    main()
