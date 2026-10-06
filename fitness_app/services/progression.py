"""Progression policies: what tomorrow's targets should be.

Why this module exists
----------------------
A routine says *what* to train; a progression policy says *how the load
moves* from session to session. The rules here are standard training
methodology (linear progression, double progression through a rep range,
Greyskull-style AMRAP), reimplemented as pure functions so they are trivial
to test: history in, targets and a human-readable rationale out.

Every target the runner shows says *why* it is that number, and missed reps
never advance the load. Two consecutive missed sessions trigger a 10%
deload under Greyskull; the other policies hold. This mirrors the boundary
the future assistant will respect: judgement configures the plan, but this
engine owns the arithmetic, and it works with no LLM involved.
"""

from __future__ import annotations


#: Policy names a routine may use.
POLICIES = ("none", "linear", "double_progression", "greyskull")

#: Sessions missed in a row before Greyskull deloads.
STALL_LIMIT = 2

#: Deload fraction applied on a stall.
DELOAD_FACTOR = 0.9


def _round_weight(value: float) -> float:
    """Round a target to gym-plate reality (nearest 0.5 kg).

    Args:
        value: Raw computed weight.

    Returns:
        Weight rounded to the nearest half kilo. Plates smaller than that
        are a fiction in most gyms, and targets should be loadable.
    """
    return round(value * 2) / 2


def _hit_all(history: list[dict]) -> bool:
    """Check the last session hit every target rep.

    Args:
        history: Recent sessions, newest last. Each is a dict with
            ``reps`` (list actually performed per set) and ``target_reps``.

    Returns:
        True when the newest session met or beat its target on every set.
    """
    if not history:
        return False
    last = history[-1]
    target = last.get("target_reps") or 0
    reps = last.get("reps") or []
    return bool(reps) and all(rep >= target for rep in reps)


def _missed(history: list[dict]) -> bool:
    """Check the last session missed any target rep.

    Args:
        history: Recent sessions, newest last.

    Returns:
        True when the newest session fell short on at least one set.
    """
    if not history:
        return False
    last = history[-1]
    target = last.get("target_reps") or 0
    return any(rep < target for rep in last.get("reps") or [])


def _consecutive_misses(history: list[dict]) -> int:
    """Count trailing sessions that missed reps.

    Args:
        history: Recent sessions, newest last.

    Returns:
        Number of consecutive missed sessions counting back from newest.
    """
    count = 0
    for session in reversed(history):
        target = session.get("target_reps") or 0
        if any(rep < target for rep in session.get("reps") or []):
            count += 1
        else:
            break
    return count


def _last_weight(history: list[dict], default: float) -> float:
    """Most recent working weight, or the default when no history exists.

    Args:
        history: Recent sessions, newest last.
        default: Starting weight for a new exercise.

    Returns:
        The weight to base the next target on.
    """
    if not history:
        return default
    return history[-1].get("weight") if history[-1].get("weight") is not None else default


def linear(
    history: list[dict], increment_kg: float = 2.5, default_weight: float = 20.0
) -> dict:
    """Linear progression: add weight when every target rep was hit.

    The simplest policy and the right default: hit the reps, earn more
    weight. Miss anything and the weight holds.

    Args:
        history: Recent sessions (weight, reps list, target_reps), newest last.
        increment_kg: Step to add on success.
        default_weight: Starting weight with no history.

    Returns:
        Dict with weight, reps (unchanged target), rationale and deload flag.
    """
    weight = _last_weight(history, default_weight)
    target = (history[-1].get("target_reps") if history else None) or 5

    if _hit_all(history):
        return {
            "weight": _round_weight(weight + increment_kg),
            "reps": target,
            "deload": False,
            "rationale": f"all {target}s hit — up {increment_kg:g} kg",
        }
    if not history:
        return {
            "weight": _round_weight(default_weight),
            "reps": target,
            "deload": False,
            "rationale": "first session — start light",
        }
    return {
        "weight": _round_weight(weight),
        "reps": target,
        "deload": False,
        "rationale": "reps missed — weight holds",
    }


