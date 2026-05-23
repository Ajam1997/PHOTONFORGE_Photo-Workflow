from pathlib import Path
from scripts.doc_parser import parse_user_needs, parse_architecture

FIXTURES = Path(__file__).parent / "fixtures"


def test_parse_user_needs_count():
    items = parse_user_needs(FIXTURES / "sample_user_needs.md")
    assert len(items) == 2


def test_parse_user_needs_fields():
    items = parse_user_needs(FIXTURES / "sample_user_needs.md")
    un001 = next(i for i in items if i["id"] == "UN-001")
    assert un001["title"] == "The system installs without errors."
    assert un001["acceptance"] == "pip install -e . exits 0."
    assert un001["kpm"] == "NONE"
    assert un001["stage"] == 1
    assert un001["status"] == "DEFINED"


def test_parse_user_needs_verified_status():
    items = parse_user_needs(FIXTURES / "sample_user_needs.md")
    un010 = next(i for i in items if i["id"] == "UN-010")
    assert un010["status"] == "VERIFIED"


def test_parse_architecture_frs():
    data = parse_architecture(FIXTURES / "sample_architecture.md")
    assert len(data["functional_requirements"]) == 2
    fr11 = next(r for r in data["functional_requirements"] if r["id"] == "FR-1.1")
    assert fr11["description"] == "Automated Media Ingest"
    assert fr11["implementation"] == "udev-triggered rsync"


def test_parse_architecture_nfrs():
    data = parse_architecture(FIXTURES / "sample_architecture.md")
    assert len(data["non_functional_requirements"]) == 2
    nfr = next(r for r in data["non_functional_requirements"] if r["id"] == "NFR-2.1")
    assert nfr["description"] == "Internet Independence"
    assert "offline" in nfr["specification"]


def test_parse_architecture_kpms():
    data = parse_architecture(FIXTURES / "sample_architecture.md")
    assert len(data["kpms"]) == 2
    kpm = next(k for k in data["kpms"] if k["id"] == "KPM-1.1")
    assert kpm["metric"] == "Ingest Latency"
    assert kpm["target"] == ">= 80% USB 3.0 bandwidth"
    assert kpm["owner"] == "@devops"
    assert kpm["verified_by"] == "@verification"
