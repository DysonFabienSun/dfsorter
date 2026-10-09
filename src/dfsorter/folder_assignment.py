MODES = {
    "automatic": "Detect from folder names",
    "single_game": "Assign one game",
    "unclassified": "Leave unclassified",
}


def validate_assignment(mode=None, game=None, games=None):
    mode = mode or ("single_game" if game else "automatic")
    if mode not in MODES:
        raise ValueError("Unknown game assignment mode")
    if mode == "single_game":
        if not game:
            raise ValueError("Select a game for this capture folder")
        if games is not None and game not in games:
            raise ValueError(f"Capture folder game configuration unavailable: {game}")
    else:
        game = None
    return mode, game


def assigned_game(detected, mode, game):
    if mode == "single_game":
        return game
    return detected if mode == "automatic" else None


def assignment_summary(folder):
    mode, game = validate_assignment(folder.get("assignment_mode"), folder.get("forced_game"))
    return f"Single game · {game}" if mode == "single_game" else {
        "automatic": "Automatic", "unclassified": "Unclassified",
    }[mode]
