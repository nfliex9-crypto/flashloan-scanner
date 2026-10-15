"""Deterministic risk and funding-rule engine. No external IO and no brokerage access.

IMPORTANT: Policy values are input-specific; do not represent certification of any firm.
All amounts are in account currency. All clock calculations use a named timezone.
"""
from __future__ import annotations
from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal, ROUND_FLOOR
from typing import Literal
from zoneinfo import ZoneInfo

D = lambda x: Decimal(str(x))
Mode = Literal["static", "eod_trailing", "intraday_trailing"]

@dataclass(frozen=True)
class RuleProfile:
    name: str
    initial_balance: Decimal
    max_loss: Decimal
    profit_target: Decimal
    mode: Mode = "eod_trailing"
    daily_loss_limit: Decimal | None = None
    consistency_fraction: Decimal | None = None
    lock_floor_at_initial: bool = True
    max_contracts: int = 4
    session_timezone: str = "America/Chicago"
    reset_hour: int = 17
    def __post_init__(self):
        if self.initial_balance <= 0 or self.max_loss <= 0 or self.profit_target <= 0:
            raise ValueError("Initial balance, max loss and target must be positive")
        if self.daily_loss_limit is not None and self.daily_loss_limit <= 0:
            raise ValueError("Daily limit must be positive")
        if self.consistency_fraction is not None and not (0 < self.consistency_fraction <= 1):
            raise ValueError("Consistency must be between 0 and 1")
        if self.mode not in ("static", "eod_trailing", "intraday_trailing"):
            raise ValueError("Unknown drawdown mode")
        if not (0 <= self.reset_hour < 24) or self.max_contracts < 1:
            raise ValueError("Invalid session or contract limit")
        ZoneInfo(self.session_timezone)

@dataclass(frozen=True)
class Contract:
    symbol: str
    tick_size: Decimal
    tick_value: Decimal
    roundtrip_fee: Decimal
    def __post_init__(self):
        if self.tick_size <= 0 or self.tick_value <= 0 or self.roundtrip_fee < 0:
            raise ValueError("Invalid contract specification")

@dataclass(frozen=True)
class TradeDecision:
    approved: bool
    quantity: int
    maximum_loss: Decimal
    reason: str

