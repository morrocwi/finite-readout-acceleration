"""
experiments.py — does Finite Readout Acceleration actually buy anything on WEB work?

The paper's benchmark is a synthetic trig score on [0,1]^2. That is a proof of
mechanism, not an engineering answer. These experiments ask the questions an
engineer actually has to answer before shipping it:

  E1  What is c_o really, on this machine, for a real key? -> the break-even table.
  E2  Is the win about COST, or about the function being continuum-heavy?
      (the paper's counterexample changes both variables at once -- confounded)
  E3  Does the error certificate survive being measured by MAX instead of MEAN?
  E4  On an ARAYA-shaped request trace: how much collapses, and does the
      key-safety linter catch an unsafe key before it ships?
  E5  On RAG / vector retrieval: query-embedding quotient, scored by RECALL
      (the actual readout) rather than by coordinate error.
  E6  Does the online break-even guard survive a distribution shift?

All traces are synthetic and labelled as such. Timings are wall-clock medians on
this machine; they demonstrate a cost mechanism, not a portable coefficient.
"""

from __future__ import annotations

import math
import random
import statistics
import sys
from fractions import Fraction

import numpy as np

from fra import (
    BreakEvenGuard,
    Certificate,
    CostModel,
    FiniteReadoutAccelerator,
    audit_key_safety,
    empirical_lipschitz,
    lipschitz_delta,
    timed,
)

SEED = 20260730
rng = random.Random(SEED)
nprng = np.random.default_rng(SEED)

RULE = "=" * 78
def head(t: str) -> None:
    print(f"\n{RULE}\n{t}\n{RULE}")


# ---------------------------------------------------------------------------
# E1 - measure c_o for real, then build the break-even table
# ---------------------------------------------------------------------------

def e1_break_even_table() -> CostModel:
    head("E1  What does the quotient overhead c_o actually cost? -> break-even table")

    # A realistic web readout key: a tuple of small values, hashed into a dict.
    trace = [
        (rng.randrange(77), rng.randrange(2), rng.randrange(12), rng.randrange(400))
        for _ in range(200_000)
    ]
    cache = {t: i for i, t in enumerate(set(trace))}

    def build_and_lookup():
        acc = 0
        for prov, lang, svc, day in trace:
            k = (prov, lang, svc, day)      # key construction
            acc += cache.get(k, 0)          # lookup
        return acc

    t, _ = timed(build_and_lookup, repeat=5)
    c_o = t / len(trace)
    print(f"measured c_o (tuple key + dict lookup) = {c_o*1e9:8.1f} ns/request")

    # A string cache key, as a WordPress/Redis deployment would actually use.
    def build_str():
        acc = 0
        for prov, lang, svc, day in trace:
            k = f"araya:v1:{prov}:{lang}:{svc}:{day}"
            acc += len(k)
        return acc

    t2, _ = timed(build_str, repeat=5)
    print(f"measured c_o (string key, no I/O)      = {t2/len(trace)*1e9:8.1f} ns/request")

    print("\nBreak-even: the quotient pays only while  K_N/N  <  (c_f - c_o)/(c_f + c_m)")
    print(f"{'workload':38} {'c_f':>10} {'max K/N':>9} {'ceiling':>10}")
    print("-" * 70)
    profiles = [
        ("dict/array op in-process",        200e-9),
        ("JSON parse of a small payload",     5e-6),
        ("template render (PHP partial)",   200e-6),
        ("indexed SQL query (local)",         2e-3),
        ("embedding one query (CPU)",        15e-3),
        ("HTTP call to an internal service", 40e-3),
        ("vector search over 1M chunks",    120e-3),
        ("LLM generation (small model)",    800e-3),
    ]
    for name, c_f in profiles:
        m = CostModel(c_f=c_f, c_o=c_o, c_m=0.0)
        be = m.break_even_alpha()
        verdict = "never pays" if be <= 0 else f"{be:8.4f}"
        print(f"{name:38} {c_f*1e3:8.3f}ms {verdict:>9} {m.max_speedup_ceiling():9.0f}x")

    print(
        "\nReading: for anything at or above a SQL query, the break-even K/N is ~1.0 --"
        "\ni.e. the quotient pays unless the trace is almost perfectly key-distinct."
        "\nFor in-process work it can never pay. That is the whole engineering rule."
    )
    return CostModel(c_f=2e-3, c_o=c_o)


# ---------------------------------------------------------------------------
# E2 - is the win about COST or about CONTINUUM-HEAVINESS?  (closes the confound)
# ---------------------------------------------------------------------------

