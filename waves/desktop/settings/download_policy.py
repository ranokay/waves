"""Schema rows for the one persisted policy store; edits use applySettings."""

from __future__ import annotations

import dataclasses

from waves.model.download_policy import (
    ADVANCED_BOUNDS,
    CROSS_PROVIDER_FIELDS,
    CROSS_PROVIDER_LABELS,
    POLICY_CHOICES,
    POLICY_LABELS,
    DownloadPolicies,
)


def policy_fields(policies: DownloadPolicies, provider_id: str = "") -> list[dict]:
    prefix = f"providers.{provider_id}" if provider_id else "shared"
    values = policies.providers.get(provider_id, {}) if provider_id else dataclasses.asdict(policies.shared)
    rows = []
    for name, label in POLICY_LABELS.items():
        # Existing shared audio/video controls are the default's sole writers.
        if not provider_id and name in ("audio_type", "video_quality"):
            continue
        value = values.get(name, "__inherit__")
        row = {
            "key": f"download_policies.{prefix}.{name}",
            "label": label,
            "help": "Captured for new download requests. Retry keeps the original rules. Routing and fulfillment capabilities determine which options can execute.",
            "type": "enum",
            "value": value,
        }
        if name in POLICY_CHOICES:
            options = [
                {"value": word, "label": word.replace("_", " ").capitalize() if word else "Use existing default"}
                for word in POLICY_CHOICES[name]
            ]
        elif name == "require_extras":
            if not provider_id:
                row["type"] = "bool"
                rows.append(row)
                continue
            row["value"] = str(value).lower() if isinstance(value, bool) else value
            options = [{"value": "true", "label": "Required"}, {"value": "false", "label": "Optional"}]
        else:
            row.update(
                type="str" if provider_id else "int",
                value=str(value) if provider_id and value != "__inherit__" else "" if provider_id else value,
                minimum=0,
                maximum=240,
            )
            row["help"] += " Leave empty to inherit." if provider_id else ""
            rows.append(row)
            continue
        if provider_id:
            options.insert(0, {"value": "__inherit__", "label": "Use shared policy"})
        row["options"] = options
        rows.append(row)
    return rows


def routing_fields(policies: DownloadPolicies) -> list[dict]:
    rows = [
        {
            "key": "download_policies.provider_priority",
            "label": "Provider preference order",
            "help": "Comma-separated provider IDs; source wins absent an eligible improvement. An order is a preference, never a pin.",
            "type": "str",
            "value": ", ".join(policies.provider_priority),
        },
        {
            "key": "download_policies.same_provider_fallback",
            "label": "Allow Auto engine fallback",
            "help": "Bounded recovery within the same provider, when supported. Explicit engine choices remain pinned unless Allow fallback is selected for the job.",
            "type": "bool",
            "value": policies.same_provider_fallback,
        },
    ]
    for key, label in zip(CROSS_PROVIDER_FIELDS, CROSS_PROVIDER_LABELS, strict=True):
        rows.append(
            {
                "key": f"download_policies.{key}",
                "label": label,
                "help": "Off by default. Captured independently; requires ready providers, high-confidence identity and preserved constraints. Fulfillment support is required.",
                "type": "bool",
                "value": getattr(policies, key),
            }
        )
    return rows


def engine_fields(policies: DownloadPolicies, provider_id: str) -> list[dict]:
    rows = []
    for operation in ("", "audio", "lyrics", "artwork"):
        key = f"operation_priority.{provider_id}.{operation}" if operation else f"engine_priority.{provider_id}"
        order = (
            policies.operation_priority.get(provider_id, {}).get(operation, ())
            if operation
            else policies.engine_priority.get(provider_id, ())
        )
        rows.append(
            {
                "key": f"download_policies.{key}",
                "label": f"{operation.capitalize()} engine preference order"
                if operation
                else "Engine preference order",
                "help": "Comma-separated engine IDs. Empty follows the provider's eligible Auto routes; operation orders override the general order. Recommendations require qualification.",
                "type": "str",
                "value": ", ".join(order),
            }
        )
    return rows


def advanced_fields(policies: DownloadPolicies) -> list[dict]:
    return [
        {
            "key": f"download_policies.{key}",
            "label": key.replace("_", " ").capitalize(),
            "help": "Captured recovery bound for engines implementing request recovery. Mandatory integrity checks retain their provider-owned limits.",
            "type": "int" if key == "attempt_limit" else "float",
            "value": getattr(policies, key),
            "minimum": bounds[0],
            "maximum": bounds[1],
            "step": 1,
        }
        for key, bounds in ADVANCED_BOUNDS.items()
    ]
