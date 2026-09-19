# 06 — Property-Based Testing

## Beyond Example-Based Tests

Standard parametrize tests are example-based: you enumerate specific inputs and expected outputs. This is powerful but limited by your imagination. You can only test the edge cases you think of.

Property-based testing inverts this: instead of specifying *inputs*, you specify *properties of the output* — invariants that must hold for *any valid input*. The testing engine (Hypothesis) then:

1. Generates hundreds of random inputs that satisfy your type constraints
2. Runs your test for each
3. If a failure is found, *shrinks* the input to the minimal failing example
4. Reports the minimal case as the counterexample

```bash
uv add --dev hypothesis
```

---

## 1. The Mental Shift: From Examples to Properties

The key question is: **what must always be true, regardless of the specific input?**

| Example-based thinking | Property-based thinking |
|------------------------|------------------------|
| `normalize([0, 50, 100]) == [0.0, 0.5, 1.0]` | For any list, output length equals input length |
| `normalize([0, 0, 0]) == [0.0, 0.0, 0.0]` | For any list, all output values are in [0, 1] |
| `sort([3, 1, 2]) == [1, 2, 3]` | Sorted output is always ordered; same elements |
| `parse_json(serialize(obj)) == obj` | Round-trip: deserialize(serialize(x)) == x |

---

## 2. Core Hypothesis Concepts

### `@given` and Strategies

`@given` is the decorator. Strategies generate values.

```python
from hypothesis import given, settings, assume, note
from hypothesis import strategies as st
from feature_pipeline.preprocessing import normalize_features

@given(st.lists(st.floats(allow_nan=False, allow_infinity=False), min_size=1))
def test_normalize_output_is_always_in_unit_range(values):
    result = normalize_features(values, method="min_max")
    assert all(0.0 <= v <= 1.0 for v in result)

@given(st.lists(st.floats(allow_nan=False, allow_infinity=False)))
def test_normalize_preserves_length(values):
    result = normalize_features(values, method="min_max")
    assert len(result) == len(values)
```

Hypothesis runs each test with 100 examples by default (configurable). When it finds a failure, it shrinks to the minimal counterexample.

### Common Strategies

```python
st.integers()                          # any integer
st.integers(min_value=0, max_value=100) # bounded integer
st.floats(allow_nan=False, allow_infinity=False)  # finite floats
st.text()                              # any unicode string
st.text(alphabet=st.characters(whitelist_categories=["Lu", "Ll", "Nd"]))
st.binary()                            # bytes
st.booleans()                          # True or False
st.none()                              # None
st.lists(st.integers(), min_size=1, max_size=100)
st.sets(st.text())
st.dictionaries(st.text(), st.integers())
st.one_of(st.integers(), st.text(), st.none())  # union
st.just("fixed_value")               # always returns this value
st.sampled_from(["min_max", "z_score", "robust"])  # pick from list
```

### `@composite` — Building Complex Strategies

```python
from hypothesis.strategies import composite

@composite
def feature_record(draw) -> dict:
    """Generate a valid feature record."""
    return {
        "user_id": draw(st.text(min_size=1, max_size=50, 
                                alphabet="abcdefghijklmnopqrstuvwxyz0123456789-_")),
        "age": draw(st.integers(min_value=0, max_value=150)),
        "income": draw(st.floats(min_value=0, max_value=1e8, allow_nan=False)),
        "purchase_count": draw(st.integers(min_value=0, max_value=10_000)),
        "segment": draw(st.sampled_from(["bronze", "silver", "gold", "platinum"])),
    }

@given(feature_record())
def test_schema_validator_accepts_any_valid_record(record):
    # Should not raise for any valid record
    validate_feature_schema(record)

@given(st.lists(feature_record(), min_size=1, max_size=100))
def test_batch_processor_handles_any_valid_batch(records):
    result = process_batch(records)
    assert len(result) == len(records)
    assert all(0.0 <= r["normalized_income"] <= 1.0 for r in result)
```

---

## 3. Properties for ML and Data Code

Property-based testing is particularly powerful for data transformation code because the invariants are mathematical and universal.

### Normalization Properties

```python
@given(st.lists(st.floats(allow_nan=False, allow_infinity=False), min_size=2))
def test_min_max_properties(values):
    result = normalize_features(values, method="min_max")
    
    # Property 1: length preserved
    assert len(result) == len(values)
    
    # Property 2: all values in [0, 1]
    assert all(0.0 <= v <= 1.0 for v in result)
    
    # Property 3: minimum maps to 0, maximum maps to 1 (when min != max)
    if min(values) != max(values):
        assert min(result) == pytest.approx(0.0, abs=1e-9)
        assert max(result) == pytest.approx(1.0, abs=1e-9)
    
    # Property 4: relative order is preserved
    sorted_original = sorted(range(len(values)), key=lambda i: values[i])
    sorted_result = sorted(range(len(result)), key=lambda i: result[i])
    assert sorted_original == sorted_result

@given(st.lists(st.floats(allow_nan=False, allow_infinity=False), min_size=2))
def test_z_score_properties(values):
    result = normalize_features(values, method="z_score")
    
    # Property 1: mean is approximately 0
    mean = sum(result) / len(result)
    assert abs(mean) < 1e-6, f"Mean should be ~0, got {mean}"
    
    # Property 2: std is approximately 1 (when not constant)
    if min(values) != max(values):
        variance = sum((v - mean) ** 2 for v in result) / len(result)
        assert abs(variance - 1.0) < 1e-6
```

