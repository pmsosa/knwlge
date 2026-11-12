"""Made-up demo courses for screenshots and trying the UI without a Gemini key.

    docker run --rm -e KNWLGE_DATA=/demo -v <scratch>:/demo knwlge python -m app.demo
    docker run --rm -e KNWLGE_DATA=/demo -v <scratch>:/demo knwlge python -m app.demo --team

`--team` also makes three made-up accounts for team mode (run the app with KNWLGE_MODE=team), with demo-only passwords:
maya (admin, owns the courses), sam (author) and kim (learner). The finished courses are published.

Writes straight into a fresh data folder (refuses one that already has courses). Everything in it is invented.
"""
from __future__ import annotations

import datetime as dt
import sys

from . import audit, auth, db, learning, pipeline
from .tiers import skeleton


def lesson(title: str, idea: str, maths: bool = False) -> dict:
    eq = " The relationship is $f = \\frac{v}{\\lambda}$, where $v$ is the speed of sound and $\\lambda$ the wavelength." if maths else ""
    return {
        "goal": f"What is {idea.lower()}, and why does it matter?",
        "hook": f"Once you see {idea.lower()}, you'll start noticing it everywhere.",
        "chunks": [
            {"title": f"{idea}: the core idea",
             "markdown": f"Every sound is a vibration travelling through the air.{eq}\n\n"
                         "Think of a guitar string: pluck it and it swings back and forth hundreds of times a second. "
                         "Each swing pushes on the air, sending out a ripple of **compressions** and **rarefactions**.",
             "example_markdown": "A string vibrating 440 times a second makes the note A4.\n\n"
                                 "$$\\lambda = \\frac{v}{f} = \\frac{343\\,\\text{m/s}}{440\\,\\text{Hz}} \\approx 0.78\\,\\text{m}$$",
             "checks": [{"id": "c1", "type": "mcq", "prompt": "What does a vibrating string push on to make sound?",
                         "options": ["The air around it", "The light around it", "Only the guitar body"],
                         "answer": "The air around it", "explanation": "Sound is a pressure wave in the air.", "tolerance": 0,
                         "topic": "sound waves"}]},
            {"title": "Pitch and frequency",
             "markdown": "How high or low a note sounds (its **pitch**) follows how fast it vibrates (its **frequency**, in hertz). "
                         "Double the frequency and you hear the same note an **octave** higher.",
             "example_markdown": "A3 is 220 Hz, A4 is 440 Hz, A5 is 880 Hz: each step doubles.",
             "checks": [{"id": "c2", "type": "numeric", "prompt": "A4 is 440 Hz. What is A5, one octave up, in Hz?",
                         "options": [], "answer": "880", "explanation": "An octave doubles the frequency.", "tolerance": 0,
                         "topic": "octaves"}]},
            {"title": "Why instruments sound different",
             "markdown": "A piano and a violin playing the same note share a frequency but not a **timbre**. Each instrument "
                         "adds its own mix of quieter, higher vibrations called **overtones**.",
             "example_markdown": "Play A4 on a flute and on a trumpet: the 440 Hz part is the same, but the trumpet adds "
                                 "strong overtones at 880, 1320 and 1760 Hz.",
             "checks": [{"id": "c3", "type": "mcq", "prompt": "What makes a trumpet and a flute sound different on the same note?",
                         "options": ["Their overtones (timbre)", "Their frequency", "How loud they are"],
                         "answer": "Their overtones (timbre)", "explanation": "Timbre comes from the mix of overtones.",
                         "tolerance": 0, "topic": "timbre"}]},
        ],
        "practice": [
            {"id": "p1", "type": "mcq", "prompt": "If a string vibrates faster, the pitch goes…", "options": ["Up", "Down", "Stays the same"],
             "answer": "Up", "explanation": "Higher frequency, higher pitch.", "tolerance": 0, "topic": "pitch"},
            {"id": "p2", "type": "numeric", "prompt": "A note is 330 Hz. What is the note one octave **below**, in Hz?",
             "options": [], "answer": "165", "explanation": "Halve it.", "tolerance": 0, "topic": "octaves"},
            {"id": "p3", "type": "short", "prompt": "In a sentence: why can you hear a friend talking around a corner?",
             "options": [], "answer": "Sound waves bend (diffract) around obstacles.", "explanation": "Long wavelengths diffract.",
             "tolerance": 0, "topic": "diffraction"},
        ],
        "exercises": [{"title": "Explain it to a friend",
                       "prompt": f"Explain {idea.lower()} to a friend who has never studied physics, using one everyday example.",
                       "rubric": [{"criterion": "Accurate", "points": 3, "description": "The physics is right."},
                                  {"criterion": "Clear example", "points": 2, "description": "The example really shows the idea."}],
                       "model_answer": "Sound is the air being pushed back and forth…"}],
        "wrapup": {"key_points": ["Sound is a vibration travelling through the air.", "Frequency sets the pitch; doubling it is an octave.",
                                  "Overtones give each instrument its timbre."], "teaser": "Next: why some notes sound good together."},
        "reading": [{"kind": "video", "title": "What is sound?", "creator": "Demo Science Channel", "url": "https://www.youtube.com/watch?v=demo000001",
                     "isbn": "", "year": "2021", "level": "beginner", "minutes": 9, "why": "Great slow-motion footage of vibrating strings.",
                     "free": True, "top": False}],
    }