def double_progression(
    history: list[dict],
    increment_kg: float = 2.5,
    default_weight: float = 20.0,
    rep_min: int = 8,
    rep_max: int = 12,
) -> dict:
    """Double progression: climb reps first, weight second.

    Work from the bottom of the rep range to the top across sessions; only
    when every set hits the top does the weight go up (and reps reset to
    the bottom). Misses hold everything in place.

    Args:
        history: Recent sessions, newest last.
        increment_kg: Step to add when the range top is cleared.
        default_weight: Starting weight with no history.
        rep_min: Range bottom.
        rep_max: Range top.

    Returns:
        Dict with weight, reps, rationale and deload flag.
    """
    weight = _last_weight(history, default_weight)

    if not history:
        return {
            "weight": _round_weight(default_weight),
            "reps": rep_min,
            "deload": False,
            "rationale": f"first session — start at {rep_min}s",
        }

    last = history[-1]
    reps_done = min(last.get("reps") or [rep_min])

    if all(rep >= rep_max for rep in (last.get("reps") or [])):
        return {
            "weight": _round_weight(weight + increment_kg),
            "reps": rep_min,
            "deload": False,
            "rationale": f"cleared {rep_max}s — up {increment_kg:g} kg, back to {rep_min}s",
        }
    if _missed(history):
        return {
            "weight": _round_weight(weight),
            "reps": reps_done,
            "deload": False,
            "rationale": "reps missed — hold and consolidate",
        }
    return {
        "weight": _round_weight(weight),
        "reps": min(rep_max, reps_done + 1),
        "deload": False,
        "rationale": f"add a rep next time ({reps_done} → {min(rep_max, reps_done + 1)})",
    }


def greyskull(
    history: list[dict], increment_kg: float = 2.5, default_weight: float = 20.0
) -> dict:
    """Greyskull-style AMRAP progression with resets.

    Sets of 5 with the last set as-many-reps-as-possible: hit 5+ on it and
    the weight goes up. Miss reps twice running and the weight resets 10%,
    because grinding into a stall is how progress dies.

    Args:
        history: Recent sessions, newest last.
        increment_kg: Step to add on success.
        default_weight: Starting weight with no history.

    Returns:
        Dict with weight, reps, rationale and deload flag.
    """
    weight = _last_weight(history, default_weight)
    target = (history[-1].get("target_reps") if history else None) or 5

    if not history:
        return {
            "weight": _round_weight(default_weight),
            "reps": target,
            "deload": False,
            "rationale": "first session — 5, 5, 5+",
        }

    if _consecutive_misses(history) >= STALL_LIMIT:
        reset = _round_weight(weight * DELOAD_FACTOR)
        return {
            "weight": reset,
            "reps": target,
            "deload": True,
            "rationale": f"stalled twice — reset 10% to {reset:g} kg and climb back",
        }

    last = history[-1]
    top_set = max(last.get("reps") or [0])
    if top_set >= target and _hit_all(history):
        return {
            "weight": _round_weight(weight + increment_kg),
            "reps": target,
            "deload": False,
            "rationale": f"{top_set} on the AMRAP set — up {increment_kg:g} kg",
        }
    return {
        "weight": _round_weight(weight),
        "reps": target,
        "deload": False,
        "rationale": "missed reps — hold the weight",
    }


#: Policy name -> function.
POLICY_FUNCTIONS = {
    "none": None,  # handled directly in next_target: targets never move
    "linear": linear,
    "double_progression": double_progression,
    "greyskull": greyskull,
}


def next_target(
    policy: str,
    history: list[dict],
    increment_kg: float = 2.5,
    default_weight: float = 20.0,
    rep_min: int = 8,
    rep_max: int = 12,
) -> dict:
    """Compute the next session's targets under a policy.

    Args:
        policy: One of ``none``, ``linear``, ``double_progression``,
            ``greyskull``. Unknown names fall back to linear rather than
            failing — a mistyped policy must not block training.
        history: Recent sessions (weight, reps list, target_reps), newest last.
        increment_kg: Step on success.
        default_weight: Starting weight with no history.
        rep_min: Double-progression range bottom.
        rep_max: Double-progression range top.

    Returns:
        Dict with weight, reps, rationale and deload flag.
    """
    if policy == "none":
        weight = _last_weight(history, default_weight)
        target = (history[-1].get("target_reps") if history else None) or 5
        return {
            "weight": _round_weight(weight),
            "reps": target,
            "deload": False,
            "rationale": "no automatic progression — targets stay put",
        }
    function = POLICY_FUNCTIONS.get(policy, linear)
    if function is None:  # defensive: the table maps none -> None
        function = linear
    if function is double_progression:
        return function(history, increment_kg, default_weight, rep_min, rep_max)
    return function(history, increment_kg, default_weight)


def next_cardio_target(
    durations: list[int],
    enabled: bool,
    default_seconds: int = 600,
) -> dict:
    """Compute the next cardio duration target.

    Cardio progression is deliberately modest and off by default: when
    enabled, the target grows 5% over the last logged duration. The future
    assistant may *offer* to enable it, but nothing here turns it on.

    Args:
        durations: Recent logged durations in seconds, newest last.
        enabled: The routine slot's progress flag.
        default_seconds: Starting target with no history.

    Returns:
        Dict with duration_seconds and rationale.
    """
    if not enabled or not durations:
        return {
            "duration_seconds": durations[-1] if durations else default_seconds,
            "rationale": "cardio holds steady (progression off)"
            if not enabled else "first cardio session — start here",
        }
    grown = int(durations[-1] * 1.05)
    return {
        "duration_seconds": grown,
        "rationale": f"+5% over last time ({durations[-1]}s → {grown}s)",
    }
