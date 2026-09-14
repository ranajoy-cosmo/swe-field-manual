# 07 — Testing ML Code

## Why ML Code Is Different

Standard software testing assumes that for a given input, there is one correct output. ML code breaks this assumption in several places:

- **Data pipelines** transform data through statistical operations — outputs are distributions, not exact values
- **Models** are probabilistic — the same input may produce slightly different outputs depending on numerical precision, hardware, and framework versions
- **Training** is stochastic — two runs with the same hyperparameters may produce different weights
- **Correctness** is fuzzy — a model that achieves 91% accuracy is "correct"; one that achieves 45% is not, but the function signatures are identical

These properties don't make ML code untestable — they just require different tests. This chapter covers four testing categories specific to ML systems:

1. **Data validation tests** — the data is what you think it is
2. **Model behavioral tests** — the model behaves in ways that reflect domain understanding
3. **Pipeline smoke tests** — the training and inference pipeline runs end-to-end
4. **Infrastructure tests** — the serving and storage layers work correctly (covered in Chapter 04)

---

## 1. Data Validation Tests

The most common source of ML production failures is bad data. Not model bugs — data bugs. A feature is computed incorrectly, a join produces duplicates, a null propagates silently, a distribution shifts.

Data validation tests catch these before they reach model training or serving.

### Testing Feature Computation

```python
# tests/unit/test_feature_engineering.py
import pytest
import math
from feature_pipeline.features import (
    compute_age_normalized,
    compute_recency_score,
    compute_purchase_velocity,
)

class TestAgeNormalized:
    @pytest.mark.parametrize("age, expected", [
        (0,   0.0),     # minimum
        (100, 1.0),     # maximum (our domain max)
        (25,  0.25),    # mid-low
        (50,  0.5),     # midpoint
    ])
    def test_known_values(self, age, expected):
        assert compute_age_normalized(age) == pytest.approx(expected, abs=1e-9)

    def test_always_returns_value_in_unit_range(self):
        for age in range(0, 101, 5):
            result = compute_age_normalized(age)
            assert 0.0 <= result <= 1.0, f"Age {age} normalized to {result}"

    def test_raises_for_negative_age(self):
        with pytest.raises(ValueError, match="age must be non-negative"):
            compute_age_normalized(-1)

    def test_raises_for_age_above_maximum(self):
        with pytest.raises(ValueError, match="age exceeds domain maximum"):
            compute_age_normalized(200)

class TestRecencyScore:
    def test_recent_event_produces_high_score(self):
        score = compute_recency_score(days_since_last_purchase=1)
        assert score > 0.9

    def test_old_event_produces_low_score(self):
        score = compute_recency_score(days_since_last_purchase=365)
        assert score < 0.1

    def test_score_decreases_monotonically_with_time(self):
        scores = [compute_recency_score(d) for d in range(0, 100, 5)]
        assert all(scores[i] >= scores[i+1] for i in range(len(scores)-1))

    def test_score_is_always_finite(self):
        for days in [0, 1, 30, 365, 3650]:
            score = compute_recency_score(days)
            assert math.isfinite(score), f"Non-finite score for {days} days"
```

### Testing Data Schema and Quality

Use `pandera` for DataFrame schema validation tests — it integrates naturally with pytest:

```bash
uv add --dev pandera
```

```python
# tests/unit/test_data_schema.py
import pandas as pd
import pandera as pa
import pytest
from pandera import Column, DataFrameSchema, Check

FEATURE_SCHEMA = DataFrameSchema({
    "user_id":        Column(str, nullable=False),
    "age_normalized": Column(float, checks=[
        Check.in_range(0.0, 1.0),
        Check(lambda s: s.notna().all(), error="age_normalized has nulls"),
    ]),
    "purchase_count": Column(int, checks=Check.greater_than_or_equal_to(0)),
    "recency_score":  Column(float, checks=[
        Check.in_range(0.0, 1.0),
        Check(lambda s: s.notna().all()),
    ]),
    "segment":        Column(str, checks=Check.isin(["bronze", "silver", "gold", "platinum"])),
})

def test_feature_pipeline_output_matches_schema(pipeline, sample_entities):
    output_df = pipeline.compute_features(sample_entities)
    FEATURE_SCHEMA.validate(output_df)  # raises SchemaError if invalid

def test_feature_pipeline_produces_no_duplicates(pipeline, sample_entities):
    output_df = pipeline.compute_features(sample_entities)
    assert output_df["user_id"].is_unique, "Duplicate user_ids in output"

def test_feature_pipeline_covers_all_entities(pipeline, sample_entities):
    output_df = pipeline.compute_features(sample_entities)
    assert set(output_df["user_id"]) == set(sample_entities)
```

