"""Provider card and status payloads shared by settings and live surfaces.

These builders take provider descriptors and explicit state; they own no Qt
objects or bridge state. Session lifecycle stays in the application bridge.
"""

from __future__ import annotations

from waves.providers import StatusKind


def apple_status(
    enabled: bool,
    *,
    runtime_ready: bool = False,
    signed_in: bool = False,
    needs_attention: bool = False,
    cookies_ready: bool = False,
) -> dict:
    """The Apple status light's ``{"state", "word"}`` (spec §9.2.3).

    One source for both the bridge slot (the page's live mirror) and the
    schema's baked value, so the two can never disagree. The light has five
    states: ``off`` while the component is disabled, ``not_set_up`` once
    enabled but with neither runtime nor sign-in, ``runtime_ready`` when
    the managed N_m3u8DL-RE is provisioned, ``signed_in`` when a verified
    cookies export (cookies tier, no runtime needed) or a wrapper session
    unlocks downloads, and ``needs_attention`` when a saved cookies path
    or runtime needs repair. Precedence is needs_attention > signed_in >
    runtime_ready > not_set_up > off. ``cookies_ready`` without
    ``signed_in`` still lights ``signed_in``: the cookies tier unlocks
    AAC 256 + Atmos with no runtime at all (spec §2).
    """
    # Local import avoids a module-import cycle in tests that stub the bridge.
    from waves.providers.apple.runtime import describe_setup

    described = describe_setup(
        enabled=bool(enabled),
        runtime_ready=bool(runtime_ready),
        signed_in=bool(signed_in),
        needs_attention=bool(needs_attention),
        cookies_ready=bool(cookies_ready),
    )
    return {"state": described["state"], "word": described["word"]}


def provider_session_field(descriptor, logged_in: bool) -> dict:
    """The status row a session-kind provider card carries.

    One shape for every provider: the row reports the session and offers the
    matching action, so a second session-kind provider renders its card
    without a QML or schema branch. It stages no edit.
    """
    return {
        "key": f"provider_{descriptor.id}_session",
        "provider": descriptor.id,
        "label": "Session",
        "help": (
            f"The {descriptor.name} account Waves is working from. This row "
            "reports the session and offers the matching action: "
            "sign in while signed out, sign out while signed in."
        ),
        "type": "status",
        "value": "signed_in" if logged_in else "not_signed_in",
        "word": "Signed in" if logged_in else "Not signed in",
        "actions": [
            {
                "label": "Sign out" if logged_in else "Sign in",
                "action": f"{descriptor.id}_{'signout' if logged_in else 'signin'}",
            }
        ],
    }


def provider_card(provider) -> dict:
    """One Providers card, composed from the provider's descriptor.

    The card's identity, blurb and field list are the provider's; the live
    data behind those keys stays the bridge's (built where the probes live).
    A session-kind provider's generated status row leads the card even when
    its descriptor does not list the key, so a provider that contributes
    nothing but identity still renders.
    """
    descriptor = provider.descriptor()
    fields = list(descriptor.settings_fields)
    if descriptor.status_kind == StatusKind.SESSION:
        session_key = f"provider_{descriptor.id}_session"
        if session_key not in fields:
            fields.insert(0, session_key)
    return {
        "name": descriptor.name,
        "id": f"providers_{descriptor.id}",
        "desc": descriptor.card_desc,
        "logo": descriptor.logo,
        "logo_width": descriptor.logo_width,
        "logo_header_width": descriptor.logo_header_width,
        "logo_header_height": descriptor.logo_header_height,
        "fields": fields,
    }
