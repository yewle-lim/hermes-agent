"""LID→phone resolution must see the session dir of the profile that OWNS the bridge (#135139).

Under the multiplex fold the WhatsApp bridge is shared ingress owned by the **default** profile:
it writes ``lid-mapping-*.json`` into ``<hermes-root>/platforms/whatsapp/session``. A message handled
by a *secondary* profile resolved ``get_hermes_dir(..., "whatsapp/session")`` against that profile's
home — ``<root>/profiles/<name>/platforms/whatsapp/session``, which never exists — so the alias set
collapsed to the LID itself, an allowlisted *phone number* could not match, and the sender was denied
with a pairing prompt even though they were explicitly allowlisted.

The resolver now also consults the host/default profile's session directory, nearest dir first.
"""

import json
from pathlib import Path

from hermes_constants import (get_default_hermes_root, reset_hermes_home_override,
                              set_hermes_home_override)

PHONE = "351912345678"
LID = "77214955630717"


def _write_mappings(session_dir: Path, phone: str = PHONE, lid: str = LID) -> None:
    """Mirror what the JS bridge writes: phone→lid and lid→phone (reverse)."""
    session_dir.mkdir(parents=True, exist_ok=True)
    (session_dir / f"lid-mapping-{phone}.json").write_text(json.dumps(lid), encoding="utf-8")
    (session_dir / f"lid-mapping-{lid}_reverse.json").write_text(
        json.dumps(phone), encoding="utf-8"
    )


def _as_secondary_profile(tmp_path, monkeypatch):
    """Be the secondary profile of a multiplexed host; return (root, token)."""
    root = tmp_path / ".hermes"
    profile_home = root / "profiles" / "secondary"
    profile_home.mkdir(parents=True)
    monkeypatch.setenv("HERMES_HOME", str(profile_home))
    token = set_hermes_home_override(str(profile_home))
    return root, token


def test_lid_resolves_via_the_host_profiles_session_dir(tmp_path, monkeypatch):
    """Mappings live only where the bridge wrote them: the host/default profile's session dir."""
    from gateway.whatsapp_identity import expand_whatsapp_aliases

    root, token = _as_secondary_profile(tmp_path, monkeypatch)
    try:
        _write_mappings(root / "platforms" / "whatsapp" / "session")
        aliases = expand_whatsapp_aliases(LID)
    finally:
        reset_hermes_home_override(token)

    assert aliases == {LID, PHONE}


def test_lid_resolves_via_the_host_profiles_legacy_session_dir(tmp_path, monkeypatch):
    """Same, on the legacy layout: ``<root>/whatsapp/session`` (no ``platforms/``)."""
    from gateway.whatsapp_identity import expand_whatsapp_aliases

    root, token = _as_secondary_profile(tmp_path, monkeypatch)
    try:
        _write_mappings(root / "whatsapp" / "session")
        aliases = expand_whatsapp_aliases(LID)
    finally:
        reset_hermes_home_override(token)

    assert PHONE in aliases


def test_profiles_own_session_dir_wins_over_the_hosts(tmp_path, monkeypatch):
    """Both dirs hold a mapping for the same LID: the active profile's own file is authoritative."""
    from gateway.whatsapp_identity import expand_whatsapp_aliases

    local_phone = "351900000001"
    root, token = _as_secondary_profile(tmp_path, monkeypatch)
    try:
        profile_home = Path(get_default_hermes_root()) / "profiles" / "secondary"
        _write_mappings(profile_home / "platforms" / "whatsapp" / "session", phone=local_phone)
        _write_mappings(root / "platforms" / "whatsapp" / "session", phone=PHONE)
        aliases = expand_whatsapp_aliases(LID)
    finally:
        reset_hermes_home_override(token)

    assert local_phone in aliases
    assert PHONE not in aliases


def test_unmapped_lid_still_degrades_to_itself(tmp_path, monkeypatch):
    """No mapping files anywhere: the alias set stays the LID alone (no invented identity)."""
    from gateway.whatsapp_identity import expand_whatsapp_aliases

    _root, token = _as_secondary_profile(tmp_path, monkeypatch)
    try:
        aliases = expand_whatsapp_aliases(LID)
    finally:
        reset_hermes_home_override(token)

    assert aliases == {LID}


def test_canonical_id_is_the_phone_when_only_the_host_has_mappings(tmp_path, monkeypatch):
    """The session-key canonicaliser follows the same resolution, so keys stay stable."""
    from gateway.whatsapp_identity import canonical_whatsapp_identifier

    root, token = _as_secondary_profile(tmp_path, monkeypatch)
    try:
        _write_mappings(root / "platforms" / "whatsapp" / "session")
        canonical = canonical_whatsapp_identifier(f"{LID}@lid")
    finally:
        reset_hermes_home_override(token)

    assert canonical == PHONE
