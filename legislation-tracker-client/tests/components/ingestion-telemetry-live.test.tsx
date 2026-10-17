import React from "react";
import { render, screen, cleanup, act, fireEvent } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, expect, it, vi } from "vitest";
import IngestionTelemetryLive from "@/app/components/IngestionTelemetryLive";
import { authGet, authPost } from "@/lib/api";
vi.mock("@/lib/api", () => ({ authGet: vi.fn(), authPost: vi.fn() }));
afterEach(() => { cleanup(); vi.resetAllMocks(); vi.useRealTimers(); });
it("makes no automatic requests, keeps unknown counts unavailable and never starts on refresh", async () => {
    const user = userEvent.setup();
    render(<IngestionTelemetryLive />);
    expect(authGet).not.toHaveBeenCalled();
    expect(authPost).not.toHaveBeenCalled();
    expect(screen.getByRole("button", { name: "Start discovery and ingestion" })).toBeEnabled();
    vi.mocked(authGet).mockRejectedValue(new Error("offline"));
    await user.click(screen.getByRole("button", { name: "Refresh telemetry" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("Telemetry unavailable");
    expect(authPost).not.toHaveBeenCalled();
    vi.mocked(authPost).mockResolvedValue({ run_id: "direct-start", status: "pending" });
    await user.click(screen.getByRole("button", { name: "Start discovery and ingestion" }));
    expect(authPost).toHaveBeenCalledTimes(1);
    expect(screen.getByRole("status")).toHaveTextContent("direct-start");
});
it("starts discovery without first requesting telemetry", async () => {
    vi.mocked(authPost).mockResolvedValue({ run_id: "first-start", status: "pending" });
    render(<IngestionTelemetryLive />);
    await userEvent.setup().click(screen.getByRole("button", { name: "Start discovery and ingestion" }));
    expect(authGet).not.toHaveBeenCalled();
    expect(authPost).toHaveBeenCalledWith("/api/ingestion/poll-congress/", expect.objectContaining({ congress: 119, jurisdiction: "federal", idempotency_key: expect.any(String) }));
    expect(screen.getByRole("status")).toHaveTextContent("first-start");
});
it("shows a compact pipeline table with diagnostics collapsed", async () => {
    vi.mocked(authGet).mockImplementation(async path => path.includes("source-readiness") ? { available: false, missing_unqueued_metadata: null } : { observed_at: "2026-10-15T12:00:00Z", counts_by_kind_and_status: [{ kind: "bill_versions", status: "pending", count: 8 }, { kind: "bill_versions", status: "processing", count: 2 }], recent_work_states: [], discovery_run: null });
    render(<IngestionTelemetryLive />);
    await userEvent.setup().click(screen.getByRole("button", { name: "Refresh telemetry" }));
    expect(screen.getByRole("table", { name: "Pipeline work items" })).toHaveTextContent("Bill text versions");
    expect(screen.getByText("Source & technical details").closest("details")).not.toHaveAttribute("open");
    expect(screen.getByText("Recent activity").closest("details")).not.toHaveAttribute("open");
});
it("expires ready counts locally without making another network request", async () => {
    vi.useFakeTimers();
    vi.mocked(authGet).mockImplementation(async (path) => path.includes("source-readiness") ? { available: true, missing_unqueued_metadata: 11, age_seconds: 299, complete: true } : { observed_at: "2026-10-09T18:00:00Z", counts_by_kind_and_status: [], stale_leases: 0, discovery_run: null, recent_work_states: [] });
    render(<IngestionTelemetryLive />);
    await act(async () => { fireEvent.click(screen.getByRole("button", { name: "Refresh telemetry" })); });
    expect(screen.getByText("11", { exact: true })).toBeInTheDocument();
    await act(async () => { vi.advanceTimersByTime(2000); });
    expect(screen.queryByText("11", { exact: true })).not.toBeInTheDocument();
    expect(screen.getByText(/Stale — readiness is unavailable/)).toBeInTheDocument();
    expect(authGet).toHaveBeenCalledTimes(2);
    expect(authPost).not.toHaveBeenCalled();
});
it("distinguishes discovery from work status and reuses the start request key", async () => {
    const user = userEvent.setup();
    vi.mocked(authGet).mockImplementation(async (path) => path.includes("source-readiness") ? { available: false, missing_unqueued_metadata: null, reason: "Incomplete" } : { observed_at: "2026-10-09T18:00:00Z", last_discovery_completed_at: null, last_successful_work_item_at: "2026-10-09T17:00:00Z", counts_by_kind_and_status: [{ kind: "bill", status: "pending", count: 4 }], stale_leases: 0, discovery_run: null, recent_work_states: [] });
    vi.mocked(authPost).mockResolvedValue({ run_id: "run-1", status: "pending" });
    render(<IngestionTelemetryLive />);
    await user.click(screen.getByRole("button", { name: "Refresh telemetry" }));
    const start = await screen.findByRole("button", { name: "Start discovery and ingestion" });
    expect(start).toBeEnabled();
    expect(screen.getByText("Last successful work item")).toBeInTheDocument();
    await user.click(start);
    await user.click(start);
    expect(vi.mocked(authPost).mock.calls[0][1]).toEqual(vi.mocked(authPost).mock.calls[1][1]);
    expect(screen.getByRole("status")).toHaveTextContent("Downstream processing is separate");
});

it("requires the accepted run identity before preparing a new request", async () => {
    const user = userEvent.setup();
    let runId = "unrelated";
    vi.mocked(authGet).mockImplementation(async path => path.includes("source-readiness") ? { available: false, missing_unqueued_metadata: null } : { observed_at: "2026-10-09T18:00:00Z", counts_by_kind_and_status: [], recent_work_states: [], discovery_run: { id: runId, status: "succeeded" } });
    vi.mocked(authPost).mockResolvedValue({ run_id: "accepted", status: "pending" });
    render(<IngestionTelemetryLive />);
    await user.click(screen.getByRole("button", { name: "Refresh telemetry" }));
    await user.click(screen.getByRole("button", { name: "Start discovery and ingestion" }));
    await user.click(screen.getByRole("button", { name: "Refresh telemetry" }));
    const prepare = screen.getByRole("button", { name: "Prepare a new discovery request" });
    expect(prepare).toBeDisabled();
    runId = "accepted";
    await user.click(screen.getByRole("button", { name: "Refresh telemetry" }));
    expect(prepare).toBeEnabled();
});
it("ignores a start completion after unmount", async () => {
    const user = userEvent.setup();
    vi.mocked(authGet).mockImplementation(async path => path.includes("source-readiness") ? { available: false, missing_unqueued_metadata: null } : { observed_at: "2026-10-09T18:00:00Z", counts_by_kind_and_status: [], recent_work_states: [], discovery_run: null });
    let resolve!: (value: unknown) => void;
    vi.mocked(authPost).mockImplementation(() => new Promise(done => { resolve = done; }));
    const view = render(<IngestionTelemetryLive />);
    await user.click(screen.getByRole("button", { name: "Refresh telemetry" }));
    await user.click(screen.getByRole("button", { name: "Start discovery and ingestion" }));
    view.unmount();
    await act(async () => resolve({ run_id: "late", status: "pending" }));
    expect(screen.queryByRole("status")).not.toBeInTheDocument();
    expect(authPost).toHaveBeenCalledTimes(1);
});

it("keeps incremental readiness separate from historical gaps and renders basis invalidation", async () => {
    const user = userEvent.setup();
    let valid = true;
    vi.mocked(authGet).mockImplementation(async path => path.includes("source-readiness") ? {
        available: true, age_seconds: 1, complete: true,
        missing_unqueued_metadata: 9, ready_to_start: valid ? 3 : null,
        incremental_discoverable_count_available: valid,
        discovery_basis: { cursor_at: "2026-10-09T18:00:00Z", from_date_time: "2026-10-09T17:55:00Z" },
        discovery_checked_completed_at: "2026-10-09T18:10:00Z",
    } : { observed_at: "2026-10-09T18:10:00Z", counts_by_kind_and_status: [], recent_work_states: [], discovery_run: null });
    render(<IngestionTelemetryLive />);
    await user.click(screen.getByRole("button", { name: "Refresh telemetry" }));
    const ready = screen.getByRole("heading", { name: "Ready for incremental discovery" }).parentElement!;
    const gaps = screen.getByRole("heading", { name: "Missing unqueued metadata" }).parentElement!;
    expect(ready.querySelector("strong")).toHaveTextContent("3");
    expect(gaps.querySelector("strong")).toHaveTextContent("9");
    expect(screen.getByText(/Discovery basis: cursor/)).toHaveTextContent("2026-10-09T17:55:00Z");
    valid = false;
    await user.click(screen.getByRole("button", { name: "Refresh telemetry" }));
    expect(ready.querySelector("strong")).toHaveTextContent("Unavailable");
    expect(gaps.querySelector("strong")).toHaveTextContent("9");
    expect(authPost).not.toHaveBeenCalled();
});