### Testing Data Distributions (Statistical Tests)

For detecting distribution shifts or ensuring features have expected statistical properties:

```python
import numpy as np
from scipy import stats

def test_age_distribution_is_approximately_uniform(computed_features):
    ages = computed_features["age_normalized"].values
    
    # Kolmogorov-Smirnov test against uniform distribution
    stat, p_value = stats.kstest(ages, "uniform")
    
    # If p < 0.05, distribution is significantly non-uniform
    # For production feature validation, set threshold based on your domain
    assert p_value > 0.01, f"Age distribution is non-uniform (p={p_value:.3f})"

def test_normalized_features_have_expected_range(computed_features):
    numeric_cols = ["age_normalized", "income_normalized", "recency_score"]
    for col in numeric_cols:
        values = computed_features[col].dropna().values
        assert values.min() >= 0.0, f"{col} has values below 0"
        assert values.max() <= 1.0, f"{col} has values above 1"
        assert np.isfinite(values).all(), f"{col} has non-finite values"
```

---

## 2. Model Behavioral Tests

Rather than testing exact model outputs (which vary with training), test *behavioral properties* — invariants that must hold for a correct model regardless of the specific weights.

These tests use a **pre-trained fixture model**, not a freshly trained one, to ensure determinism.

### Directional Expectation Tests

Does the model's output move in the expected direction when input changes?

```python
# tests/unit/test_model_behavior.py
import pytest
import numpy as np

@pytest.fixture(scope="session")
def trained_model(model_checkpoint_path):
    """Load a fixed, deterministic model for behavioral tests."""
    return Model.load(model_checkpoint_path)

class TestModelBehavior:
    
    def test_higher_purchase_count_increases_predicted_ltv(self, trained_model):
        """More purchases → higher predicted lifetime value."""
        base_features = {"age_normalized": 0.3, "purchase_count": 5, "recency_score": 0.8}
        high_features  = {**base_features, "purchase_count": 20}
        
        ltv_low  = trained_model.predict(base_features)
        ltv_high = trained_model.predict(high_features)
        
        assert ltv_high > ltv_low, (
            f"Expected higher LTV for more purchases. "
            f"Got {ltv_low:.3f} → {ltv_high:.3f}"
        )

    def test_recent_activity_increases_predicted_churn_resistance(self, trained_model):
        """More recent activity → lower churn probability."""
        stale_features  = {"recency_score": 0.1, "purchase_count": 3, "age_normalized": 0.4}
        active_features = {**stale_features, "recency_score": 0.9}
        
        churn_stale  = trained_model.predict_churn(stale_features)
        churn_active = trained_model.predict_churn(active_features)
        
        assert churn_active < churn_stale

    def test_prediction_is_bounded_in_valid_range(self, trained_model):
        """LTV prediction must always be non-negative."""
        for _ in range(100):
            # Random valid inputs
            features = {
                "age_normalized": np.random.uniform(0, 1),
                "purchase_count": np.random.randint(0, 100),
                "recency_score": np.random.uniform(0, 1),
            }
            prediction = trained_model.predict(features)
            assert prediction >= 0, f"Negative LTV prediction: {prediction}"

    def test_prediction_is_deterministic_for_same_input(self, trained_model):
        """Same input must always produce same output (model is not stochastic at inference)."""
        features = {"age_normalized": 0.5, "purchase_count": 10, "recency_score": 0.7}
        
        predictions = [trained_model.predict(features) for _ in range(10)]
        assert len(set(predictions)) == 1, "Model is non-deterministic at inference"

    def test_model_handles_edge_case_features(self, trained_model):
        """Edge case inputs must produce finite outputs, not NaN or inf."""
        edge_cases = [
            {"age_normalized": 0.0, "purchase_count": 0, "recency_score": 0.0},   # all zeros
            {"age_normalized": 1.0, "purchase_count": 10000, "recency_score": 1.0}, # all max
        ]
        for features in edge_cases:
            result = trained_model.predict(features)
            assert np.isfinite(result), f"Non-finite output for {features}: {result}"
```

### Invariance Tests

The model output should be *invariant* (unchanged) under certain transformations that shouldn't affect the prediction:

```python
def test_prediction_invariant_to_entity_id(self, trained_model):
    """The entity_id should not influence the prediction — it's an identifier."""
    features = {"age_normalized": 0.3, "purchase_count": 5, "recency_score": 0.7}
    
    pred_a = trained_model.predict({**features, "entity_id": "user-1"})
    pred_b = trained_model.predict({**features, "entity_id": "user-99999"})
    
    assert pred_a == pytest.approx(pred_b, abs=1e-6)
```

