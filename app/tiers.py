"""Course depths. Sessions are all-in study time: practice and a written exercise are inside each one.

Sources for the shape: retrieval practice and spacing (Dunlosky et al. 2013, Adesope et al. 2017, Cepeda et al.
2008), short chunks (Guo et al. 2014), worked examples fading with expertise (Sweller, Renkl, Kalyuga), shorter
courses finished more often (Jordan 2014). Chunk sizes and reading-list counts are judgment.
"""
from __future__ import annotations

TIERS: dict[str, dict] = {
    "dive": {
        "label": "Cursory Dive",
        "blurb": "The big picture: core vocabulary, the central ideas, why they matter and where to go next.",
        "lessons": 6,
        "minutes": 45,
        "chunks": 3,
        "checks_per_chunk": 1,
        "practice": 3,
        "reading": 5,
        "depth": "Breadth only. One session per big idea, conceptual rather than technical, no prerequisites assumed. "
                 "Practice checks understanding of ideas more than skill.",
    },
    "bootcamp": {
        "label": "Boot Camp",
        "blurb": "A working skill: the core of the subject with plenty of practice and one small project.",
        "lessons": 12,
        "minutes": 50,
        "chunks": 3,
        "checks_per_chunk": 2,
        "practice": 5,
        "reading": 8,
        "depth": "The core syllabus at 'can use it' depth. Worked examples early, fading quickly to independent "
                 "practice. Minimal prerequisites, stated plainly.",
    },
    "quarter": {
        "label": "Quarter",
        "blurb": "The syllabus of a university quarter course: sub-topics, the deeper why, harder problems and a capstone.",
        "lessons": 22,
        "minutes": 60,
        "chunks": 4,
        "checks_per_chunk": 2,
        "practice": 6,
        "reading": 12,
        "depth": "A full introductory university course: sub-topics, proofs or the deeper why, edge cases, and one or "
                 "two advanced topics near the end. Harder problems, worked examples fading fast. State prerequisites.",
    },
}

DEFAULT = "bootcamp"


def skeleton(tier: str) -> list[dict]:
    """The session slots for a tier, in order: kind and minutes. The plan fills in titles and topics."""
    t = TIERS[tier]
    m = t["minutes"]
    lessons = lambda n: [{"kind": "lesson", "minutes": m} for _ in range(n)]
    if tier == "dive":
        slots = lessons(6) + [{"kind": "wrapup", "minutes": m}]
    elif tier == "bootcamp":
        slots = lessons(6) + [{"kind": "checkpoint", "minutes": m}] + lessons(6) + [{"kind": "project", "minutes": 2 * m}]
    else:
        slots = (lessons(6) + [{"kind": "review", "minutes": m}] + lessons(5) + [{"kind": "checkpoint", "minutes": m}]
                 + lessons(5) + [{"kind": "review", "minutes": m}] + lessons(6) + [{"kind": "project", "minutes": 2 * m}])
    for i, s in enumerate(slots, 1):
        s["slot"] = i
    return slots


def public() -> list[dict]:
    out = []
    for key, t in TIERS.items():
        slots = skeleton(key)
        total = sum(s["minutes"] for s in slots)
        out.append({"key": key, "label": t["label"], "blurb": t["blurb"], "sessions": len(slots),
                    "lessons": t["lessons"], "minutes": t["minutes"], "hours": round(total / 60),
                    "weeks": round(len(slots) / 2)})
    return out


KIND_LABEL = {"lesson": "Lesson", "review": "Review", "checkpoint": "Put it together", "project": "Project",
              "wrapup": "Wrap-up"}