@dataclass
class AccountState:
    rules: RuleProfile
    balance: Decimal = field(init=False)
    equity: Decimal = field(init=False)
    eod_high: Decimal = field(init=False)
    intraday_high: Decimal = field(init=False)
    day_start_equity: Decimal = field(init=False)
    daily_realized: dict[str, Decimal] = field(default_factory=dict)
    current_session: str | None = None
    breached: bool = False

    def __post_init__(self):
        x = self.rules.initial_balance
        self.balance = x
        self.equity = x
        self.eod_high = x
        self.intraday_high = x
        self.day_start_equity = x

    def session_key(self, timestamp: datetime) -> str:
        if timestamp.tzinfo is None:
            raise ValueError("Timestamp must be timezone-aware")
        local = timestamp.astimezone(ZoneInfo(self.rules.session_timezone))
        if local.hour < self.rules.reset_hour:
            from datetime import timedelta
            local = local - timedelta(days=1)
        return local.date().isoformat()

    def start_event(self, timestamp: datetime) -> None:
        key = self.session_key(timestamp)
        if self.current_session is not None and key < self.current_session:
            raise ValueError("Out-of-order session event")
        if key != self.current_session:
            if self.current_session is not None:
                # The previous observed balance is not independently verified as
                # the firm's official end-of-day balance.
                self.eod_high = max(self.eod_high, self.balance)
            self.day_start_equity = self.equity
            self.current_session = key
            self.daily_realized.setdefault(key, D(0))

    @property
    def floor(self) -> Decimal:
        r = self.rules
        if r.mode == "static":
            return r.initial_balance - r.max_loss
        peak = self.eod_high if r.mode == "eod_trailing" else self.intraday_high
        result = peak - r.max_loss
        return min(result, r.initial_balance) if r.lock_floor_at_initial else result

    @property
    def cushion(self) -> Decimal:
        return self.equity - self.floor

    @property
    def day_cushion(self) -> Decimal:
        r = self.rules
        if r.daily_loss_limit is None:
            return D("Infinity")
        return self.equity - (self.day_start_equity - r.daily_loss_limit)

    def observe_equity(self, timestamp: datetime, unrealized_pnl) -> bool:
        self.start_event(timestamp)
        self.equity = self.balance + D(unrealized_pnl)
        self.intraday_high = max(self.intraday_high, self.equity)
        if self.cushion <= 0 or self.day_cushion <= 0:
            self.breached = True
        return not self.breached

    def close_trade(self, timestamp: datetime, realized_pnl) -> bool:
        self.start_event(timestamp)
        pnl = D(realized_pnl)
        self.balance += pnl
        self.equity = self.balance
        self.intraday_high = max(self.intraday_high, self.equity)
        assert self.current_session is not None
        self.daily_realized[self.current_session] += pnl
        if self.cushion <= 0 or self.day_cushion <= 0:
            self.breached = True
        return not self.breached

    @property
    def net_profit(self) -> Decimal:
        return self.balance - self.rules.initial_balance

    @property
    def largest_winning_day(self) -> Decimal:
        return max([D(0), *self.daily_realized.values()])

    @property
    def consistency_ratio(self) -> Decimal | None:
        if self.net_profit <= 0:
            return None
        return self.largest_winning_day / self.net_profit

    @property
    def target_met(self) -> bool:
        return self.net_profit >= self.rules.profit_target

    @property
    def eligible(self) -> bool:
        if self.breached or not self.target_met:
            return False
        cap = self.rules.consistency_fraction
        return cap is None or (self.consistency_ratio is not None and self.consistency_ratio <= cap)


def size_position(state: AccountState, contract: Contract, stop_distance, risk_budget,
                  slippage_ticks=1, safety_fraction=D("0.20")) -> TradeDecision:
    """Pre-order check against both maximum and daily loss limits.

    No order is placed. All adverse costs are charged *per contract*, including
    round-trip fees and a one-sided stop slippage allowance. The amount is a
    conservative sizing estimate, not a fill guarantee.
    """
    if state.breached:
        return TradeDecision(False, 0, D(0), "ACCOUNT_BREACHED")
    if state.current_session is None:
        return TradeDecision(False, 0, D(0), "NO_SESSION_SNAPSHOT")
    if state.cushion <= 0 or state.day_cushion <= 0:
        return TradeDecision(False, 0, D(0), "LIMIT_REACHED")
    distance = D(stop_distance)
    budget = D(risk_budget)
    slip = D(slippage_ticks)
    fraction = D(safety_fraction)
    if distance <= 0 or budget <= 0 or slip < 0 or not 0 < fraction < 1:
        return TradeDecision(False, 0, D(0), "INVALID_RISK_INPUT")
    exact_ticks = distance / contract.tick_size
    if exact_ticks != exact_ticks.to_integral_value():
        return TradeDecision(False, 0, D(0), "INVALID_TICK_ALIGNMENT")
    per_contract = (exact_ticks + slip) * contract.tick_value + contract.roundtrip_fee
    permitted = min(budget, state.cushion * fraction, state.day_cushion * fraction)
    qty = min(state.rules.max_contracts, int((permitted / per_contract).to_integral_value(rounding=ROUND_FLOOR)))
    if qty < 1:
        return TradeDecision(False, 0, D(0), "INSUFFICIENT_RISK_BUDGET")
    return TradeDecision(True, qty, per_contract * qty, "RISK_APPROVED")


def example_profile() -> RuleProfile:
    """Unverified illustration only; users must configure the specific account."""
    return RuleProfile(name="Illustrative 50K evaluation", initial_balance=D(50000),
        max_loss=D(2000), profit_target=D(3000), daily_loss_limit=D(1200),
        consistency_fraction=None, mode="eod_trailing")
