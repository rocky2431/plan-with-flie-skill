"""Isolate child hooks and CLIs from the calling host's task selections."""

import os


HOST_VARIABLES = frozenset({
    "CLAUDE_CODE_SESSION_ID", "CLAUDE_PLUGIN_DATA", "CLAUDE_PLUGIN_ROOT",
    "ZCODE_PLUGIN_ROOT", "GROK_PLUGIN_DATA",
})


def clean_environment(**overrides: str) -> dict[str, str]:
    environment = {key: value for key, value in os.environ.items()
                   if key not in HOST_VARIABLES and not key.startswith("TASK_STATE_")}
    environment.update(overrides)
    return environment