def e2_confound_matrix() -> None:
    head("E2  Cost vs continuum-heaviness: the 2x2 the paper's counterexample misses")

    N = 30_000
    pts = [(rng.random(), rng.random()) for _ in range(N)]

    def expensive_trig(p):            # continuum-heavy AND expensive (paper's arm)
        x, y = p
        s = 0.0
        for i in range(1, 121):
            s += math.sin(x * i) * math.cos(y * i) + math.sqrt(abs(x - y) + i)
        return s

    def cheap_trig(p):                # continuum-heavy but CHEAP
        x, y = p
        return math.sin(x) + math.cos(y)

    def expensive_rational(p):        # Q-native but EXPENSIVE (exact rational work)
        x, y = p
        a = Fraction(int(x * 10**6), 10**6)
        b = Fraction(int(y * 10**6), 10**6)
        s = Fraction(0)
        for i in range(1, 25):
            s += (a * i + b) / (b * i + a + 1)
        return float(s)

    def cheap_poly(p):                # Q-native and CHEAP (paper's counterexample)
        x, y = p
        return ((3 * x + 2) * x + 1) * x + ((2 * y + 1) * y) + x * y

    eps = 0.01
    def key(p):
        return (round(p[0] / eps), round(p[1] / eps))
    def rep(p, k):
        return (k[0] * eps, k[1] * eps)

    print(f"{'function':32} {'kind':16} {'raw':>9} {'FRA':>9} {'speedup':>8} {'K/N':>7}")
    print("-" * 88)
    results = {}
    for name, fn, kind in [
        ("120 rounds of sin/cos/sqrt", expensive_trig, "expensive, R"),
        ("24 rounds exact Fraction",   expensive_rational, "expensive, Q"),
        ("sin(x)+cos(y)",              cheap_trig, "cheap, R"),
        ("cubic polynomial",           cheap_poly, "cheap, Q"),
    ]:
        t_raw, _ = timed(lambda fn=fn: [fn(p) for p in pts], repeat=3)

        def run(fn=fn):
            acc = FiniteReadoutAccelerator(key, rep, fn)
            out = [acc(p) for p in pts]
            return acc, out

        t_fra, (acc, _) = timed(run, repeat=3)
        sp = t_raw / t_fra
        results[name] = sp
        print(
            f"{name:32} {kind:16} {t_raw:8.3f}s {t_fra:8.3f}s {sp:7.2f}x {acc.alpha:7.4f}"
        )

    print(
        "\nBoth EXPENSIVE arms accelerate and both CHEAP arms do not, regardless of"
        "\nwhether the function is continuum-heavy (sin/cos/sqrt) or Q-native (exact"
        "\nFraction arithmetic). So the driver is c_f/c_o -- the cost ratio -- NOT how"
        "\nmuch continuum machinery the function contains. The paper's theory survives"
        "\nthe control its own counterexample could not distinguish."
    )


# ---------------------------------------------------------------------------
# E3 - the certificate, measured by MAX (and against a declared Lipschitz bound)
# ---------------------------------------------------------------------------

def e3_certificate() -> None:
    head("E3  Error certificate: what MEAN error hides")

    N = 20_000
    pts = [(rng.random(), rng.random()) for _ in range(N)]

    def score(p):
        x, y = p
        s = 0.0
        for i in range(1, 121):
            s += math.sin(x * i) * math.cos(y * i) + math.sqrt(abs(x - y) + i)
        return s

    def d_in(p, q):
        return max(abs(p[0] - q[0]), abs(p[1] - q[1]))   # Chebyshev: matches the grid

    L_hat = empirical_lipschitz(pts[:2000], score, d_in, pairs=40_000, rng=rng)
    print(f"empirical Lipschitz lower bound L_hat = {L_hat:.2f}")
    print("  (a LOWER bound from sampled difference quotients -- it cannot certify L)")

    print(f"\n{'eps':>7} {'r_Q':>8} {'declared L*r_Q':>15} {'obs MAX abs':>12} {'bound?':>9}"
          f" {'obs MEAN':>9} {'obs MAX':>9} {'max/mean':>9}")
    print("-" * 92)
    for eps in (0.005, 0.01, 0.02, 0.05):
        errs = []
        for p in pts:
            k = (round(p[0] / eps), round(p[1] / eps))
            rep = (k[0] * eps, k[1] * eps)
            errs.append(abs(score(p) - score(rep)))
        scale = statistics.fmean(abs(score(p)) for p in pts[:2000])
        r_Q = eps / 2 * math.sqrt(2)
        cert = Certificate(
            declared_delta=lipschitz_delta(L_hat, r_Q),
            observed_max=max(errs),
            observed_mean=statistics.fmean(errs),
            n=len(errs),
            scale=scale,
        )
        ratio = cert.observed_max / cert.observed_mean
        print(
            f"{eps:7.3f} {r_Q:8.4f} {cert.declared_delta:15.3f} "
            f"{cert.observed_max:12.3f} {'held' if cert.holds else 'VIOLATED':>9} "
            f"{cert.observed_mean/scale:8.3%} {cert.observed_max/scale:8.3%} {ratio:8.1f}x"
        )

    print(
        "\nThe MAX error runs several times the MEAN at every resolution. A published"
        "\n'0.84% mean relative error' therefore certifies nothing about the worst"
        "\nrequest -- and the worst request is the one that flips a ranking, a price"
        "\nband, or an eligibility decision. Report max; keep mean as context only."
    )


