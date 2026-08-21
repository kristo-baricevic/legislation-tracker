import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import BillEnhancementPanel from "@/app/bills/[id]/bill-enhancement-panel";
import {
  ApiError,
  createBillEnhancement,
  getBillEnhancementEstimate,
  getLatestBillEnhancement,
  getStoredAccessToken,
} from "@/lib/api";

vi.mock("next/link", () => ({
  default: ({ children, href, ...props }: React.AnchorHTMLAttributes<HTMLAnchorElement>) => (
    <a href={href} {...props}>{children}</a>
  ),
}));

vi.mock("@/lib/api", () => {
  class MockApiError extends Error {
    readonly status: number;

    constructor(message: string, status: number) {
      super(message);
      this.status = status;
    }
  }

  return {
    ApiError: MockApiError,
    createBillEnhancement: vi.fn(),
    getBillEnhancement: vi.fn(),
    getBillEnhancementEstimate: vi.fn(),
    getLatestBillEnhancement: vi.fn(),
    getStoredAccessToken: vi.fn(),
    retryBillEnhancement: vi.fn(),
  };
});

const estimate = {
  feature_available: true,
  can_enhance: true,
  unavailable_reason: null,
  credential_revision: 2,
  provider: "openai",
  requested_model: "gpt-5.6-luna",
  reasoning_effort: "none",
  prompt_version: "1.0",
  output_schema_version: "1.1",
  source_packet_version: "1.0",
  source_fingerprint: "a".repeat(64),
  request_fingerprint: "b".repeat(64),
  serialized_request_bytes: 1200,
  estimated_input_tokens: 600,
  max_output_tokens: 4000,
  max_output_includes_reasoning: true,
  truncated: false,
  coverage_notice: null,
  source_description: "document_chunk",
  matching_enhancement: null,
};

