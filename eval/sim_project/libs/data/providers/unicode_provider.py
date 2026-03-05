"""Provider with unicode identifiers for edge case testing."""


class DatenAnbieter:
    """Datenanbieter mit Unicode-Bezeichnern (German: data provider with unicode identifiers)."""

    def __init__(self):
        self.beschreibung = "Marktdaten-Provider"
        self.wahrung = "EUR"

    def hole_daten(self, symbol: str) -> dict:
        """Fetch data -- method name uses non-ASCII (umlaut in German)."""
        return {
            "symbol": symbol,
            "preis": 42.0,
            "wahrung": self.wahrung,
            "notiz": "Keine besonderen Vorkommnisse",
        }

    def validiere(self, daten: dict) -> list[str]:
        fehler = []
        if "preis" not in daten:
            fehler.append("Preis fehlt")
        return fehler