def project() -> dict:
    return {"goal": "Build and explain a simple instrument.", "intro_markdown": "Time to make something with what you've learned.",
            "tips_markdown": "- Measure lengths carefully.\n- Record yourself and compare.",
            "options": [{"title": "A straw pan flute", "brief_markdown": "Cut 6 straws to lengths that play a scale and explain why.",
                         "deliverable": "A photo and a paragraph", "rubric": [{"criterion": "Works", "points": 5, "description": "It plays"},
                                                                               {"criterion": "Explained", "points": 5, "description": "The physics is clear"}],
                         "model_answer": "Shorter tubes resonate at higher frequencies…"},
                        {"title": "A rubber-band guitar", "brief_markdown": "Build a box guitar and tune it to an octave.",
                         "deliverable": "A photo and a paragraph", "rubric": [{"criterion": "Works", "points": 5, "description": "It plays"}],
                         "model_answer": "Tension and thickness set pitch…"}], "reading": []}


TITLES = ["Vibrations and waves", "Pitch and frequency", "Loudness and decibels", "Harmonics and overtones", "Resonance",
          "Intervals and consonance", "Put it together", "Scales and tuning", "Strings", "Wind instruments", "Percussion",
          "Rooms and acoustics", "Recording and the ear", "Project: make an instrument"]