### Serialization Round-Trip Properties

Round-trip testing is one of the most reliable property patterns:

```python
@given(feature_record())
def test_feature_serialization_roundtrip(record):
    """Serialize to JSON and back — must recover the original data."""
    serialized = FeatureRecord.from_dict(record).to_json()
    recovered = FeatureRecord.from_json(serialized).to_dict()
    assert recovered == record

@given(st.lists(feature_record(), min_size=1, max_size=50))
def test_batch_serialization_roundtrip(records):
    """Batch serialization must be lossless."""
    batch = FeatureBatch(records=records)
    serialized = batch.to_bytes()
    recovered = FeatureBatch.from_bytes(serialized)
    assert recovered.records == batch.records
```

### Idempotency Properties

```python
@given(st.lists(feature_record(), min_size=1))
def test_normalization_is_idempotent(records):
    """Applying normalization twice gives the same result as once."""
    once = normalize_batch(records)
    twice = normalize_batch(once)  # normalize the already-normalized data
    
    for a, b in zip(once, twice):
        for key in a:
            assert a[key] == pytest.approx(b[key], abs=1e-9)

@given(feature_record())
def test_validation_is_idempotent(record):
    """Validating a valid record twice should not modify it."""
    import copy
    original = copy.deepcopy(record)
    validate_feature_schema(record)
    validate_feature_schema(record)
    assert record == original
```

### Sorting and Ordering Properties

```python
from feature_pipeline.ranking import rank_features

@given(st.lists(feature_record(), min_size=1))
def test_ranking_properties(records):
    ranked = rank_features(records)
    
    # Property 1: same number of records
    assert len(ranked) == len(records)
    
    # Property 2: scores are decreasing (descending rank)
    scores = [r["rank_score"] for r in ranked]
    assert all(scores[i] >= scores[i+1] for i in range(len(scores)-1))
    
    # Property 3: no records are lost or duplicated
    original_ids = {r["user_id"] for r in records}
    ranked_ids = {r["user_id"] for r in ranked}
    assert original_ids == ranked_ids
```

---

## 4. `assume` — Filtering Invalid Inputs

Use `assume()` to discard inputs that don't meet your preconditions. Hypothesis won't count discarded examples toward the target count — it will generate new ones.

```python
from hypothesis import assume

@given(st.floats(allow_nan=False), st.floats(allow_nan=False))
def test_normalize_single_value(value, min_val, max_val):
    # Skip degenerate cases where min == max
    assume(min_val < max_val)
    assume(min_val <= value <= max_val)
    
    result = normalize(value, min_val=min_val, max_val=max_val)
    assert 0.0 <= result <= 1.0
```

Use `assume` sparingly. If most generated inputs are discarded, your strategy is poorly targeted — use a `@composite` strategy instead.

---

## 5. Settings — Controlling the Test Run

```python
from hypothesis import settings, HealthCheck, Phase

# More examples for a critical function
@settings(max_examples=500)
@given(st.lists(st.floats(allow_nan=False, allow_infinity=False), min_size=1))
def test_normalize_extensively(values):
    ...

# Suppress slow-data health check for large-data tests
@settings(suppress_health_check=[HealthCheck.too_slow])
@given(st.lists(feature_record(), min_size=100, max_size=1000))
def test_bulk_processing(records):
    ...

# Faster CI runs (fewer examples)
@settings(max_examples=20)
@given(...)
def test_property_in_ci():
    ...
```

**Profiles** let you configure different settings per environment:

```python
from hypothesis import settings, HealthCheck

settings.register_profile("ci", max_examples=100)
settings.register_profile("dev", max_examples=10)
settings.register_profile("thorough", max_examples=1000)

# Load profile from environment
settings.load_profile(os.getenv("HYPOTHESIS_PROFILE", "dev"))
```

```bash
# In CI:
HYPOTHESIS_PROFILE=ci pytest tests/ -m hypothesis
```

---

## 6. The Hypothesis Database

Hypothesis maintains a local database of previously failing examples. When it finds a new failure, it saves it. On subsequent runs, it replays the failure immediately before doing random generation.

```
.hypothesis/
└── examples/       # saved failing examples, per test
```

Commit `.hypothesis/examples/` to version control. This means:
- A failure found by one developer is immediately reproduced by all teammates
- A failure found in CI is immediately reproduced locally

---

## 7. `note` — Debugging Property Test Failures

When a property test fails, the shrunk counterexample is printed. Add `note()` calls to print intermediate values:

```python
from hypothesis import note

@given(st.lists(st.floats(allow_nan=False), min_size=1))
def test_pipeline_output_properties(values):
    result = process(values)
    note(f"Input: {values}")
    note(f"Output: {result}")
    note(f"Min input: {min(values)}, Max input: {max(values)}")
    
    assert all(math.isfinite(v) for v in result)
```

Notes only appear in the output when the test fails.

---

## Summary

| Property type | Example |
|--------------|---------|
| Length preservation | `len(output) == len(input)` |
| Range constraints | `all(0 <= v <= 1 for v in output)` |
| Ordering | Sorted output is always in order |
| Round-trip (serialize/deserialize) | `from_json(to_json(x)) == x` |
| Idempotency | `f(f(x)) == f(x)` |
| Commutativity | `f(a, b) == f(b, a)` |
| Statistical (z-score) | `mean(output) ≈ 0, std(output) ≈ 1` |

> **Property-based testing does not replace example-based testing.** Use both: parametrize for specific known edge cases, Hypothesis for discovering the ones you didn't think of.
