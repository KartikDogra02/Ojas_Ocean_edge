from enum import StrEnum


class Territory(StrEnum):
    NORTH_SEA = "north_sea"
    MEDITERRANEAN = "mediterranean"
    WEST_AFRICA = "west_africa"
    RED_SEA_SUEZ = "red_sea_suez"
    PERSIAN_GULF = "persian_gulf"
    INDIAN_SUBCONTINENT = "indian_subcontinent"
    STRAIT_OF_MALACCA = "strait_of_malacca"
    EAST_ASIA = "east_asia"
    AUSTRALIA_OCEANIA = "australia_oceania"
    GULF_OF_MEXICO = "gulf_of_mexico"
    CARIBBEAN_PANAMA = "caribbean_panama"
    BRAZIL = "brazil"
    GLOBAL_REMOTE = "global_remote"

    @property
    def label(self) -> str:
        return TERRITORY_LABELS[self]


TERRITORY_LABELS: dict[Territory, str] = {
    Territory.NORTH_SEA: "North Sea (UK/Norway/Netherlands)",
    Territory.MEDITERRANEAN: "Mediterranean (Greece/Italy/Spain/Malta)",
    Territory.WEST_AFRICA: "West Africa (Nigeria/Ghana/Angola)",
    Territory.RED_SEA_SUEZ: "Red Sea & Suez (Egypt/Saudi Arabia/Djibouti)",
    Territory.PERSIAN_GULF: "Persian Gulf (UAE/Qatar/Oman)",
    Territory.INDIAN_SUBCONTINENT: "Indian Subcontinent (India/Sri Lanka)",
    Territory.STRAIT_OF_MALACCA: "Strait of Malacca (Singapore/Malaysia/Indonesia)",
    Territory.EAST_ASIA: "East Asia (China/South Korea/Japan)",
    Territory.AUSTRALIA_OCEANIA: "Australia & Oceania",
    Territory.GULF_OF_MEXICO: "Gulf of Mexico (USA/Mexico)",
    Territory.CARIBBEAN_PANAMA: "Caribbean & Panama Canal",
    Territory.BRAZIL: "Brazil (Santos/Rio de Janeiro/Campos Basin)",
    Territory.GLOBAL_REMOTE: "Global / Remote Offshore",
}
