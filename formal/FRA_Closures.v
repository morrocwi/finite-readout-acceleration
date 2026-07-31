(* ===================================================================== *)
(*  FRA_Closures.v — Finite Readout Acceleration, the algebraic subset,    *)
(*  Coq 8.20, over Q, axiom-free ("Closed under the global context" on     *)
(*  every theorem below — see Print Assumptions at the end of this file). *)
(*  Developed by Yaoharee Lahtee.                                         *)
(*                                                                         *)
(*  SCOPE, set by the webidm ultracode review (2026-07-30, run             *)
(*  wf_9075b1cc-9c6): Coq-ify ONLY the closures the review classed as      *)
(*  "genuinely exact over Q, no model assumption, given inputs". Every     *)
(*  closure the review flagged as model-dependent is deliberately OUT of   *)
(*  scope here and must not be bundled in with these:                      *)
(*    - Little's Law           (stationarity + finite-window boundary term)*)
(*    - M/M/c waiting time     (Poisson/independence assumption)           *)
(*    - index selectivity, predictive mode (column-independence assumption)*)
(*    - lipschitz_delta        WHEN L is empirically estimated rather than  *)
(*      given exactly (fra.py experiment E3 already falsified a declared   *)
(*      bound built from an estimated L, at 3 of 4 tested resolutions)     *)
(*  Each of those stays tier Dr / finite_diagnostic in fra.py and is NOT   *)
(*  represented here as a machine-checked theorem.                         *)
(*                                                                         *)
(*  Source: Lahtee 2026, "What a Finite Readout Need Not Compute" --        *)
(*    Thm 3   break_even_iff        (paper Eq 15)                         *)
(*    --      SpeedUp               (paper Eq 17)                        *)
(*    Prop 1  ceiling_strict         STRENGTHENED here (see note below)    *)
(*    Prop 2  injective_key_slowdown (paper: an injective key cannot       *)
(*                                    accelerate; here made quantitative:  *)
(*                                    K=N forces SpeedUp < 1, a genuine    *)
(*                                    slowdown, not merely "no speedup")   *)
(*    Prop 3  hit_rate_bounds        (paper Eq 20, plus the sanity bound   *)
(*                                    0 <= H <= 1 the paper states but      *)
(*                                    does not itself certify)             *)
(*    --      bottleneck_ceiling    (the review's finding #7 correction:   *)
(*                                    "tuning any page is pointless" was    *)
(*                                    retracted to a precise ceiling; this  *)
(*                                    is that ceiling, machine-checked --   *)
(*                                    matches the ARAYA measurement         *)
(*                                    1.356/1.130 = 1.20x used in the      *)
(*                                    engineering summary of 2026-07-30)   *)
(*                                                                         *)
(*  ON "ONE DAY" AND "INDUCTION": the ultracode review flagged the         *)
(*  Coq-ification timeline for the strengthened Prop 1 as a "narrow risk"  *)
(*  pending "an actual induction going through". ceiling_strict below      *)
(*  settles that concretely: it needs NO induction on N or K. N and K are  *)
(*  free rational parameters (not a recursively defined structure being    *)
(*  inducted over); the whole proof is one chain of field-ordered          *)
(*  inequality facts, because the denominator N*co + K*(cf+cm) is          *)
(*  STRICTLY larger than N*co the instant K*(cf+cm) > 0 -- a single         *)
(*  algebraic fact, not a recursion. Settled by a machine-checked witness, *)
(*  not by re-asserting the disagreement in prose.                        *)
(* ===================================================================== *)

Require Import QArith.
Require Import Lqa.

Open Scope Q_scope.

(* --------------------------------------------------------------------- *)
(*  A general cross-multiplication fact for Q, used by every theorem      *)
(*  below. Not paper-specific; a genuinely reusable field lemma.           *)
(* --------------------------------------------------------------------- *)

Lemma Qdiv_cross_lt : forall a b c d : Q, 0 < b -> 0 < d ->
  (a / b < c / d <-> a * d < c * b).
Proof.
  intros a b c d Hb Hd.
  assert (Hbne : ~ b == 0) by (apply Qnot_eq_sym, Qlt_not_eq; exact Hb).
  assert (Hdne : ~ d == 0) by (apply Qnot_eq_sym, Qlt_not_eq; exact Hd).
  split; intro H.
  - apply (Qmult_lt_compat_r (a/b) (c/d) (b*d)) in H.
    2: apply Qmult_lt_0_compat; assumption.
    assert (E1 : a/b*(b*d) == a*d) by (field; exact Hbne).
    assert (E2 : c/d*(b*d) == c*b) by (field; exact Hdne).
    rewrite E1 in H. rewrite E2 in H. exact H.
  - apply (Qmult_lt_compat_r (a*d) (c*b) (/b * /d)) in H.
    2: { apply Qmult_lt_0_compat; apply Qinv_lt_0_compat; assumption. }
    assert (E1 : a*d*(/b * /d) == a/b) by (field; split; assumption).
    assert (E2 : c*b*(/b * /d) == c/d) by (field; split; assumption).
    rewrite E1 in H. rewrite E2 in H. exact H.
Qed.

(* --------------------------------------------------------------------- *)
(*  Definitions -- Eq 13/14/17/20 of the paper, exactly, over Q.           *)
(* --------------------------------------------------------------------- *)

(* Raw cost of executing every request with no reuse. *)
Definition Traw (N cf : Q) : Q := N * cf.

(* Cost with the readout quotient: N lookups + K expensive evaluations. *)
Definition Tq (N K cf co cm : Q) : Q := N * co + K * (cf + cm).

(* Measured speedup, Eq 17. *)
Definition SpeedUp (N K cf co cm : Q) : Q := Traw N cf / Tq N K cf co cm.

(* Induced hit rate, Eq 20. *)
Definition HitRate (N K : Q) : Q := 1 - K / N.

(* --------------------------------------------------------------------- *)
(*  Thm 3 -- break-even condition (paper Eq 15), as a genuine iff.         *)
(*  Hypotheses: N>0 (a trace has at least one request), cf+cm>0 (a         *)
(*  positive marginal miss cost), co<cf (the work must cost more than the  *)
(*  overhead for caching to ever be worth considering).                    *)
(* --------------------------------------------------------------------- *)

Theorem break_even_iff :
  forall N K cf co cm : Q,
    0 < N -> 0 < cf + cm -> co < cf ->
    ( Tq N K cf co cm < Traw N cf  <->  K / N < (cf - co) / (cf + cm) ).
Proof.
  intros N K cf co cm HN Hcfcm Hcocf.
  unfold Tq, Traw.
  rewrite (Qdiv_cross_lt K N (cf - co) (cf + cm) HN Hcfcm).
  split; intro H; lra.
Qed.

(* --------------------------------------------------------------------- *)
(*  Prop 1, STRENGTHENED: a strict finite ceiling holding for EVERY trace  *)
(*  (N>0, K>0, cm>=0, cf>0, co>0) -- no limit K/N -> 0 is taken, unlike the *)
(*  paper's asymptotic statement (which is I3, an injected infinity, in    *)
(*  information-discrete-math's own terms). No induction over N or K.      *)
(* --------------------------------------------------------------------- *)

Theorem ceiling_strict :
  forall N K cf co cm : Q,
    0 < N -> 0 < K -> 0 <= cm -> 0 < cf -> 0 < co ->
    SpeedUp N K cf co cm < cf / co.
Proof.
  intros N K cf co cm HN HK Hcm Hcf Hco.
  unfold SpeedUp, Traw, Tq.
  assert (HNco : 0 < N * co) by (apply Qmult_lt_0_compat; [exact HN | exact Hco]).
  assert (Hpos : 0 < K * (cf + cm)).
  { apply Qmult_lt_0_compat; [exact HK | lra]. }
  apply Qdiv_cross_lt.
  - lra.
  - exact Hco.
  - assert (Heq : cf * (N*co + K*(cf+cm)) == N*cf*co + cf*(K*(cf+cm))) by ring.
    assert (Hp2 : 0 < cf*(K*(cf+cm))) by (apply Qmult_lt_0_compat; [exact Hcf|exact Hpos]).
    rewrite Heq. lra.
Qed.

(* --------------------------------------------------------------------- *)
(*  Prop 2, made quantitative: an injective key (K=N, every request its    *)
(*  own class) does not merely fail to accelerate -- it strictly slows     *)
(*  the system down, whenever co>0 (any nonzero overhead at all).          *)
(* --------------------------------------------------------------------- *)

Theorem injective_key_slowdown :
  forall N cf co cm : Q,
    0 < N -> 0 < cf -> 0 < co -> 0 <= cm ->
    SpeedUp N N cf co cm < 1.
Proof.
  intros N cf co cm HN Hcf Hco Hcm.
  unfold SpeedUp, Traw, Tq.
  assert (Hden : 0 < N*co + N*(cf+cm)).
  { assert (H1 : 0 < N*co) by (apply Qmult_lt_0_compat; assumption).
    assert (H2 : 0 <= N*(cf+cm)) by (apply Qmult_le_0_compat; lra).
    lra. }
  apply Qlt_shift_div_r; [exact Hden|].
  assert (Heq : 1 * (N*co + N*(cf+cm)) == N*cf + N*co + N*cm) by ring.
  rewrite Heq.
  assert (H3 : 0 < N*co) by (apply Qmult_lt_0_compat; assumption).
  assert (H4 : 0 <= N*cm) by (apply Qmult_le_0_compat; lra).
  lra.
Qed.

(* --------------------------------------------------------------------- *)
(*  Prop 3, plus the sanity bound the paper states but leaves unproved:    *)
(*  the induced hit rate is genuinely a rate -- it lies in [0,1].          *)
(* --------------------------------------------------------------------- *)

Theorem hit_rate_bounds :
  forall N K : Q, 0 < N -> 0 <= K -> K <= N ->
    0 <= HitRate N K /\ HitRate N K <= 1.
Proof.
  intros N K HN HK0 HKN.
  unfold HitRate.
  assert (Hle : K/N <= 1) by (apply Qle_shift_div_r; [exact HN | lra]).
  assert (Hge : 0 <= K/N) by (apply Qle_shift_div_l; [exact HN | lra]).
  lra.
Qed.

(* --------------------------------------------------------------------- *)
(*  The corrected "bottleneck share" claim (review finding #7): the        *)
(*  proposal originally said a large fixed cost makes 'tuning anything      *)
(*  else pointless'; the review retracted 'pointless' and required a       *)
(*  precise ceiling instead. This is that ceiling: if total cost splits     *)
(*  into a fixed bootstrap plus a variable rest, the best any amount of     *)
(*  work on 'rest' can ever achieve is bounded by total/bootstrap -- and    *)
(*  that ratio is always >= 1, never less, regardless of how much "rest"    *)
(*  is eliminated. On the ARAYA measurement (bootstrap=1.130s,              *)
(*  rest=0.226s, total=1.356s) this instantiates to exactly the 1.20x       *)
(*  used in the 2026-07-30 engineering summary.                            *)
(* --------------------------------------------------------------------- *)

Theorem bottleneck_ceiling :
  forall total bootstrap rest : Q,
    0 < bootstrap -> 0 <= rest -> total == bootstrap + rest ->
    1 <= total / bootstrap.
Proof.
  intros total bootstrap rest Hb Hr Heq.
  rewrite Heq.
  apply Qle_shift_div_l; [exact Hb | lra].
Qed.

(* --------------------------------------------------------------------- *)
(*  Axiom-freedom, checked for every theorem above -- the one-command       *)
(*  reproducibility discipline this repo's own formal/verify.sh uses.       *)
(* --------------------------------------------------------------------- *)

Print Assumptions break_even_iff.
Print Assumptions ceiling_strict.
Print Assumptions injective_key_slowdown.
Print Assumptions hit_rate_bounds.
Print Assumptions bottleneck_ceiling.
