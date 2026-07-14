#!/usr/bin/env python3
"""Verify system_issues 6.2 fix: api keys never land in _spec.json's
config_kwargs, yet still reach the reconstructed config in the sandbox.

Self-contained: loads ale_run/executors/_secrets.py directly by path so it
does not import the ale_run package (which pulls heavy deps). Mirrors the
host->sandbox round-trip:

  host:    kwargs = _config_to_kwargs(cfg)            # all scalar fields
           keyless, sidecar = split_config_secrets(kwargs)
           _spec.json  <- keyless        (gathered to host logs)
           _secrets.json <- {**env, **sidecar}        (read-once, deleted)

  entry:   cfg = Cfg(**keyless)                        # from _spec.json
           apply_config_secrets(cfg, sidecar+env)      # re-attach real key
           os.environ <- strip_cfg_secrets(env)        # NOT the cfg secret
"""
import dataclasses
import importlib.util
import json
from pathlib import Path

_HERE = Path(__file__).resolve().parent
_SECRETS_PY = _HERE.parent / "ale_run" / "executors" / "_secrets.py"


def _load_secrets_module():
    spec = importlib.util.spec_from_file_location("_ale_secrets_under_test", _SECRETS_PY)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


S = _load_secrets_module()


# Faithful copy of executors' _config_to_kwargs (both sandbox.py and docker.py
# share this shape) so the test exercises the real serialization path.
def _config_to_kwargs(cfg):
    out = {}
    for f in dataclasses.fields(cfg):
        val = getattr(cfg, f.name)
        if isinstance(val, (str, int, float, bool, type(None), list, dict, tuple)):
            out[f.name] = val
    return out


@dataclasses.dataclass
class PiConfigLike:
    """Shaped like ale_run.agents.pi.config.PiConfig for the fields that matter."""
    model: str = "openai/gpt-5.6-sol"
    api_key: str | None = None
    api_key_env: str = "OPENAI_API_KEY"
    base_url: str | None = None
    max_tokens: int = 32768


REAL_KEY = "sk-supersecret-abcd1234"


def _fail(msg):
    print(f"FAIL: {msg}")
    raise SystemExit(1)


def test_spec_is_keyless_and_key_roundtrips():
    cfg = PiConfigLike(api_key=REAL_KEY, api_key_env="OPENAI_API_KEY")

    kwargs = _config_to_kwargs(cfg)
    assert kwargs["api_key"] == REAL_KEY, "precondition: raw kwargs carry the key"

    keyless, sidecar = S.split_config_secrets(kwargs)

    # 1. _spec.json (== keyless) must not contain the plaintext key anywhere.
    spec_blob = json.dumps({"config_kwargs": keyless})
    if REAL_KEY in spec_blob:
        _fail(f"plaintext key leaked into _spec.json: {spec_blob}")
    if keyless.get("api_key") is not None:
        _fail(f"api_key not blanked in keyless kwargs: {keyless.get('api_key')!r}")

    # 2. api_key_env is a VAR NAME, not a secret -> must survive intact.
    if keyless.get("api_key_env") != "OPENAI_API_KEY":
        _fail(f"api_key_env wrongly stripped/mangled: {keyless.get('api_key_env')!r}")

    # 3. non-secret scalar fields survive.
    if keyless.get("model") != "openai/gpt-5.6-sol" or keyless.get("max_tokens") != 32768:
        _fail(f"non-secret fields corrupted: {keyless!r}")

    # 4. the secret rides the sidecar under the reserved prefix.
    prefixed = S.CFG_SECRET_PREFIX + "api_key"
    if sidecar.get(prefixed) != REAL_KEY:
        _fail(f"sidecar missing the real key under {prefixed}: {sidecar!r}")

    # 5. entry-side reconstruction: keyless spec -> cfg, then re-attach.
    reconstructed = PiConfigLike(**keyless)
    if reconstructed.api_key is not None:
        _fail("reconstructed cfg unexpectedly already has api_key")
    framework_env = {"OPENAI_API_KEY": REAL_KEY, "HF_TOKEN": "hf_xyz"}
    full_sidecar = {**framework_env, **sidecar}
    S.apply_config_secrets(reconstructed, full_sidecar)
    if reconstructed.api_key != REAL_KEY:
        _fail(f"key not re-attached to cfg: {reconstructed.api_key!r}")

    # 6. os.environ injection must EXCLUDE the cfg secret (agent must not read it)
    #    but keep the framework env vars.
    injected = S.strip_cfg_secrets(full_sidecar)
    if prefixed in injected:
        _fail("cfg secret would be injected into os.environ (agent-visible)")
    if injected.get("OPENAI_API_KEY") != REAL_KEY or injected.get("HF_TOKEN") != "hf_xyz":
        _fail(f"framework env vars wrongly stripped: {injected!r}")

    print("PASS: test_spec_is_keyless_and_key_roundtrips")


def test_api_key_env_not_captured_as_secret():
    # Exact-match on field NAME: api_key_env holds a var name, not a secret.
    if S.is_secret_field("api_key_env"):
        _fail("api_key_env wrongly classified as a secret field")
    if not S.is_secret_field("api_key"):
        _fail("api_key not classified as a secret field")
    if not S.is_secret_field("API_KEY"):
        _fail("case-insensitivity broken for api_key")
    print("PASS: test_api_key_env_not_captured_as_secret")


def test_empty_secret_field_dropped_cleanly():
    cfg = PiConfigLike(api_key=None)  # unset key
    keyless, sidecar = S.split_config_secrets(_config_to_kwargs(cfg))
    if keyless.get("api_key") is not None:
        _fail("empty api_key should stay None in keyless kwargs")
    if any(k.startswith(S.CFG_SECRET_PREFIX) for k in sidecar):
        _fail(f"empty secret should not ride the sidecar: {sidecar!r}")
    # reconstruction still works
    PiConfigLike(**keyless)
    print("PASS: test_empty_secret_field_dropped_cleanly")


if __name__ == "__main__":
    test_spec_is_keyless_and_key_roundtrips()
    test_api_key_env_not_captured_as_secret()
    test_empty_secret_field_dropped_cleanly()
    print("\nALL PASSED: _spec.json stays keyless; api_key round-trips via sidecar (6.2)")
