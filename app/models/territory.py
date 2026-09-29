from app.models.common import LabeledEnum


class Territory(LabeledEnum):
    NORTH_SEA = "north_sea", "North Sea (UK/Norway/Netherlands)"
    MEDITERRANEAN = "mediterranean", "Mediterranean (Greece/Italy/Spain/Malta)"
    WEST_AFRICA = "west_africa", "West Africa (Nigeria/Ghana/Angola)"
    RED_SEA_SUEZ = "red_sea_suez", "Red Sea & Suez (Egypt/Saudi Arabia/Djibouti)"
    PERSIAN_GULF = "persian_gulf", "Persian Gulf (UAE/Qatar/Oman)"
    INDIAN_SUBCONTINENT = "indian_subcontinent", "Indian Subcontinent (India/Sri Lanka)"
    STRAIT_OF_MALACCA = "strait_of_malacca", "Strait of Malacca (Singapore/Malaysia/Indonesia)"
    EAST_ASIA = "east_asia", "East Asia (China/South Korea/Japan)"
    AUSTRALIA_OCEANIA = "australia_oceania", "Australia & Oceania"
    GULF_OF_MEXICO = "gulf_of_mexico", "Gulf of Mexico (USA/Mexico)"
    CARIBBEAN_PANAMA = "caribbean_panama", "Caribbean & Panama Canal"
    BRAZIL = "brazil", "Brazil (Santos/Rio de Janeiro/Campos Basin)"
    GLOBAL_REMOTE = "global_remote", "Global / Remote Offshore"
