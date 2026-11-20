"""Research router: category, discipline and split decided from the user's own (spoken) words."""
import pytest

from backend.core.research_router import base_topic, detect_field, route

SINGLE = [
    # (spoken request, expected category, expected field for academic)
    ("what does the research say about intermittent fasting", "academic", "general"),
    ("what are the studies on transformers and large language model benchmarks", "academic", "cs_ml"),
    ("analyse the effect of minimum wage on employment", "academic", "social_science"),
    ("find papers on reinforcement learning from human feedback", "academic", "cs_ml"),
    ("is there evidence that remote work reduces productivity", "academic", "general"),
    ("meta-analysis of tutoring effects on test scores", "academic", "social_science"),
    ("look for arXiv preprints on diffusion models", "academic", "cs_ml"),
    ("research the market size of electric scooters in India", "market", ""),
    ("what's the TAM for AI note-taking apps", "market", ""),
    ("market outlook for solar panels in Europe", "market", ""),
    ("compare Notion vs Obsidian", "competitive", ""),
    ("who are the main competitors of Zerodha", "competitive", ""),
    ("Tesla's revenue and margins last quarter", "financial", ""),
    ("financial analysis of Infosys", "financial", ""),
    ("look into Kubernetes architecture and how it compares to Nomad", "technical", ""),
    ("is our use of GDPR data legal for the newsletter", "legal", ""),
    ("patent landscape for solid-state battery electrolytes", "legal", ""),
    ("deep dive on the future of remote work by 2030", "trend", ""),
    ("who is Sam Altman", "person_org", ""),
    ("background of the founder of Zoho", "person_org", ""),
    ("SWOT and business model of Swiggy", "business", ""),
    ("how healthy is the Rust contributor community", "community", ""),
]


@pytest.mark.parametrize("text,cat,fld", SINGLE)
def test_single_category_requests(text, cat, fld):
    plan = route(text)
    assert not plan.multi and not plan.guessed, (text, plan)
    assert plan.segments[0].category == cat, (text, plan.segments[0].reasons)
    assert plan.segments[0].field == fld
    assert plan.explanation.startswith("Researching this as")


COMBINED = [
    ("analyse the market size and what the research says about solid-state batteries", ["market", "academic"]),
    ("analyse solid-state batteries: market size, competitors, and what the scientific literature says",
     ["market", "academic"]),
    ("give me the financials of Nvidia and also what the studies say about GPU energy use", ["financial", "academic"]),
    ("check whether our data retention is legal; plus the market size for compliance tools", ["legal", "market"]),
    ("compare Figma vs Canva as well as the market size for design tools", ["competitive", "market"]),
]


@pytest.mark.parametrize("text,cats", COMBINED)
def test_combined_requests_split_by_category(text, cats):
    plan = route(text)
    assert plan.multi and [s.category for s in plan.segments] == cats, (text, [(s.category, s.request) for s in plan.segments])
    assert len({s.topic for s in plan.segments}) == len(cats)            # one topic per part
    assert plan.explanation.startswith(f"I'll research this in {len(cats)} parts")
    assert all(s.request for s in plan.segments)


@pytest.mark.parametrize("text", [
    "analyse India and China EV adoption",               # plain "and" joins subjects, not tasks
    "research cost and benefits of heat pumps",
])
def test_plain_and_does_not_split(text):
    assert not route(text).multi


def test_ambiguous_request_is_decided_labelled_and_offers_the_alternative():
    plan = route("analyse solid state batteries", model_type="technical")
    assert plan.guessed and plan.segments[0].category == "technical"   # model hint only as tie-breaker
    assert route("analyse solid state batteries", model_type="bogus").segments[0].category == "domain"
    p2 = route("analyse demand for AI tutors and the evidence they work")
    assert p2.segments[0].category in ("market", "academic")


def test_user_correction_names_the_category():
    assert route("make it market research").segments[0].category == "market"
    assert route("no, do it as academic research on battery recycling").segments[0].category == "academic"


def test_model_type_never_overrides_clear_words():
    assert route("what does the research say about sleep and memory", model_type="market").segments[0].category == "academic"


def test_explanation_mentions_field_and_max_three_segments():
    assert "computer science" in route("studies on large language model hallucination").explanation
    many = route("market size of drones; competitors of DJI; the research on drone safety; legal rules for drones")
    assert len(many.segments) == 3


def test_base_topic_and_field_helpers():
    assert base_topic("please analyse the market for e-bikes in Pune") == "The market for e-bikes in Pune"
    assert base_topic("x", topic="EV batteries") == "EV batteries"
    assert detect_field("deep learning benchmarks") == "cs_ml"
    assert detect_field("ocean acidification") == "general"