def make(c, subject: str, title: str, depth: str, summary: str, done: int, attempts: bool) -> str:
    cid = pipeline._course_id(subject)
    now = db.now()
    slots = skeleton(depth)
    titles = (TITLES * 3)[: len(slots)]
    plan = {"title": title, "summary": summary, "prerequisites": ["Basic arithmetic"] if depth != "dive" else [],
            "readiness": {"teaching": "High", "feedback": "Medium-high", "weak_spots": ["Can't hear you play: uploads only"],
                          "safety_note": ""},
            "sessions": [{"slot": s["slot"], "kind": s["kind"], "title": titles[i] if s["kind"] != "project" else TITLES[-1],
                          "topics": ["waves", "frequency", "examples"], "objectives": ["You'll be able to explain it simply."]}
                         for i, s in enumerate(slots)]}
    c.execute("INSERT INTO courses(id, subject, notes, depth, title, summary, status, plan_json, answers_json, created_at, updated_at, published_at) "
              "VALUES (?,?,?,?,?,?,?,?,?,?,?,?)", (cid, subject, "", depth, title, summary, "ready", db.dumps(plan), "{}", now, now, now))
    db.course_dir(cid).mkdir(parents=True, exist_ok=True)
    for slot, s in zip(slots, plan["sessions"]):
        sid = f"{cid}-s{slot['slot']:02d}"
        c.execute("INSERT INTO sessions(id, course_id, seq, kind, title, topics_json, objectives_json, minutes, state) VALUES (?,?,?,?,?,?,?,?,?)",
                  (sid, cid, slot["slot"], slot["kind"], s["title"], db.dumps(s["topics"]), db.dumps(s["objectives"]), slot["minutes"], "ready"))
        content = project() if slot["kind"] == "project" else lesson(s["title"], s["title"], maths=slot["slot"] == 1)
        pipeline.store_session(c, sid, slot["kind"], content)
        if slot["slot"] <= done:
            c.execute("INSERT INTO session_progress(user_id, session_id, started_at, done_at, summary_note) VALUES (?,?,?,?,?)",
                      (db.OWNER_ID, sid, now, now, "Sound is vibration; frequency sets pitch."))
    c.execute("UPDATE reading SET status='verified', verify_note='Demo' WHERE course_id=?", (cid,))
    for r in [("book", "Strings and Air: A Listener's Guide (demo)", "A. Example", True, False), ("video", "The Science of Sound (demo series)", "Demo Science Channel", False, True),
              ("course", "Fundamentals of Music Theory (demo)", "An Open University", False, True), ("article", "How do instruments work? (demo)", "Demo Encyclopedia", False, True),
              ("podcast", "Sound Matters (demo)", "Demo Radio", False, True)]:
        c.execute("INSERT INTO reading(course_id, kind, title, creator, url, level, minutes, why, free, top, status) VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                  (cid, r[0], r[1], r[2], "https://example.org/demo", "beginner", 240 if r[0] == "book" else 30,
                   "A friendly, thorough companion to the course.", 1 if r[4] else 0, 1 if r[3] else 0, "verified"))
    if attempts:
        demo_media(c, cid, f"{cid}-s01")
        first = c.execute("SELECT * FROM items WHERE session_id=? ORDER BY seq", (f"{cid}-s01",)).fetchall()
        for it in first:
            if it["qtype"] in ("mcq", "numeric"):
                learning.attempt(c, it["id"], it["answer"] if it["seq"] != 2 else "800")
        ex = next(i for i in first if i["qtype"] == "long")
        cur = c.execute("INSERT INTO attempts(item_id, course_id, created_at, answer, status, score, feedback_json) VALUES (?,?,?,?,?,?,?)",
                        (ex["id"], cid, now, "Sound is the air being squeezed and stretched, like a slinky…", "marked", 0.8,
                         db.dumps({"lines": [{"criterion": "Accurate", "points": 3, "awarded": 3, "comment": "Spot on: compressions and rarefactions."},
                                             {"criterion": "Clear example", "points": 2, "awarded": 1, "comment": "The slinky works; say what moves."}],
                                   "overall": "A clear, friendly explanation. The slinky is a great picture.", "revisit": ["Longitudinal waves"],
                                   "score": 0.8, "level": "Solid"})))
        c.execute("UPDATE jobs SET status='cancelled' WHERE kind='mark'")
        _ = cur
    return cid


def _png(width: int = 720, height: int = 300) -> bytes:
    """A made-up 'photo' for the demo: a sine wave on paper, drawn without any imaging library."""
    import math
    import struct
    import zlib
    rows = []
    for y in range(height):
        row = bytearray([0])
        for x in range(width):
            wave = height / 2 + math.sin(x / 38) * 90 * math.exp(-x / 900)
            d = abs(y - wave)
            if d < 3:
                row += bytes((93, 140, 215))
            elif abs(y - height / 2) < 1:
                row += bytes((193, 193, 192))
            else:
                row += bytes((252, 252, 249))
        rows.append(bytes(row))
    raw = zlib.compress(b"".join(rows), 9)
    chunk = lambda t, d: struct.pack(">I", len(d)) + t + d + struct.pack(">I", zlib.crc32(t + d) & 0xffffffff)
    return b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0)) + chunk(b"IDAT", raw) + chunk(b"IEND", b"")