### Minimum Functionality Tests (MNLT)

A minimum set of labeled examples where the model *must* get the right answer. These are not about accuracy — they're about obvious correctness:

```python
MUST_PREDICT_HIGH = [
    # These are clearly high-LTV users — model must agree
    {"age_normalized": 0.4, "purchase_count": 50, "recency_score": 0.95},
    {"age_normalized": 0.35, "purchase_count": 100, "recency_score": 0.9},
]

MUST_PREDICT_LOW = [
    # These are clearly low-LTV users
    {"age_normalized": 0.8, "purchase_count": 0, "recency_score": 0.0},
    {"age_normalized": 0.9, "purchase_count": 1, "recency_score": 0.05},
]

HIGH_THRESHOLD = 0.7  # domain-defined

def test_model_correctly_identifies_obvious_high_value_users(trained_model):
    for features in MUST_PREDICT_HIGH:
        score = trained_model.predict(features)
        assert score >= HIGH_THRESHOLD, (
            f"Model failed on an obvious high-value user. "
            f"Features: {features}, Score: {score:.3f}"
        )

def test_model_correctly_identifies_obvious_low_value_users(trained_model):
    for features in MUST_PREDICT_LOW:
        score = trained_model.predict(features)
        assert score < HIGH_THRESHOLD, (
            f"Model failed on an obvious low-value user. "
            f"Features: {features}, Score: {score:.3f}"
        )
```

---

## 3. Training Pipeline Smoke Tests

Smoke tests verify that the training pipeline runs end-to-end without crashing, using a tiny dataset. They don't validate model quality — that's the job of offline evaluation. They validate that the *plumbing* works.

```python
# tests/integration/test_training_smoke.py
import pytest
import torch
from feature_pipeline.training import Trainer, TrainingConfig
from feature_pipeline.data import FeatureDataset

@pytest.fixture(scope="module")
def tiny_dataset(tmp_path_factory):
    """Minimal dataset for smoke testing — 50 examples."""
    data_dir = tmp_path_factory.mktemp("data")
    create_fixture_dataset(data_dir, n_examples=50)
    return data_dir

@pytest.fixture(scope="module")
def smoke_config(tiny_dataset) -> TrainingConfig:
    return TrainingConfig(
        data_path=tiny_dataset,
        model_name="small-test-model",
        num_epochs=2,          # just 2 epochs
        batch_size=16,
        learning_rate=0.01,
        max_steps=10,          # stop after 10 steps regardless
        checkpoint_dir=None,   # don't save checkpoints
    )

@pytest.mark.integration
@pytest.mark.slow
class TestTrainingSmoke:
    
    def test_training_completes_without_error(self, smoke_config):
        """Training must run end-to-end without exceptions."""
        trainer = Trainer(config=smoke_config)
        result = trainer.train()  # should not raise
        assert result is not None

    def test_loss_is_finite_throughout_training(self, smoke_config):
        """Loss must never be NaN or inf — indicates gradient explosion or bad data."""
        import math
        trainer = Trainer(config=smoke_config)
        
        losses = []
        def record_loss(step, loss):
            losses.append(loss)
        
        trainer.on_step_end = record_loss
        trainer.train()
        
        assert all(math.isfinite(l) for l in losses), \
            f"Non-finite loss encountered: {[l for l in losses if not math.isfinite(l)]}"

    def test_loss_decreases_in_first_few_steps(self, smoke_config):
        """Loss should generally decrease — sanity check on learning."""
        trainer = Trainer(config=smoke_config)
        result = trainer.train()
        
        early_loss = result.loss_history[:3]
        final_loss = result.loss_history[-3:]
        
        assert min(final_loss) < max(early_loss), \
            "Loss did not decrease at all — potential training bug"

    def test_model_checkpoint_can_be_loaded(self, smoke_config, tmp_path):
        """A saved checkpoint must be loadable and produce valid predictions."""
        config = smoke_config.model_copy(update={"checkpoint_dir": tmp_path})
        trainer = Trainer(config=config)
        trainer.train()
        
        checkpoint_path = tmp_path / "final_checkpoint"
        assert checkpoint_path.exists()
        
        model = Model.load(checkpoint_path)
        sample_features = {"age_normalized": 0.5, "purchase_count": 5, "recency_score": 0.7}
        prediction = model.predict(sample_features)
        assert isinstance(prediction, float)
        assert math.isfinite(prediction)

    def test_evaluation_metrics_are_computed(self, smoke_config):
        """Evaluation must produce a complete metrics dict."""
        trainer = Trainer(config=smoke_config)
        result = trainer.train()
        
        required_metrics = {"loss", "mae", "rmse"}
        assert required_metrics.issubset(set(result.eval_metrics.keys()))
        assert all(math.isfinite(v) for v in result.eval_metrics.values())
```

