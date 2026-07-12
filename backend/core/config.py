import os
import yaml
from pathlib import Path


ENV_OVERRIDES = {
    "voice": {"deepgram_api_key": "DEEPGRAM_API_KEY"},
    "mcp": {
        "servers": {
            "github": {"env": {"GITHUB_PERSONAL_ACCESS_TOKEN": "GITHUB_PERSONAL_ACCESS_TOKEN"}},
            "exa": {"env": {"EXA_API_KEY": "EXA_API_KEY"}},
        }
    },
    "ollama": {"endpoint": "OLLAMA_ENDPOINT"},
}


def load_config():
    dotenv_path = Path(__file__).resolve().parent.parent.parent / ".env"
    if dotenv_path.exists():
        with open(dotenv_path) as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith("#") and "=" in line:
                    k, v = line.split("=", 1)
                    os.environ.setdefault(k.strip(), v.strip())

    config_path = Path(__file__).resolve().parent.parent.parent / "config.yaml"
    with open(config_path) as f:
        config = yaml.safe_load(f)

    _walk_and_override(config, ENV_OVERRIDES)

    configured_projects = config.get("data", {}).get("projects_dir", "")
    if configured_projects and not os.path.isdir(configured_projects):
        fallback = os.environ.get("PROJECTS_DIR") or str(
            Path(__file__).resolve().parent.parent.parent / "projects"
        )
        config["data"]["projects_dir"] = fallback

    return config


def _walk_and_override(cfg_dict, override_map):
    for key, value in override_map.items():
        if isinstance(value, dict):
            if key in cfg_dict and isinstance(cfg_dict[key], dict):
                _walk_and_override(cfg_dict[key], value)
        elif isinstance(value, str):
            env_val = os.environ.get(value)
            if env_val:
                cfg_dict[key] = env_val
