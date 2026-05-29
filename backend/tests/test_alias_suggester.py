from app.features.rag.services.alias_suggester import (
    AliasObservation,
    canonicalize_alias,
    observations_from_file,
    suggest_aliases,
)


def test_canonicalize_alias_strips_legal_suffixes_and_normalizes_known_vendor() -> None:
    assert canonicalize_alias("Teradyne Inc.", "vendor") == "teradyne"
    assert canonicalize_alias("PCI-SIG", "vendor") == "pci_sig"


def test_observations_skip_boilerplate_and_keep_proper_terms() -> None:
    observations = observations_from_file(
        filename="PCIe-Link-Training.pdf",
        text="Copyright all rights reserved. PCI-SIG defines LTSSM for PCIe.",
        vendor="PCI SIG",
        platform="PCIe 5.0",
        knowledge_type="Specification",
    )
    values = [obs.value.casefold() for obs in observations]

    assert "all rights reserved" not in values
    assert "pci-sig" in values
    assert "ltssm" in values
    assert any(
        obs.field == "platform" and obs.value == "PCIe 5.0" for obs in observations
    )


def test_suggest_aliases_groups_variants_by_canonical() -> None:
    suggestions = suggest_aliases(
        [
            AliasObservation("vendor", "PCI SIG", "a.pdf"),
            AliasObservation("vendor", "PCI-SIG", "b.pdf"),
            AliasObservation("vendor", "PCI-SIG", "c.pdf"),
            AliasObservation("proper_noun", "all rights reserved", "d.pdf"),
        ],
        min_count=2,
    )

    assert [s.as_dict() for s in suggestions] == [
        {
            "field": "vendor",
            "canonical": "pci_sig",
            "aliases": ["PCI-SIG", "PCI SIG"],
            "count": 3,
            "examples": ["a.pdf", "b.pdf", "c.pdf"],
        }
    ]
