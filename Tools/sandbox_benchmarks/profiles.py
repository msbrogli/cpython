"""Restriction profile definitions for sandbox benchmarks.

Each profile is a dict of sys.sandbox config settings.
None means the sandbox is not enabled (disabled profile).
Limits are set generously so benchmarks never hit them —
we measure the overhead of *checking*, not *enforcing*.
"""

# Generous limits that benchmarks will never reach
_SIZE_LIMITS = dict(
    max_int_digits=50000,
    max_str_length=500000,
    max_bytes_length=500000,
    max_list_size=500000,
    max_dict_size=500000,
    max_set_size=500000,
    max_tuple_size=500000,
)

_ITERATION_LIMIT = dict(
    max_iterations=100000000,
)

_OPERATION_LIMIT = dict(
    max_operations=100000000,
)

# Common permissive settings — disable import/module restrictions so
# benchmarks that use stdlib (math, json, re, random) work correctly.
# We are not benchmarking import overhead.
_PERMISSIVE_BASE = dict(
    allow_float=True,
    allow_complex=True,
    allow_dunder_access=True,
    allow_unsafe=True,
    allow_io=True,
    allow_class_creation=True,
    allow_magic_methods=True,
    allow_metaclasses=True,
    import_restrict_mode=False,
    module_access_restrict_mode=False,
)

PROFILES = {
    # Sandbox exists but not enabled — measures compiled-in check overhead
    "disabled": None,

    # Enabled, all limits=0 (no limit), all features permissive
    "enabled_nolimits": dict(
        max_int_digits=0,
        max_str_length=0,
        max_bytes_length=0,
        max_list_size=0,
        max_dict_size=0,
        max_set_size=0,
        max_tuple_size=0,
        max_iterations=0,
        max_operations=0,
        **_PERMISSIVE_BASE,
    ),

    # Only size limits active
    "size_limits_only": dict(
        **_SIZE_LIMITS,
        max_iterations=0,
        max_operations=0,
        **_PERMISSIVE_BASE,
    ),

    # Size limits + iteration limits
    "iteration_limits": dict(
        **_SIZE_LIMITS,
        **_ITERATION_LIMIT,
        max_operations=0,
        **_PERMISSIVE_BASE,
    ),

    # Size limits + dunder access blocked
    "dunder_blocked": dict(
        **_SIZE_LIMITS,
        max_iterations=0,
        max_operations=0,
        **{k: v for k, v in _PERMISSIVE_BASE.items() if k != 'allow_dunder_access'},
        allow_dunder_access=False,
    ),

    # Size limits + frozen mode
    "frozen_mode": dict(
        **_SIZE_LIMITS,
        max_iterations=0,
        max_operations=0,
        **_PERMISSIVE_BASE,
        # frozen_mode is set separately via sandbox property
    ),

    # Size limits + opcode restrict mode
    "opcode_restrict": dict(
        **_SIZE_LIMITS,
        max_iterations=0,
        max_operations=0,
        **_PERMISSIVE_BASE,
        # opcode_restrict_mode is set separately via sandbox property
    ),

    # Full lockdown — all restrictions active
    "full_lockdown": dict(
        **_SIZE_LIMITS,
        **_ITERATION_LIMIT,
        **_OPERATION_LIMIT,
        **{k: v for k, v in _PERMISSIVE_BASE.items()
           if k not in ('allow_dunder_access', 'allow_unsafe', 'allow_io')},
        allow_dunder_access=False,
        allow_unsafe=False,
        allow_io=False,
        # frozen_mode and opcode_restrict_mode set separately
    ),
}

# All valid opcodes — used by opcode_restrict profiles so the check fires
# on every dispatch but no opcode is actually blocked.
import opcode as _opcode
_ALL_OPCODES = frozenset(_opcode.opmap.values())

# Extra properties set outside set_config()
# These are applied via setattr(sys.sandbox, prop, value)
EXTRA_PROPERTIES = {
    "frozen_mode": {"frozen_mode": True},
    "opcode_restrict": {
        "opcode_restrict_mode": True,
        "allow_specialized_opcodes": True,
        "allowed_opcodes": _ALL_OPCODES,
    },
    "full_lockdown": {
        "frozen_mode": True,
        "opcode_restrict_mode": True,
        "allow_specialized_opcodes": True,
        "allowed_opcodes": _ALL_OPCODES,
    },
}