# ---------------------------------------------------------------------------
# E4 - an ARAYA-shaped web trace + the key-safety linter
# ---------------------------------------------------------------------------

def e4_web_trace() -> None:
    head("E4  ARAYA-shaped request trace: how much collapses, and is the key SAFE?")

    N = 30_000
    provinces = [f"p{i:02d}" for i in range(77)]
    # Zipf-ish province popularity: Bangkok and a few provinces dominate, as real.
    weights = [1.0 / (i + 1) ** 1.1 for i in range(77)]
    services = ["nikah", "venue", "package", "academy", "certificate"]
    roles = ["guest", "member", "admin"]

    trace = []
    for i in range(N):
        prov = rng.choices(provinces, weights=weights, k=1)[0]
        trace.append(
            {
                "province": prov,
                "lang": rng.choice(["th", "en"]),
                "service": rng.choice(services),
                "ts_ms": 1750000000000 + rng.randrange(30 * 86400 * 1000),
                "user_id": rng.randrange(4000),
                "role": rng.choices(roles, weights=[0.8, 0.18, 0.02], k=1)[0],
                "utm": rng.choice(["", "fb", "ig", "line", "google"]),
            }
        )

    def readout(r):
        """What the page actually returns: listing content + whether it is gated."""
        gated = r["role"] == "guest"
        return (r["province"], r["lang"], r["service"],
                r["ts_ms"] // (86400 * 1000), gated)

    keys = {
        "Q0 raw (ts_ms + user_id + utm)":
            lambda r: (r["province"], r["lang"], r["service"], r["ts_ms"],
                       r["user_id"], r["utm"], r["role"]),
        "Q1 drop utm + user_id":
            lambda r: (r["province"], r["lang"], r["service"], r["ts_ms"], r["role"]),
        "Q2 + bin timestamp to the day":
            lambda r: (r["province"], r["lang"], r["service"],
                       r["ts_ms"] // (86400 * 1000), r["role"]),
        "Q3 UNSAFE: Q2 without role":
            lambda r: (r["province"], r["lang"], r["service"],
                       r["ts_ms"] // (86400 * 1000)),
    }

    c_o = 3e-7
    model = CostModel(c_f=2e-3, c_o=c_o)   # one indexed SQL query + render
    declared_cells = [(s, ro) for s in services for ro in roles]
    def cov(r): return (r["service"], r["role"])

    print(f"{'cache key design':34} {'K':>7} {'K/N':>7} {'hit rate':>9} {'pred speedup':>13}  safety")
    print("-" * 96)
    for name, fn in keys.items():
        rep = audit_key_safety(
            trace, fn, readout, coverage_key=cov, declared_cells=declared_cells
        )
        sp = model.speedup(N, rep.n_keys)
        verdict = "UNSAFE" if not rep.exact_safe else ("OK" if rep.trustworthy_pass else "UNCERTIFIED")
        print(
            f"{name:34} {rep.n_keys:7d} {rep.n_keys/N:7.4f} "
            f"{1-rep.n_keys/N:8.2%} {sp:12.2f}x  {verdict}"
        )
        if not rep.exact_safe:
            k, a, b = rep.violating_keys[0]
            print(f"{'':34} -> key {k}")
            print(f"{'':34}    serves gated={a[-1]} and gated={b[-1]} from ONE entry")
        elif rep.coverage_gaps:
            print(f"{'':34} -> {len(rep.coverage_gaps)} (service,role) cell(s) untested: "
                  f"{rep.coverage_gaps[:3]}")

    print(
        "\nQ3 is the fastest key in the table and it is a security bug: it merges a"
        "\nguest and a logged-in member into one cache entry. This is a TRACE-BOUNDED"
        "\ncheck (tier finite_diagnostic), not a decidable proof of absence: an OK verdict"
        "\nonly holds when coverage_gaps is empty (every declared role/service cell was"
        "\nactually exercised) -- ker(Q) subseteq ker(g) is checked on the trace you have,"
        "\nnever on the trace you haven't. Run it, with coverage declared, in CI on every"
        "\ncache-key change."
    )


# ---------------------------------------------------------------------------
# E5 - RAG / vector retrieval, scored by RECALL (the real readout)
# ---------------------------------------------------------------------------

def e5_vector_rag() -> None:
    head("E5  RAG query quotient: score it by RECALL, not by coordinate error")

    M, D, NQ, TOPK, NTOPIC = 20_000, 128, 3_000, 10, 300

    # A realistic embedding corpus is NOT uniform on the sphere -- it lies near a
    # low-dimensional manifold of topics. A uniform Gaussian corpus has no nearest
    # neighbour worth finding (all cosines ~ 0), and would make every quotient look
    # broken for reasons that have nothing to do with the quotient.
    def unit(a):
        return a / np.linalg.norm(a, axis=1, keepdims=True)

    def jitter(base, r):
        """base + a perturbation of RELATIVE norm r (r<1 keeps the cluster intact).

        Scaling raw N(0,I_D) by a constant does NOT do this: in D=128 a coefficient
        of 0.35 already has norm 0.35*sqrt(128) ~ 3.96, four times the signal, which
        destroys the cluster structure and makes every quotient look broken.
        """
        u = unit(nprng.normal(size=base.shape).astype(np.float32))
        return unit(base + r * u)

    topics = unit(nprng.normal(size=(NTOPIC, D)).astype(np.float32))
    doc_topic = nprng.integers(0, NTOPIC, M)
    corpus = jitter(topics[doc_topic], 0.60)      # within-topic cosine ~ 0.74

    # Real query traffic is not uniform either: users ask the same ~200 things,
    # reworded -- so queries sit near topics, with paraphrase noise.
    intent_topic = nprng.integers(0, NTOPIC, 200)
    intents = jitter(topics[intent_topic], 0.30)
    q = jitter(intents[nprng.integers(0, 200, NQ)], 0.25)

    sims = corpus[:2000] @ corpus[:2000].T
    print(f"corpus structure check: mean off-diagonal cosine = "
          f"{(sims.sum() - np.trace(sims)) / (2000*1999):.4f}, "
          f"mean top-10 cosine = {np.mean(np.sort(sims, axis=1)[:, -11:-1]):.4f}")
    print("  (a structured corpus: near neighbours are genuinely nearer than average)")

    def exact_topk(v):
        return np.argpartition(-(corpus @ v), TOPK)[:TOPK]

    t_raw, gold = timed(lambda: [exact_topk(v) for v in q], repeat=3)
    gold_sets = [set(g.tolist()) for g in gold]

    # Three candidate quotients. The first is the one everybody reaches for.
    quotients = []
    for eps in (0.05, 0.20):
        quotients.append(
            (f"scalar quant  eps={eps:.2f}",
             (lambda v, eps=eps: np.round(v / eps).astype(np.int16).tobytes()))
        )
    # LSH: sign of p random projections -> p bits. A genuinely COARSE key.
    for p in (24, 16, 12):
        P = nprng.normal(size=(D, p)).astype(np.float32)
        quotients.append(
            (f"LSH sign, p={p:>2} bits",
             (lambda v, P=P: np.packbits((v @ P) > 0).tobytes()))
        )
    # IVF-style: nearest of C coarse centroids (what FAISS/IVF actually does).
    for C in (2000, 500):
        cc = corpus[nprng.choice(M, C, replace=False)].copy()
        quotients.append(
            (f"coarse centroid, C={C}",
             (lambda v, cc=cc: int(np.argmax(cc @ v))))
        )

    print(f"{'quotient':28} {'K/N':>7} {'speedup':>9} {'recall mean':>12} {'recall MIN':>11} {'p05':>7}")
    print("-" * 82)
    for name, key in quotients:
        acc = FiniteReadoutAccelerator(key, lambda v, k: v, exact_topk)
        t_fra, got = timed(lambda acc=acc: [acc(v) for v in q], repeat=1)
        recalls = [len(set(g.tolist()) & gold_sets[i]) / TOPK for i, g in enumerate(got)]
        recalls.sort()
        print(
            f"{name:28} {acc.alpha:7.4f} {t_raw/t_fra:8.2f}x "
            f"{statistics.fmean(recalls):11.3f} {min(recalls):10.3f} "
            f"{recalls[len(recalls)//20]:6.3f}"
        )

    # ---- the CORRECT pattern: quotient generates CANDIDATES, exact rerank decides
    # (paper Eq 28: Answer(q) = Rerank_exact(Candidates_Q(Q(q))) -- the rerank is
    #  not optional decoration, it is what makes the quotient safe.)
    print()
    C = 500
    # Trained centroids, as a real IVF index uses -- sampled FROM the corpus, not
    # drawn at random in the ambient space.
    cent = corpus[nprng.choice(M, C, replace=False)].copy()
    assign = np.argmax(corpus @ cent.T, axis=1)
    buckets = [np.flatnonzero(assign == c) for c in range(C)]

    for nprobe in (1, 4, 16):
        def ivf(v, nprobe=nprobe):
            cs = np.argpartition(-(cent @ v), nprobe)[:nprobe]
            cand = np.concatenate([buckets[c] for c in cs])
            if len(cand) <= TOPK:
                return cand
            sub = corpus[cand] @ v
            return cand[np.argpartition(-sub, TOPK)[:TOPK]]

        t_ivf, got = timed(lambda: [ivf(v) for v in q], repeat=1)
        recalls = sorted(
            len(set(g.tolist()) & gold_sets[i]) / TOPK for i, g in enumerate(got)
        )
        print(
            f"{'IVF candidates + exact rerank, nprobe=' + str(nprobe):40} "
            f"{t_raw/t_ivf:6.2f}x  recall mean={statistics.fmean(recalls):.3f} "
            f"min={min(recalls):.3f} p05={recalls[len(recalls)//20]:.3f}"
        )

    print(
        "\nThe naive quotient is INJECTIVE in high dimension: rounding 128 coordinates"
        "\nnever makes two distinct queries collide, so K/N = 1 and Proposition 2"
        "\nguarantees a slowdown. The quotient must be built in a LOW-dimensional"
        "\nreadout space (LSH bits, coarse centroid) before it can collapse anything."
        "\nAnd then mean recall stays flattering long after the WORST query has"
        "\ncollapsed -- gate a RAG cache on min/p05 recall plus an exact rerank,"
        "\nnever on mean recall or on embedding MSE."
    )


# ---------------------------------------------------------------------------
# E6 - the online guard under distribution shift
# ---------------------------------------------------------------------------

def e6_guard_under_shift() -> None:
    head("E6  Distribution shift: does the deployment notice it stopped paying?")

    model = CostModel(c_f=50e-6, c_o=30e-6)   # deliberately thin margin
    print(f"c_f={model.c_f*1e6:.0f}us  c_o={model.c_o*1e6:.0f}us  "
          f"break-even K/N = {model.break_even_alpha():.4f}")

    # Phase 1: healthy, highly repetitive traffic. Phase 2: near-unique keys.
    phase1 = [rng.randrange(300) for _ in range(20_000)]
    phase2 = [100_000 + i for i in range(20_000)]
    trace = phase1 + phase2

    for guarded in (False, True):
        guard = BreakEvenGuard(model, window=2000, recheck_every=2000) if guarded else None
        acc = FiniteReadoutAccelerator(
            key_fn=lambda x: x,
            representative_fn=lambda x, k: x,
            expensive_fn=lambda x: x * x,
            guard=guard,
        )
        for x in trace:
            acc(x)
        # model the wall-clock the deployment would have paid
        if guarded and guard.stats.disabled_at:
            n1 = guard.stats.disabled_at
            k1 = len(set(trace[:n1]))
            cost = n1 * model.c_o + k1 * model.c_f + (len(trace) - n1) * model.c_f
            tag = f"guard tripped at request {n1}: {guard.stats.reason}"
        else:
            k = len(set(trace))
            cost = len(trace) * model.c_o + k * model.c_f
            tag = "no guard -- ran the quotient over the whole trace"
        raw = len(trace) * model.c_f
        print(
            f"\n{'GUARDED' if guarded else 'UNGUARDED'}: modelled {cost*1e3:7.1f} ms "
            f"vs raw {raw*1e3:7.1f} ms -> {raw/cost:5.2f}x"
        )
        print(f"  {tag}")

    print(
        "\nWithout the guard the shift turns a win into a measured LOSS and nothing"
        "\nreports it. K_N/N is a readout of the prefix you have already seen; it does"
        "\nnot bound the trace you are about to receive. Monitor it, or the break-even"
        "\ntheorem is decoration."
    )


if __name__ == "__main__":
    which = sys.argv[1:] or ["1", "2", "3", "4", "5", "6"]
    if "1" in which:
        e1_break_even_table()
    if "2" in which:
        e2_confound_matrix()
    if "3" in which:
        e3_certificate()
    if "4" in which:
        e4_web_trace()
    if "5" in which:
        e5_vector_rag()
    if "6" in which:
        e6_guard_under_shift()