describe("BillEnhancementPanel", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    vi.mocked(getLatestBillEnhancement).mockResolvedValue(null);
  });

  it("offers login without calling private endpoints for an anonymous reader", () => {
    vi.mocked(getStoredAccessToken).mockReturnValue(null);
    render(<BillEnhancementPanel billId={10} />);

    expect(screen.getByRole("link", { name: "Log in to use AI enhancement" })).toHaveAttribute(
      "href",
      "/login",
    );
    expect(getBillEnhancementEstimate).not.toHaveBeenCalled();
  });

  it("requires a cost confirmation containing the complete request estimate", async () => {
    const user = userEvent.setup();
    vi.mocked(getStoredAccessToken).mockReturnValue("token");
    vi.mocked(getBillEnhancementEstimate).mockResolvedValue(estimate);
    vi.mocked(createBillEnhancement).mockResolvedValue({
      id: 9,
      bill_id: 10,
      status: "pending",
      provider: "openai",
      requested_model: "gpt-5.6-luna",
      reasoning_effort: "none",
      prompt_version: "1.0",
      output_schema_version: "1.1",
      source_packet_version: "1.0",
      source_fingerprint: estimate.source_fingerprint,
      request_fingerprint: estimate.request_fingerprint,
      truncated: false,
      coverage_notice: null,
      disclaimer: "AI-generated legal information for review, not legal advice.",
      usage: { input_tokens: null, output_tokens: null, total_tokens: null },
      created_at: "2026-08-21T00:00:00Z",
      updated_at: "2026-08-21T00:00:00Z",
      completed_at: null,
      latest_attempt: null,
      result: null,
      attempts: [],
      poll_after_seconds: 2,
      stale: false,
    });

    render(<BillEnhancementPanel billId={10} />);
    await user.click(await screen.findByRole("button", { name: "Enhance with AI" }));

    const dialog = screen.getByRole("dialog", { name: "Confirm AI enhancement" });
    expect(dialog).toHaveTextContent("600 estimated input tokens");
    expect(dialog).toHaveTextContent("4,000 maximum output tokens");
    expect(dialog).toHaveTextContent(/provider may charge your account/i);
    await user.click(screen.getByRole("button", { name: "Confirm and enhance" }));

    await waitFor(() =>
      expect(createBillEnhancement).toHaveBeenCalledWith(10, {
        source_fingerprint: estimate.source_fingerprint,
        request_fingerprint: estimate.request_fingerprint,
        credential_revision: 2,
      }),
    );
  });

  it("refreshes a stale confirmation before allowing another paid request", async () => {
    const user = userEvent.setup();
    const refreshedEstimate = {
      ...estimate,
      credential_revision: 3,
      source_fingerprint: "c".repeat(64),
      request_fingerprint: "d".repeat(64),
      estimated_input_tokens: 700,
    };
    vi.mocked(getStoredAccessToken).mockReturnValue("token");
    vi.mocked(getBillEnhancementEstimate)
      .mockResolvedValueOnce(estimate)
      .mockResolvedValueOnce(refreshedEstimate);
    vi.mocked(createBillEnhancement).mockRejectedValueOnce(
      new ApiError("preflight_changed", 409),
    );

    render(<BillEnhancementPanel billId={10} />);
    await user.click(await screen.findByRole("button", { name: "Enhance with AI" }));
    await user.click(screen.getByRole("button", { name: "Confirm and enhance" }));

    await waitFor(() => expect(getBillEnhancementEstimate).toHaveBeenCalledTimes(2));
    expect(screen.queryByRole("dialog", { name: "Confirm AI enhancement" })).not.toBeInTheDocument();
    expect(screen.getByRole("alert")).toHaveTextContent(/review the refreshed estimate/i);

    await user.click(screen.getByRole("button", { name: "Enhance with AI" }));
    const refreshedDialog = screen.getByRole("dialog", { name: "Confirm AI enhancement" });
    expect(refreshedDialog).toHaveTextContent("700 estimated input tokens");
    expect(refreshedDialog).toHaveTextContent("Credential revision 3");
  });

  it("renders server-owned citations as cited sources, never verified evidence", async () => {
    vi.mocked(getStoredAccessToken).mockReturnValue("token");
    vi.mocked(getBillEnhancementEstimate).mockResolvedValue(estimate);
    vi.mocked(getLatestBillEnhancement).mockResolvedValue({
      id: 9,
      bill_id: 10,
      status: "succeeded",
      provider: "openai",
      requested_model: "gpt-5.6-luna",
      reasoning_effort: "none",
      prompt_version: "1.0",
      output_schema_version: "1.1",
      source_packet_version: "1.0",
      source_fingerprint: estimate.source_fingerprint,
      request_fingerprint: estimate.request_fingerprint,
      truncated: false,
      coverage_notice: null,
      disclaimer: "AI-generated legal information for review, not legal advice.",
      usage: { input_tokens: 100, output_tokens: 20, total_tokens: 120 },
      created_at: "2026-08-21T00:00:00Z",
      updated_at: "2026-08-21T00:00:00Z",
      completed_at: "2026-08-21T00:01:00Z",
      latest_attempt: null,
      result: {
        schema_version: "1.1",
        overview: [{
          text: "The bill requires a report.",
          source_refs: ["src_0001"],
          cited_sources: [{
            source_ref: "src_0001",
            label: "Cited source",
            quoted_text: "The Secretary shall publish a report.",
            section_label: "Introduced",
            start_char: 7,
            end_char: 44,
          }],
        }],
        key_impacts: [],
        obligations: [],
        funding_and_timing: [],
        uncertain_language: [],
      },
      attempts: [],
      poll_after_seconds: null,
      stale: false,
    });

    render(<BillEnhancementPanel billId={10} />);

    expect(await screen.findByText("The bill requires a report.")).toBeVisible();
    expect(screen.getByText("Cited source")).toBeVisible();
    expect(screen.queryByText(/verified evidence/i)).not.toBeInTheDocument();
  });

  it("keeps a stale success readable and offers the current request identity", async () => {
    vi.mocked(getStoredAccessToken).mockReturnValue("token");
    vi.mocked(getBillEnhancementEstimate).mockResolvedValue(estimate);
    vi.mocked(getLatestBillEnhancement).mockResolvedValue({
      id: 12,
      bill_id: 10,
      status: "succeeded",
      provider: "openai",
      requested_model: "old-model",
      reasoning_effort: "none",
      prompt_version: "1.0",
      output_schema_version: "1.1",
      source_packet_version: "1.0",
      source_fingerprint: "c".repeat(64),
      request_fingerprint: "d".repeat(64),
      truncated: false,
      coverage_notice: null,
      disclaimer: "AI-generated legal information.",
      usage: { input_tokens: 100, output_tokens: 10, total_tokens: 110 },
      created_at: "2026-08-20T00:00:00Z",
      updated_at: "2026-08-20T00:01:00Z",
      completed_at: "2026-08-20T00:01:00Z",
      latest_attempt: null,
      result: {
        schema_version: "1.1",
        overview: [],
        key_impacts: [],
        obligations: [],
        funding_and_timing: [],
        uncertain_language: [],
      },
      attempts: [],
      poll_after_seconds: null,
      stale: true,
    });

    render(<BillEnhancementPanel billId={10} />);

    expect(await screen.findByText(/older bill source or execution version/i)).toBeVisible();
    expect(screen.getByRole("button", { name: "Enhance current version" })).toBeVisible();
  });

  it("explains missing bill text without incorrectly sending the user to key settings", async () => {
    vi.mocked(getStoredAccessToken).mockReturnValue("token");
    vi.mocked(getBillEnhancementEstimate).mockResolvedValue({
      feature_available: true,
      can_enhance: false,
      unavailable_reason: "source_unavailable",
      credential_revision: 2,
      requested_model: "gpt-5.6-luna",
    });

    render(<BillEnhancementPanel billId={10} />);

    expect(await screen.findByText(/no stored bill text/i)).toBeVisible();
    expect(screen.queryByRole("link", { name: "Settings" })).not.toBeInTheDocument();
  });
});
