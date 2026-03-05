/// Market data bar
pub struct Bar {
    pub symbol: String,
    pub open: f64,
    pub high: f64,
    pub low: f64,
    pub close: f64,
    pub volume: u64,
}

/// Signal output from a strategy
pub struct Signal {
    pub direction: String,
    pub strength: f64,
}

impl Bar {
    pub fn new(symbol: &str, open: f64, high: f64, low: f64, close: f64, volume: u64) -> Self {
        Bar {
            symbol: symbol.to_string(),
            open, high, low, close, volume,
        }
    }

    pub fn spread(&self) -> f64 {
        self.high - self.low
    }

    pub fn change_pct(&self) -> f64 {
        if self.open == 0.0 { return 0.0; }
        (self.close - self.open) / self.open
    }
}

impl Signal {
    pub fn is_actionable(&self) -> bool {
        self.direction != "hold" && self.strength > 0.0
    }
}

pub fn validate_bar(bar: &Bar) -> Vec<String> {
    let mut errors = Vec::new();
    if bar.high < bar.low {
        errors.push("high < low".to_string());
    }
    errors
}
