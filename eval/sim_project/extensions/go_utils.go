package extensions

// MarketData holds normalized OHLCV data
type MarketData struct {
	Symbol    string
	Open      float64
	High      float64
	Low       float64
	Close     float64
	Volume    int64
	Timestamp string
}

// Portfolio tracks positions and value
type Portfolio struct {
	Positions map[string]float64
	Cash      float64
}

// NewPortfolio creates a portfolio with initial cash
func NewPortfolio(cash float64) *Portfolio {
	return &Portfolio{
		Positions: make(map[string]float64),
		Cash:      cash,
	}
}

// TotalValue computes portfolio value given prices
func (p *Portfolio) TotalValue(prices map[string]float64) float64 {
	total := p.Cash
	for symbol, qty := range p.Positions {
		if price, ok := prices[symbol]; ok {
			total += qty * price
		}
	}
	return total
}

// ValidateData checks data quality
func ValidateData(data MarketData) []string {
	var errors []string
	if data.High < data.Low {
		errors = append(errors, "high < low")
	}
	if data.Volume < 0 {
		errors = append(errors, "negative volume")
	}
	return errors
}
