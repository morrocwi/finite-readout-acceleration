#!/usr/bin/env bash
# verify.sh — compile FRA_Closures.v and confirm every theorem is axiom-free.
# Mirrors information-discrete-math/formal/verify.sh's one-command discipline.
set -u
cd "$(dirname "$0")"

THMS=(break_even_iff ceiling_strict injective_key_slowdown hit_rate_bounds bottleneck_ceiling)

echo "Compiling FRA_Closures.v ..."
OUT=$(coqc -q FRA_Closures.v 2>&1)
STATUS=$?
if [ $STATUS -ne 0 ]; then
  echo "COMPILE FAILED"
  echo "$OUT"
  exit 1
fi

FAIL=0
i=0
for T in "${THMS[@]}"; do
  i=$((i+1))
  LINE=$(echo "$OUT" | sed -n "${i}p")
  if [ "$LINE" = "Closed under the global context" ]; then
    echo "OK   $T  -- axiom-free"
  else
    echo "FAIL $T  -- $LINE"
    FAIL=1
  fi
done

if [ $FAIL -eq 0 ]; then
  echo "ALL ${#THMS[@]} THEOREMS AXIOM-FREE."
  exit 0
else
  exit 1
fi
