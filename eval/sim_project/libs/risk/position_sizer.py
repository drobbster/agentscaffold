"""Position sizing calculations."""


class PositionSizer:
    """Calculates position sizes based on signals and portfolio constraints."""

    def calculate(self, signal: dict, portfolio_value: float, max_pct: float) -> float:
        strength = signal.get("strength", 0.0)
        max_size = portfolio_value * max_pct
        return max_size * strength

    def kelly_criterion(self, win_rate: float, win_loss_ratio: float) -> float:
        """Calculate Kelly criterion fraction."""
        if win_loss_ratio == 0:
            return 0.0
        return win_rate - (1 - win_rate) / win_loss_ratio
