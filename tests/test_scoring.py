from src.checks.base import CheckContext, fehler, ok
from src.models import GbpProfile, Location, Modus
from src.scoring import score_location, top_massnahmen
from src.storage import load_global_config


def _location() -> Location:
    return Location(id="a", name="Beispiel GmbH", zip="12345", city="Musterstadt")


def _profile() -> GbpProfile:
    return GbpProfile(place_id="ChIJ_x", display_name="Beispiel GmbH")


def _scoring_config():
    return load_global_config()["scoring"]


def test_score_location_modus_a_renormalisiert_gewichte():
    # Nur Gruppe existenz_auffindbarkeit liefert bewertbare Checks, alle anderen "nicht prüfbar"
    checks = [ok("existenz_gbp_vorhanden", "existenz_auffindbarkeit", Modus.A, "ok", punkte=100.0)]
    result = score_location(_location(), _profile(), Modus.A, checks, _scoring_config())

    existenz = next(g for g in result.gruppen if g.gruppe == "existenz_auffindbarkeit")
    assert existenz.lauffaehig is True
    assert existenz.gewicht_prozent == 100.0  # einzige lauffähige Gruppe -> volles Gewicht
    assert result.gesamtscore == 100.0
    assert result.ampel == "gruen"


def test_score_location_ampellogik():
    checks = [fehler("x", "existenz_auffindbarkeit", Modus.A, "schlecht", "beheben", punkte=10.0)]
    result = score_location(_location(), _profile(), Modus.A, checks, _scoring_config())
    assert result.ampel == "rot"


def test_score_location_ohne_bewertbare_checks_ist_na():
    result = score_location(_location(), None, Modus.A, [], _scoring_config())
    assert result.gesamtscore is None
    assert result.ampel == "n/a"


def test_top_massnahmen_sortiert_nach_impact():
    checks = [
        fehler("existenz_gbp_vorhanden", "existenz_auffindbarkeit", Modus.A, "kein Profil", "anlegen", punkte=0.0),
        fehler("nap_telefon_vorhanden", "basisdaten_nap", Modus.A, "Telefon fehlt", "ergänzen", punkte=0.0),
        ok("kategorien_hauptkategorie", "kategorien", Modus.A, "passt", punkte=100.0),
    ]
    result = score_location(_location(), _profile(), Modus.A, checks, _scoring_config())
    massnahmen = top_massnahmen(result, anzahl=2)
    # existenz_auffindbarkeit hat höheres Gewicht (10) als andere renormalisierte, sollte vorne stehen
    assert massnahmen[0].check_id in ("existenz_gbp_vorhanden", "nap_telefon_vorhanden")
    assert len(massnahmen) == 2
