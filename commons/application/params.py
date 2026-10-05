"""The settings of a society, in groups, each read only by the parts that need it:

    run         seed, reputation on or off (the control run), signature checks
    money       the treasury, purses, the floor, upkeep, the economy and its grants, quality pay, the daily ceiling
    market      jobs: how many, how big, their deadlines, claims and bonds, grading
    contracts   the contract-net: who may bid, deadlines, advances, audits and disputes
    ventures    proposals co-ops make for themselves
    population  members, co-ops, spawn, merge, fork, learn
    knowledge   publishing playbooks
    trust       reputation decay, gossip, bus allowances
    runtime     how much runs at once
    storage     where records go and how long they're kept

`Params(**flat)` takes every setting by its own name (packs and tests set them that way) and is frozen; code reads them
by group: `params.market.job_ttl`. Packs override the defaults (`Pack.params` for scripted runs, `Pack.live` for live).
"""

from __future__ import annotations

from dataclasses import dataclass, field, fields

from commons.domain.money import Micros


# One frozen dataclass per group: code reads `params.<group>.<name>`. Their fields are the flat settings' (below);
# tests/application/test_params.py checks every flat setting is in exactly one group, with the same type.
@dataclass(frozen=True)
class RunConfig:
    """The run settings."""
    seed: int
    reputation: bool
    verify: bool


@dataclass(frozen=True)
class MoneyConfig:
    """The money settings."""
    treasury_seed: Micros
    treasury_reserve: Micros
    purse_seed: Micros
    basic_budget: Micros
    floor_cap: Micros
    upkeep: Micros
    actions_per_member: int
    economy: str
    grant_budget: Micros
    grant_cap_cycles: int
    quality_pay: float
    daily_ceiling: Micros
    work_cost: Micros


@dataclass(frozen=True)
class MarketConfig:
    """The market settings."""
    jobs_per_cycle: int
    job_reward: Micros
    parts_per_job: int
    board_ttl: int
    job_ttl: int
    claim_allocation: bool
    claim_bond: float
    pass_score: float
    grade_retries: int
    grade_cost: Micros
    grader_reviews: bool


@dataclass(frozen=True)
class ContractsConfig:
    """The contracts settings."""
    bid_floor: float
    sub_share: float
    advance_frac: float
    bid_window: int
    deliver_ttl: int
    review_ttl: int
    audit_cost: Micros
    dispute_window: int


@dataclass(frozen=True)
class VenturesConfig:
    """The ventures settings."""
    venture_fee: Micros
    venture_budget: int
    venture_min_score: int


@dataclass(frozen=True)
class PopulationConfig:
    """The population settings."""
    max_members: int
    max_communities: int
    spawn_fee: Micros
    spawn_window: int
    merge_window: int
    charter_window: int
    fork_good_keep: float
    learn_cost: Micros
    learn_playbook_discount: float
    learn_royalty: float


@dataclass(frozen=True)
class KnowledgeConfig:
    """The knowledge settings."""
    publish_cost: Micros


@dataclass(frozen=True)
class TrustConfig:
    """The trust settings."""
    gossip_every: int
    gossip_fanout: int
    base_allowance: int
    decay: float


@dataclass(frozen=True)
class RuntimeConfig:
    """The runtime settings."""
    parallel_turns: bool
    parallel_workers: int
    grading_workers: int


@dataclass(frozen=True)
class StorageConfig:
    """The storage settings."""
    ledger_path: str
    journal_keep: int
    events_keep: int
    activity_keep: int
    activity_path: str | None
    retain: int
    outputs_keep: int

