"""NHL team abbreviations -> full names (shared by the dashboard and injury matching)."""

TEAMS = {
    "ANA": "Anaheim Ducks", "ARI": "Arizona Coyotes", "BOS": "Boston Bruins", "BUF": "Buffalo Sabres",
    "CGY": "Calgary Flames", "CAR": "Carolina Hurricanes", "CHI": "Chicago Blackhawks", "COL": "Colorado Avalanche",
    "CBJ": "Columbus Blue Jackets", "DAL": "Dallas Stars", "DET": "Detroit Red Wings", "EDM": "Edmonton Oilers",
    "FLA": "Florida Panthers", "LAK": "Los Angeles Kings", "MIN": "Minnesota Wild", "MTL": "Montréal Canadiens",
    "NSH": "Nashville Predators", "NJD": "New Jersey Devils", "NYI": "New York Islanders", "NYR": "New York Rangers",
    "OTT": "Ottawa Senators", "PHI": "Philadelphia Flyers", "PIT": "Pittsburgh Penguins", "SJS": "San Jose Sharks",
    "SEA": "Seattle Kraken", "STL": "St. Louis Blues", "TBL": "Tampa Bay Lightning", "TOR": "Toronto Maple Leafs",
    "UTA": "Utah Mammoth", "VAN": "Vancouver Canucks", "VGK": "Vegas Golden Knights", "WSH": "Washington Capitals",
    "WPG": "Winnipeg Jets",
}

COLORS = {  # primary team colors (dashboard 'Key players' boxes)
    "ANA": "#FC4C02", "ARI": "#8C2633", "BOS": "#FFB81C", "BUF": "#003087", "CGY": "#C8102E", "CAR": "#CE1126",
    "CHI": "#CF0A2C", "COL": "#6F263D", "CBJ": "#002654", "DAL": "#006847", "DET": "#CE1126", "EDM": "#041E42",
    "FLA": "#C8102E", "LAK": "#111111", "MIN": "#154734", "MTL": "#AF1E2D", "NSH": "#FFB81C", "NJD": "#CE1126",
    "NYI": "#00539B", "NYR": "#0038A8", "OTT": "#C52032", "PHI": "#F74902", "PIT": "#FCB514", "SJS": "#006D75",
    "SEA": "#001628", "STL": "#002F87", "TBL": "#002868", "TOR": "#00205B", "UTA": "#6CACE4", "VAN": "#00205B",
    "VGK": "#B4975A", "WSH": "#C8102E", "WPG": "#041E42",
}

SECONDARY = {  # used for the second (home) team when both primaries look alike
    "ANA": "#B9975B", "ARI": "#E2D6B5", "BOS": "#111111", "BUF": "#FFB81C", "CGY": "#F1BE48", "CAR": "#111111",
    "CHI": "#111111", "COL": "#236192", "CBJ": "#CE1126", "DAL": "#8F8F8C", "DET": "#FFFFFF", "EDM": "#FF4C00",
    "FLA": "#041E42", "LAK": "#A2AAAD", "MIN": "#EAAA00", "MTL": "#FFFFFF", "NSH": "#041E42", "NJD": "#111111",
    "NYI": "#F47D30", "NYR": "#CE1126", "OTT": "#111111", "PHI": "#111111", "PIT": "#111111", "SJS": "#EA7200",
    "SEA": "#99D9D9", "STL": "#FCB514", "TBL": "#FFFFFF", "TOR": "#FFFFFF", "UTA": "#010101", "VAN": "#FFFFFF",
    "VGK": "#333F42", "WSH": "#041E42", "WPG": "#AC162C",
}
