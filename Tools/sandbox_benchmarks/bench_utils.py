"""Shared utilities for sandbox benchmarks.

Provides sandbox detection, setup helpers, and pyperf integration.
"""

import sys
import os

# Sandbox detection
HAS_SANDBOX = hasattr(sys, 'sandbox')

# Sentinel filename for sandbox scope registration
SANDBOX_FILENAME = "<sandbox_bench>"


def setup_sandbox(profile_name, scoped=True):
    """Configure the sandbox according to a named profile.

    Args:
        profile_name: Name from profiles.PROFILES (e.g. 'disabled', 'full_lockdown')
        scoped: If True, register SANDBOX_FILENAME for scope tracking
    """
    from profiles import PROFILES, EXTRA_PROPERTIES

    if profile_name not in PROFILES:
        raise ValueError(f"Unknown profile: {profile_name!r}. "
                         f"Available: {', '.join(PROFILES)}")

    profile_dict = PROFILES[profile_name]

    if not HAS_SANDBOX:
        # Standard CPython — nothing to do
        return

    sb = sys.sandbox

    if profile_dict is None:
        # 'disabled' profile — ensure sandbox is not enabled
        if sb.enabled:
            sb.disable()
        return

    # Enable sandbox
    sb.enable()

    # Apply config settings
    sb.set_config(**profile_dict)

    # Apply extra properties (frozen_mode, opcode_restrict_mode)
    extras = EXTRA_PROPERTIES.get(profile_name, {})
    for prop, value in extras.items():
        setattr(sb, prop, value)

    # Register scope filename
    if scoped:
        sb.add_filename(SANDBOX_FILENAME)


def make_bench_code(source):
    """Compile source code with the sandbox filename for scope tracking.

    Returns a code object compiled with SANDBOX_FILENAME as the filename.
    """
    return compile(source, SANDBOX_FILENAME, "exec")


def make_bench_funcs(source):
    """Compile and execute source, returning the resulting namespace.

    The source is compiled with SANDBOX_FILENAME so sandbox scope checks
    fire for the benchmarked code. Functions defined in the source are
    returned in the namespace dict.
    """
    code = make_bench_code(source)
    ns = {}
    exec(code, ns)
    return ns


def add_common_args(runner):
    """Add --sandbox-profile and --scoped arguments to a pyperf Runner.

    Returns the parsed args so the benchmark can access profile/scoped values.
    Note: We use --sandbox-profile (not --profile) to avoid conflict with
    pyperf's built-in --profile flag.
    """
    runner.argparser.add_argument(
        '--sandbox-profile', default='disabled', dest='sandbox_profile',
        help='Sandbox restriction profile name (default: disabled)')
    runner.argparser.add_argument(
        '--scoped', action='store_true', default=False,
        help='Register sandbox filename for scope tracking')
    # Parse args (pyperf handles its own args too)
    args = runner.parse_args()
    return args


def bench_main(bench_funcs, source_code=None):
    """Main entry point for benchmark scripts.

    Args:
        bench_funcs: dict mapping benchmark name to (source, func_name) or
                     list of (name, source, func_name) tuples.
                     If source_code is provided, bench_funcs is a list of
                     (name, func_name) tuples and all share the same source.
        source_code: Optional shared source code string.
    """
    import pyperf

    runner = pyperf.Runner()
    args = add_common_args(runner)

    # Setup sandbox with the specified profile
    setup_sandbox(args.sandbox_profile, scoped=args.scoped)

    if source_code is not None:
        # Shared source code — compile once
        ns = make_bench_funcs(source_code)
        for name, func_name in bench_funcs:
            runner.bench_func(name, ns[func_name])
    else:
        # Each benchmark has its own source
        for name, source, func_name in bench_funcs:
            ns = make_bench_funcs(source)
            runner.bench_func(name, ns[func_name])
