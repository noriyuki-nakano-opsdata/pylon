"""Batch API wrapper for cost-efficient bulk LLM requests.

Supports Anthropic and OpenAI Batch APIs, offering 50% cost reduction
for non-latency-sensitive workloads.  Requests flagged with
``batch_eligible=True`` in ModelRouteDecision are automatically
collected and submitted as batches.

The BatchCollector buffers requests until ``flush()`` is called or the
buffer reaches ``max_buffer_size``, then submits them through the
provider's batch endpoint.
"""

from __future__ import annotations

import enum
import time
import uuid
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from typing import Any

from pylon.providers.base import Message, Response


class BatchStatus(enum.Enum):
    PENDING = "pending"
    SUBMITTED = "submitted"
    PROCESSING = "processing"
    COMPLETED = "completed"
    FAILED = "failed"
    EXPIRED = "expired"


@dataclass
class BatchRequest:
    """A single request in a batch."""

    id: str
    messages: list[Message]
    model: str
    provider: str
    kwargs: dict[str, Any] = field(default_factory=dict)
    created_at: float = field(default_factory=time.time)


@dataclass
class BatchResult:
    """Result for a single request in a completed batch."""

    request_id: str
    response: Response | None = None
    error: str | None = None
    status: BatchStatus = BatchStatus.PENDING


@dataclass
class BatchSubmission:
    """Tracking state for a submitted batch."""

    batch_id: str
    provider: str
    requests: list[BatchRequest]
    status: BatchStatus = BatchStatus.SUBMITTED
    submitted_at: float = field(default_factory=time.time)
    completed_at: float | None = None
    results: list[BatchResult] = field(default_factory=list)
    external_batch_id: str | None = None

    @property
    def is_terminal(self) -> bool:
        return self.status in (
            BatchStatus.COMPLETED,
            BatchStatus.FAILED,
            BatchStatus.EXPIRED,
        )


# Type alias for provider batch submission callable
BatchSubmitFn = Callable[
    [str, list[BatchRequest]],  # (provider, requests)
    Awaitable[str],  # returns external_batch_id
]

BatchPollFn = Callable[
    [str, str],  # (provider, external_batch_id)
    Awaitable[tuple[BatchStatus, list[BatchResult]]],
]


