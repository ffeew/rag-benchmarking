from fastapi.testclient import TestClient
from rag_common.db import models
from sqlalchemy.orm import Session


def test_create_eval_case(client: TestClient, seed_dataset: models.Dataset) -> None:
    response = client.post(
        "/v1/eval-cases",
        json={
            "dataset_id": seed_dataset.id,
            "case_key": "test_a",
            "category": "single_company_lookup",
            "difficulty": "easy",
            "question": "What was AAPL revenue?",
            "expected_answer": "$94B",
            "expected_citations": [{"ticker": "AAPL", "form_type": "10-K"}],
            "tags": ["revenue", "factual"],
        },
    )
    assert response.status_code == 201
    body = response.json()
    assert body["case_key"] == "test_a"
    assert body["category"] == "single_company_lookup"
    assert body["expected_citations"] == [{"ticker": "AAPL", "form_type": "10-K"}]


def test_create_eval_case_duplicate_key_returns_409(
    client: TestClient,
    seed_dataset: models.Dataset,
    seed_eval_case: models.EvalCase,
) -> None:
    response = client.post(
        "/v1/eval-cases",
        json={
            "dataset_id": seed_dataset.id,
            "case_key": seed_eval_case.case_key,
            "question": "duplicate?",
        },
    )
    assert response.status_code == 409


def test_create_eval_case_unknown_dataset_returns_404(client: TestClient) -> None:
    response = client.post(
        "/v1/eval-cases",
        json={"dataset_id": "missing-id", "question": "What?"},
    )
    assert response.status_code == 404


def test_list_eval_cases_filters_by_category(
    client: TestClient,
    seed_dataset: models.Dataset,
    db_session: Session,
) -> None:
    db_session.add_all(
        [
            models.EvalCase(
                dataset_id=seed_dataset.id,
                case_key="a1",
                category="single_company_lookup",
                question="Q1",
                expected_citations=[],
                tags=["revenue"],
            ),
            models.EvalCase(
                dataset_id=seed_dataset.id,
                case_key="b1",
                category="trend",
                question="Q2",
                expected_citations=[],
                tags=["margin", "yoy"],
            ),
        ]
    )
    db_session.commit()
    response = client.get(
        "/v1/eval-cases",
        params={"dataset_id": seed_dataset.id, "category": "trend"},
    )
    assert response.status_code == 200
    body = response.json()
    assert body["total"] == 1
    assert body["items"][0]["case_key"] == "b1"


def test_list_eval_cases_filters_by_tag(
    client: TestClient,
    seed_dataset: models.Dataset,
    db_session: Session,
) -> None:
    db_session.add_all(
        [
            models.EvalCase(
                dataset_id=seed_dataset.id,
                case_key="a1",
                question="Q1",
                expected_citations=[],
                tags=["revenue"],
            ),
            models.EvalCase(
                dataset_id=seed_dataset.id,
                case_key="b1",
                question="Q2",
                expected_citations=[],
                tags=["margin", "yoy"],
            ),
        ]
    )
    db_session.commit()
    response = client.get(
        "/v1/eval-cases",
        params={"dataset_id": seed_dataset.id, "tag": "margin"},
    )
    assert response.status_code == 200
    body = response.json()
    assert body["total"] == 1
    assert body["items"][0]["case_key"] == "b1"


def test_read_eval_case_returns_404_for_missing(client: TestClient) -> None:
    response = client.get("/v1/eval-cases/nonexistent")
    assert response.status_code == 404


def test_patch_eval_case_updates_fields(
    client: TestClient,
    seed_eval_case: models.EvalCase,
) -> None:
    response = client.patch(
        f"/v1/eval-cases/{seed_eval_case.id}",
        json={"difficulty": "hard", "tags": ["updated"]},
    )
    assert response.status_code == 200
    body = response.json()
    assert body["difficulty"] == "hard"
    assert body["tags"] == ["updated"]
    # Untouched fields preserved
    assert body["question"] == seed_eval_case.question


def test_patch_eval_case_rejects_conflicting_case_key(
    client: TestClient,
    seed_dataset: models.Dataset,
    seed_eval_case: models.EvalCase,
    db_session: Session,
) -> None:
    other = models.EvalCase(
        dataset_id=seed_dataset.id,
        case_key="other_key",
        question="Other?",
        expected_citations=[],
        tags=[],
    )
    db_session.add(other)
    db_session.commit()
    response = client.patch(
        f"/v1/eval-cases/{other.id}",
        json={"case_key": seed_eval_case.case_key},
    )
    assert response.status_code == 409


def test_delete_eval_case_204_when_unused(client: TestClient, seed_eval_case: models.EvalCase) -> None:
    response = client.delete(f"/v1/eval-cases/{seed_eval_case.id}")
    assert response.status_code == 204


def test_delete_eval_case_409_when_referenced_by_results(
    client: TestClient,
    seed_eval_case: models.EvalCase,
    seed_dataset: models.Dataset,
    db_session: Session,
) -> None:
    eval_run = models.EvalRun(
        dataset_id=seed_dataset.id,
        status="completed",
        run_config={},
        system_variant="full_agentic",
        model_metadata={},
        metrics={},
        errors=[],
    )
    db_session.add(eval_run)
    db_session.flush()
    db_session.add(
        models.EvalResult(
            eval_run_id=eval_run.id,
            eval_case_id=seed_eval_case.id,
            retrieval_mode="full_agentic",
            answer="x",
            trace_id=None,
            metrics={},
        )
    )
    db_session.commit()
    response = client.delete(f"/v1/eval-cases/{seed_eval_case.id}")
    assert response.status_code == 409