@dataclass(frozen=True)
class Params:
    seed: int = 0
    reputation: bool = True  # False = the control run: primes can't tell bidders apart
    treasury_seed: Micros = 2_000_000
    treasury_reserve: Micros = 2_000_000  # the treasury stops taking its 20% at this balance
    purse_seed: Micros = 150_000
    basic_budget: Micros = 3_000  # per cycle, to communities whose purse is below floor_cap
    floor_cap: Micros = 8_000  # two cycles of one member's upkeep
    upkeep: Micros = 4_000  # per member, per cycle
    actions_per_member: int = 2
    jobs_per_cycle: int = 2
    job_reward: Micros = 80_000
    parts_per_job: int = 2
    work_cost: Micros = 10_000  # what a scripted community spends producing one part
    grade_cost: Micros = 2_000  # notional treasury cost per graded part (StubGrader)
    # Reviews (your decision, 26 Sep, option B): the grader judges every delivery against the part's rubric.
    # Pass = the prime pays the rest; fail = rejected. The grade is reused when the job is graded. The prime
    # had a conflict of interest (rejecting saves money) and LLM primes rejected good work. False restores
    # prime reviews and disputes.
    grader_reviews: bool = True
    # K2, tempo and efficiency: no rule may reward being first.
    # Claims are registered during a cycle and allocated at its end: most trusted, then best fit, then least
    # loaded; ties by a draw seeded from the job. The winner posts a bond (a share of the reward), returned when
    # the job is paid and forfeited to the treasury if it fails, so claiming what you can't finish costs money.
    claim_allocation: bool = True
    claim_bond: float = 0.1
    # Pay scales with quality: this share of the reward depends on the mean part score (1.0 pays in full, 0.5
    # pays 1 - share/2). Every part must still pass. 0 = the old flat reward.
    quality_pay: float = 0.5
    venture_fee: Micros = 5_000  # paid to the treasury when proposing a venture (deters spam)
    venture_budget: int = 2  # ventures the market will take on per cycle, best-scored first
    venture_min_score: int = 5  # appraisals below this are worth nothing
    grade_retries: int = 3  # cycles a complete job waits for an unavailable grader before it fails
    # K4: the economy. "market" pays each passing job its reward; "grant" shares a fixed budget per cycle among
    # passing work by value (see the module docstring). A pack sets these.
    economy: str = "market"
    grant_budget: Micros = 0
    grant_cap_cycles: int = 3  # budgets the pool may bank when too little work passes
    outputs_keep: int = 200  # paid work kept in memory for the scorecard (the full record is in the activity log)
    # The world refuses bids (and awards) from anyone below this line, in the commons' pooled standing or in
    # the prime's own record of them for that capability. A rule, not a judgement: in the 1.5 runs LLM primes
    # kept hiring a known defector whose standing had fallen to 0.17.
    bid_floor: float = 0.35
    pass_score: float = 0.5  # every part must grade at least this for the market to pay
    sub_share: float = 0.4  # of job reward a scripted prime offers for each part it lacks
    advance_frac: float = 0.5
    board_ttl: int = 3  # cycles a job stays on the board
    job_ttl: int = 8  # cycles from claim to submission
    bid_window: int = 3  # cycles an announcement stays open
    deliver_ttl: int = 3
    review_ttl: int = 2
    publish_cost: Micros = 15_000
    gossip_every: int = 5
    gossip_fanout: int = 3
    base_allowance: int = 12
    decay: float = 0.995
    daily_ceiling: Micros = 10**12
    verify: bool = True
    ledger_path: str = ":memory:"  # a file under runs/ keeps long runs out of RAM
    journal_keep: int = 20
    events_keep: int = 50
    # Let communities think at the same time: model calls run in parallel, but every action takes the
    # world's lock, so state changes one action at a time. Off by default: scripted runs stay
    # deterministic. The catch until K2: when two communities want the same job, whoever's model
    # answers first gets it, which is a small reward for speed.
    parallel_turns: bool = False
    parallel_workers: int = 4
    # model calls for grading and appraisal at once (outside the lock). Verdicts are applied in a fixed order,
    # so results don't depend on which call finishes first. 1 for scripted runs; `commons run` uses 4.
    grading_workers: int = 1
    activity_keep: int = 2000  # entries of the activity log kept in memory
    activity_path: str | None = None  # also append every entry to this JSONL file
    retain: int = 20  # cycles a closed job or contract stays visible before it's dropped
    # population and capabilities (commons/application/population.py)
    max_members: int = 7
    max_communities: int = 12
    spawn_fee: Micros = 300_000
    spawn_window: int = 3
    merge_window: int = 3
    charter_window: int = 3  # cycles other co-ops have to comment on a proposed charter before it goes to you
    fork_good_keep: float = 0.5  # share of a parent's good record a fork inherits (bad is kept in full)
    learn_cost: Micros = 500_000
    learn_playbook_discount: float = 0.4
    learn_royalty: float = 0.1  # of learn_cost, to the author of the playbook learned from
    # disputes
    audit_cost: Micros = 6_000  # paid by the disputing contractor; refunded by the prime if the audit finds for them
    dispute_window: int = 3

    # the groups, built from the flat settings
    run: RunConfig = field(init=False, repr=False, compare=False)
    money: MoneyConfig = field(init=False, repr=False, compare=False)
    market: MarketConfig = field(init=False, repr=False, compare=False)
    contracts: ContractsConfig = field(init=False, repr=False, compare=False)
    ventures: VenturesConfig = field(init=False, repr=False, compare=False)
    population: PopulationConfig = field(init=False, repr=False, compare=False)
    knowledge: KnowledgeConfig = field(init=False, repr=False, compare=False)
    trust: TrustConfig = field(init=False, repr=False, compare=False)
    runtime: RuntimeConfig = field(init=False, repr=False, compare=False)
    storage: StorageConfig = field(init=False, repr=False, compare=False)

    def __post_init__(self):
        values = {f.name: getattr(self, f.name) for f in fields(self) if f.init}
        for group, cls in CONFIGS.items():
            object.__setattr__(self, group, cls(**{name: values[name] for name in GROUPS[group]}))


CONFIGS: dict[str, type] = {"run": RunConfig, "money": MoneyConfig, "market": MarketConfig, "contracts": ContractsConfig,
                            "ventures": VenturesConfig, "population": PopulationConfig, "knowledge": KnowledgeConfig,
                            "trust": TrustConfig, "runtime": RuntimeConfig, "storage": StorageConfig}
GROUPS: dict[str, tuple[str, ...]] = {g: tuple(f.name for f in fields(c)) for g, c in CONFIGS.items()}