class BatchCollector:
    """Collects batch-eligible requests and submits them in bulk.

    Usage:
        collector = BatchCollector(max_buffer_size=100)
        req_id = collector.enqueue(messages, model="gpt-4o", provider="openai")
        # ... enqueue more requests ...
        submissions = await collector.flush(submit_fn=my_submit_fn)
        # ... later ...
        await collector.poll(batch_id, poll_fn=my_poll_fn)
        result = collector.get_result(req_id)
    """

    def __init__(
        self,
        *,
        max_buffer_size: int = 100,
        auto_flush: bool = False,
    ) -> None:
        self._buffer: dict[str, list[BatchRequest]] = {}  # keyed by provider
        self._max_buffer_size = max_buffer_size
        self._auto_flush = auto_flush
        self._submissions: dict[str, BatchSubmission] = {}
        self._request_to_batch: dict[str, str] = {}
        self._results: dict[str, BatchResult] = {}

    def enqueue(
        self,
        messages: list[Message],
        *,
        model: str,
        provider: str,
        **kwargs: Any,
    ) -> str:
        """Add a request to the batch buffer.

        Returns:
            Request ID that can be used to retrieve the result later.
        """
        request_id = f"batch_req_{uuid.uuid4().hex[:12]}"
        request = BatchRequest(
            id=request_id,
            messages=messages,
            model=model,
            provider=provider,
            kwargs=kwargs,
        )

        if provider not in self._buffer:
            self._buffer[provider] = []
        self._buffer[provider].append(request)
        self._results[request_id] = BatchResult(request_id=request_id)

        return request_id

    @property
    def buffer_size(self) -> int:
        """Total number of buffered requests across all providers."""
        return sum(len(reqs) for reqs in self._buffer.values())

    @property
    def buffered_providers(self) -> list[str]:
        """Providers with buffered requests."""
        return [p for p, reqs in self._buffer.items() if reqs]

    async def flush(
        self,
        submit_fn: BatchSubmitFn,
        *,
        provider: str | None = None,
    ) -> list[BatchSubmission]:
        """Submit buffered requests as batches.

        Args:
            submit_fn: Async callable that submits a batch to the provider.
            provider: If given, only flush requests for this provider.

        Returns:
            List of BatchSubmission objects for tracking.
        """
        providers_to_flush = [provider] if provider else list(self._buffer.keys())
        submissions: list[BatchSubmission] = []

        for p in providers_to_flush:
            requests = self._buffer.pop(p, [])
            if not requests:
                continue

            batch_id = f"batch_{uuid.uuid4().hex[:12]}"
            try:
                external_id = await submit_fn(p, requests)
            except Exception as exc:
                # Mark all requests as failed
                submission = BatchSubmission(
                    batch_id=batch_id,
                    provider=p,
                    requests=requests,
                    status=BatchStatus.FAILED,
                    results=[
                        BatchResult(
                            request_id=r.id,
                            error=str(exc),
                            status=BatchStatus.FAILED,
                        )
                        for r in requests
                    ],
                )
                for r in requests:
                    self._results[r.id] = BatchResult(
                        request_id=r.id, error=str(exc), status=BatchStatus.FAILED
                    )
                self._submissions[batch_id] = submission
                submissions.append(submission)
                continue

            submission = BatchSubmission(
                batch_id=batch_id,
                provider=p,
                requests=requests,
                external_batch_id=external_id,
            )
            for r in requests:
                self._request_to_batch[r.id] = batch_id

            self._submissions[batch_id] = submission
            submissions.append(submission)

        return submissions

    async def poll(
        self,
        batch_id: str,
        poll_fn: BatchPollFn,
    ) -> BatchSubmission:
        """Poll a submitted batch for completion.

        Args:
            batch_id: Internal batch ID from flush().
            poll_fn: Async callable that checks batch status.

        Returns:
            Updated BatchSubmission.
        """
        submission = self._submissions.get(batch_id)
        if submission is None:
            raise KeyError(f"Unknown batch: {batch_id}")

        if submission.is_terminal:
            return submission

        if submission.external_batch_id is None:
            return submission

        status, results = await poll_fn(
            submission.provider, submission.external_batch_id
        )
        submission.status = status
        if results:
            submission.results = results
            submission.completed_at = time.time()
            for result in results:
                self._results[result.request_id] = result

        return submission

    def get_result(self, request_id: str) -> BatchResult | None:
        """Get the result for a specific request."""
        return self._results.get(request_id)

    def get_pending_batches(self) -> list[BatchSubmission]:
        """List non-terminal batch submissions."""
        return [s for s in self._submissions.values() if not s.is_terminal]


def estimate_batch_savings(
    request_count: int,
    avg_input_tokens: int,
    avg_output_tokens: int,
    price_per_million_input: float,
    price_per_million_output: float,
    *,
    batch_discount: float = 0.5,
) -> dict[str, float]:
    """Estimate cost savings from using Batch API.

    Returns dict with standard_cost, batch_cost, and savings_usd.
    """
    total_input = request_count * avg_input_tokens
    total_output = request_count * avg_output_tokens
    standard_cost = (
        total_input * price_per_million_input
        + total_output * price_per_million_output
    ) / 1_000_000
    batch_cost = standard_cost * batch_discount
    return {
        "standard_cost_usd": round(standard_cost, 6),
        "batch_cost_usd": round(batch_cost, 6),
        "savings_usd": round(standard_cost - batch_cost, 6),
        "savings_percent": round((1 - batch_discount) * 100, 1),
    }