def _wav(freq: float = 440.0, seconds: float = 2.0) -> bytes:
    import io
    import math
    import struct
    import wave
    rate = 22050
    buf = io.BytesIO()
    with wave.open(buf, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(rate)
        frames = b"".join(struct.pack("<h", int(12000 * math.sin(2 * math.pi * freq * i / rate) * min(1, (seconds * rate - i) / 2000)))
                          for i in range(int(seconds * rate)))
        w.writeframes(frames)
    return buf.getvalue()


SVG = """<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 640 220" font-family="sans-serif" font-size="14">
<line x1="20" y1="110" x2="620" y2="110" stroke="#c1c1c0" stroke-width="1"/>
<path d="M20 110 C 70 20, 120 20, 170 110 S 270 200, 320 110 S 420 20, 470 110 S 570 200, 620 110" fill="none" stroke="#181818" stroke-width="3"/>
<line x1="95" y1="42" x2="395" y2="42" stroke="#5d8cd7" stroke-width="2"/><text x="215" y="34" fill="#5d8cd7">one wavelength (λ)</text>
<line x1="570" y1="110" x2="570" y2="180" stroke="#5d8cd7" stroke-width="2"/><text x="578" y="150" fill="#5d8cd7">amplitude</text>
</svg>"""

EXPERIMENT = """<!doctype html><html><body style="margin:0;font-family:sans-serif;background:#fcfcf9;color:#181818">
<canvas id="c" width="600" height="300" style="width:100%;height:330px;display:block"></canvas>
<div style="padding:6px 10px;font-size:13px">String length <input id="len" type="range" min="40" max="140" value="100">
<span id="out"></span> · Shorter strings swing faster: higher pitch.</div>
<script>
const c=document.getElementById('c'),g=c.getContext('2d'),len=document.getElementById('len'),out=document.getElementById('out');let t=0;
function draw(){const L=+len.value,f=1.6*Math.sqrt(100/L);out.textContent=(220*f).toFixed(0)+' Hz';g.fillStyle='#fcfcf9';g.fillRect(0,0,600,300);
const a=Math.sin(t*f)*0.6,x=300+Math.sin(a)*L*2,y=20+Math.cos(a)*L*2;g.strokeStyle='#181818';g.lineWidth=3;g.beginPath();g.moveTo(300,20);g.lineTo(x,y);g.stroke();
g.fillStyle='#5d8cd7';g.beginPath();g.arc(x,y,16,0,7);g.fill();t+=0.05;requestAnimationFrame(draw)}draw();
</script></body></html>"""


def demo_media(c, course_id: str, session_id: str) -> None:
    folder = db.course_dir(course_id) / "media"
    folder.mkdir(parents=True, exist_ok=True)
    rows = [
        (0, "mermaid", "How a plucked string becomes a sound you hear.",
         {"code": "flowchart LR\n  A[Pluck the string] --> B[String vibrates]\n  B --> C[Air pressure waves]\n  C --> D[Eardrum moves]\n  D --> E[You hear a note]"},
         None, None, ""),
        (0, "image", "A decaying vibration: big swings at first, fading as energy leaks away.", {}, "png", _png(),
         "Demo picture · made for this demo"),
        (0, "audio", "A4: 440 vibrations a second. Listen for one steady pitch.", {}, "wav", _wav(), "Demo recording · a generated tone"),
        (1, "svg", "Wavelength and amplitude on one wave.", {}, "svg", SVG.encode(), ""),
        (1, "widget", "Drag the sliders: a changes loudness (amplitude), k changes pitch (frequency).",
         {"type": "plot", "expression": "a*sin(k*x)", "x_min": -6.3, "x_max": 6.3, "y_min": -3, "y_max": 3,
          "params": [{"name": "a", "min": 0.2, "max": 3, "step": 0.1, "value": 1}, {"name": "k", "min": 0.5, "max": 4, "step": 0.1, "value": 1}]},
         None, None, ""),
        (2, "experiment", "Change the string length and watch how fast it swings.", {}, "html", EXPERIMENT.encode(), ""),
        (2, "widget", "Quick recall before you move on.",
         {"type": "flashcards", "cards": [{"front": "What sets a note's pitch?", "back": "Its frequency: how many vibrations per second."},
                                          {"front": "What is an octave?", "back": "A doubling of frequency."},
                                          {"front": "What gives an instrument its timbre?", "back": "Its mix of overtones."}]},
         None, None, ""),
    ]
    for k, (chunk, kind, caption, spec, ext, data, credit) in enumerate(rows):
        mid = f"{session_id}-m{chunk + 1}{k}"
        rel = None
        mime = {"png": "image/png", "wav": "audio/wav", "svg": "image/svg+xml", "html": "text/html"}.get(ext or "")
        if data:
            rel = f"media/{mid}.{ext}"
            (folder / f"{mid}.{ext}").write_bytes(data)
        c.execute("INSERT INTO media(id, course_id, session_id, chunk, seq, kind, caption, spec_json, status, file, mime, credit) "
                  "VALUES (?,?,?,?,?,?,?,?,?,?,?,?)", (mid, course_id, session_id, chunk, k, kind, caption, db.dumps(spec), "ready",
                                                       rel, mime, credit))
    s2 = session_id.replace("-s01", "-s02")
    c.execute("INSERT INTO media(id, course_id, session_id, chunk, seq, kind, caption, spec_json, status) VALUES (?,?,?,?,?,?,?,?,?)",
              (f"{s2}-m10", course_id, s2, 0, 0, "widget", "Some famous moments in the science of sound.",
               db.dumps({"type": "timeline", "events": [
                   {"date": "c. 500 BC", "label": "Pythagoras and string lengths", "detail": "Halving a string's length gives the octave."},
                   {"date": "1636", "label": "Mersenne's laws", "detail": "How length, tension and mass set a string's pitch."},
                   {"date": "1822", "label": "Fourier's series", "detail": "Any periodic sound is a sum of sine waves."},
                   {"date": "1863", "label": "Helmholtz on tone", "detail": "Overtones explain timbre."}]}), "ready"))


# demo-only accounts (never use these anywhere real)
DEMO_PEOPLE = [("maya", "Maya Lindqvist", "admin", "demo-maya-password"),
               ("sam", "Sam Okafor", "author", "demo-sam-password"),
               ("kim", "Kim Arden", "learner", "demo-kim-password")]


def demo_team(c) -> None:
    """Made-up people for team mode: the owner becomes Maya (admin); Sam writes, Kim learns."""
    name, display, _, pw = DEMO_PEOPLE[0]
    c.execute("UPDATE users SET username=?, display_name=?, role='admin' WHERE id=?", (name, display, db.OWNER_ID))
    auth.set_password(c, db.OWNER_ID, pw, must_change=False)
    for uname, display, role, pw in DEMO_PEOPLE[1:]:
        uid, _ = auth.create_user(c, uname, display, role, pw)
        auth.set_password(c, uid, pw, must_change=False)
    c.execute("UPDATE courses SET author_id=?, visibility='published', published_at=? WHERE status!='review'", (db.OWNER_ID, db.now()))
    c.execute("UPDATE courses SET author_id=?, visibility='draft' WHERE status='review'", (db.OWNER_ID,))
    # a little made-up history for the audit page
    ids = {u: r["id"] for u, r in ((u, c.execute("SELECT id FROM users WHERE username=?", (u,)).fetchone()) for u, *_ in DEMO_PEOPLE)}
    music = c.execute("SELECT id FROM courses WHERE title LIKE '%Music%'").fetchone()["id"]
    for who, action, ttype, tid, details in [
            ("maya", "user.created", "user", str(ids["sam"]), {"username": "sam", "role": "author"}),
            ("maya", "user.created", "user", str(ids["kim"]), {"username": "kim", "role": "learner"}),
            ("maya", "course.published", "course", music, {}),
            ("sam", "auth.signin", "", "", {}),
            ("maya", "session.chunk_revise_asked", "session", f"{music}-s02", {"chunk": 0, "mode": "rewrite", "wish": "simpler words"}),
            ("kim", "auth.signin", "", "", {})]:
        audit.log(c, action, ttype, tid, details, user_id=ids[who])


def main() -> None:
    db.init()
    with db.tx() as c:
        if c.execute("SELECT count(*) AS n FROM courses").fetchone()["n"]:
            sys.exit("This data folder already has courses; use an empty one for the demo.")
        a = make(c, "The physics of music", "The Physics of Music", "bootcamp",
                 "Why a guitar string sings, why some notes sound good together, and how rooms shape what you hear.", 3, True)
        make(c, "Castles of medieval Europe", "Castles: How Medieval Fortresses Worked", "dive",
             "A tour of how castles were designed, built, defended and lived in, from motte-and-bailey to the age of cannon.", 1, False)
        q = make(c, "Introduction to astronomy", "Astronomy: From Backyard to Big Bang", "quarter",
                 "A full introductory astronomy course: the sky, light and telescopes, planets, stars, galaxies and cosmology.", 0, False)
        c.execute("UPDATE sessions SET state='writing' WHERE course_id=? AND seq > 9", (q,))
        c.execute("UPDATE courses SET status='building' WHERE id=?", (q,))
        ago = lambda **kw: (dt.datetime.now(dt.timezone.utc) - dt.timedelta(**kw)).replace(microsecond=0).isoformat().replace("+00:00", "Z")
        for cid_, at in ((q, ago(days=2)), (a, db.now())):
            c.execute("INSERT OR REPLACE INTO course_opens(user_id, course_id, at) VALUES (?,?,?)", (db.OWNER_ID, cid_, at))
        jazz = [("How jazz began", "New Orleans, brass bands, blues and ragtime"), ("The swing era", "Big bands, dance halls, the soloist"),
                ("Bebop", "Speed, harmony and the small group"), ("Cool, modal and hard bop", "Three answers to bebop"),
                ("Free jazz and fusion", "Breaking the rules, plugging in"), ("Jazz today", "Hip hop, global jazz and where to listen"),
                ("Wrap-up: your jazz map", "Putting the century together")]
        jp = {"title": "Jazz: A Listener's History", "summary": "A guided listening tour of a century of jazz: where each style came "
              "from, what to listen for, and the records that changed everything.", "prerequisites": [],
              "readiness": {"teaching": "Medium-high", "feedback": "Medium", "weak_spots": [
                  "A text course can't play you the music: each session links recordings to listen to.",
                  "Feedback on your listening notes is about ideas, not your ear."], "safety_note": ""},
              "sessions": [{"slot": i, "kind": slot["kind"], "minutes": slot["minutes"], "title": t, "topics": [x.strip() for x in tp.split(",")],
                            "objectives": ["You'll be able to recognise the style and say where it came from."]}
                           for i, ((t, tp), slot) in enumerate(zip(jazz, skeleton("dive")), 1)]}
        c.execute("INSERT INTO courses(id, subject, notes, depth, title, summary, status, plan_json, answers_json, created_at, updated_at) "
                  "VALUES (?,?,?,?,?,?,?,?,?,?,?)", ("history-of-jazz-demo01", "History of jazz", "", "dive",
                  jp["title"], jp["summary"], "review", db.dumps(jp), "{}", db.now(), db.now()))
        c.execute("INSERT INTO course_opens(user_id, course_id, at) VALUES (?,?,?)", (db.OWNER_ID, "history-of-jazz-demo01", ago(hours=3)))
        db.set_setting(c, "gemini_api_key", "demo-key-not-real")
        for kind, cost in [("plan", 0.06), ("session", 0.41), ("check", 0.03), ("reading", 0.05), ("mark", 0.02)]:
            c.execute("INSERT INTO llm_calls(course_id, kind, model, input_tokens, output_tokens, cost_usd, outcome, at) VALUES (?,?,?,?,?,?,?,?)",
                      (a, kind, "gemini-3.8-flash", 40000, 12000, cost, "ok", db.now()))
        if "--team" in sys.argv[1:]:
            demo_team(c)
    print("demo data written" + (" (with team accounts: " + ", ".join(f"{u} / {p}" for u, _, _, p in DEMO_PEOPLE) + ")"
                                 if "--team" in sys.argv[1:] else ""))


if __name__ == "__main__":
    main()