---

## 4. Testing Inference Pipelines

The inference path has different correctness requirements than training:

```python
# tests/unit/test_inference.py
import pytest
import numpy as np
from feature_pipeline.inference import InferencePipeline

@pytest.fixture(scope="module")
def inference_pipeline(model_checkpoint):
    return InferencePipeline(model=model_checkpoint, batch_size=32)

class TestInferencePipeline:
    
    def test_single_entity_inference_returns_expected_shape(self, inference_pipeline):
        result = inference_pipeline.predict(entity_id="user-123", features=sample_features)
        assert "score" in result
        assert "confidence" in result
        assert 0.0 <= result["score"] <= 1.0
        assert 0.0 <= result["confidence"] <= 1.0

    def test_batch_inference_output_count_matches_input(self, inference_pipeline):
        entity_ids = [f"user-{i}" for i in range(100)]
        results = inference_pipeline.predict_batch(entity_ids=entity_ids)
        assert len(results) == len(entity_ids)

    def test_batch_inference_preserves_entity_id_order(self, inference_pipeline):
        """Results must be in the same order as input entity IDs."""
        entity_ids = [f"user-{i}" for i in range(50)]
        results = inference_pipeline.predict_batch(entity_ids=entity_ids)
        assert [r["entity_id"] for r in results] == entity_ids

    def test_inference_latency_is_within_sla(self, inference_pipeline):
        """P95 inference latency must be under 100ms for a single entity."""
        import time
        latencies = []
        for _ in range(100):
            start = time.perf_counter()
            inference_pipeline.predict(entity_id="user-123", features=sample_features)
            latencies.append(time.perf_counter() - start)
        
        p95_ms = np.percentile(latencies, 95) * 1000
        assert p95_ms < 100, f"P95 latency {p95_ms:.1f}ms exceeds 100ms SLA"
```

---

## 5. Fixtures for ML Tests

ML tests have specific fixture needs:

```python
# tests/conftest.py

@pytest.fixture(scope="session")
def model_checkpoint_path():
    """Path to a deterministic, pre-trained model fixture."""
    path = Path("tests/fixtures/models/test_model_v1.ckpt")
    if not path.exists():
        pytest.skip(f"Model fixture not found at {path}. Run make download-fixtures.")
    return path

@pytest.fixture(scope="session")
def trained_model(model_checkpoint_path):
    return Model.load(model_checkpoint_path)

@pytest.fixture
def sample_feature_batch():
    """A small, deterministic batch of features for testing."""
    return [
        {"user_id": f"user-{i}", "age_normalized": i * 0.1, 
         "purchase_count": i, "recency_score": 1.0 - i * 0.1}
        for i in range(10)
    ]

@pytest.fixture
def create_fixture_dataframe():
    """Factory for creating test DataFrames with controlled properties."""
    def _create(n_rows: int = 100, seed: int = 42) -> pd.DataFrame:
        rng = np.random.default_rng(seed)
        return pd.DataFrame({
            "user_id": [f"user-{i}" for i in range(n_rows)],
            "age": rng.integers(18, 80, size=n_rows),
            "purchase_count": rng.integers(0, 100, size=n_rows),
            "days_since_last_purchase": rng.integers(0, 365, size=n_rows),
        })
    return _create
```

---

## Summary

| Test category | What it catches | Tools |
|--------------|----------------|-------|
| Feature computation tests | Wrong math, wrong range, wrong behavior | pytest + parametrize |
| Schema validation tests | Missing fields, wrong types, nulls | pandera, pydantic |
| Distribution tests | Feature drift, statistical anomalies | scipy.stats |
| Behavioral tests | Model learning something sensible | Fixed checkpoint fixture |
| Directional tests | Monotonicity, expected direction of effect | parametrize + assert comparison |
| Invariance tests | Spurious correlations with identifiers | Paired input tests |
| Smoke tests | Pipeline crashes, NaN loss, broken checkpointing | Integration test with tiny dataset |
| Inference tests | Shape, order, latency SLA | TestClient or direct pipeline call |

> **The governing rule for ML tests:** you can't test that a model is "correct," but you can test that it's not obviously wrong. Push the definition of "obviously wrong" as far as your domain knowledge allows.
