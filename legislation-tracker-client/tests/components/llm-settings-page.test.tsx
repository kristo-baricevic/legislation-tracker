import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import SettingsPage from "@/app/settings/page";
import {
  deleteLLMSettings,
  getLLMSettings,
  getSession,
  updateLLMSettings,
  validateLLMCredential,
} from "@/lib/api";

vi.mock("next/navigation", () => ({
  useRouter: () => ({ replace: vi.fn() }),
}));

vi.mock("@/lib/api", () => ({
  deleteLLMSettings: vi.fn(),
  getLLMSettings: vi.fn(),
  getSession: vi.fn(),
  updateLLMSettings: vi.fn(),
  validateLLMCredential: vi.fn(),
}));

const configured = {
  feature_available: true,
  configured: true,
  provider: "openai",
  key_suffix: "1234",
  revision: 2,
  enabled: true,
  validation_status: "unverified" as const,
  validated_revision: null,
  validated_at: null,
  requested_model: "gpt-5.6-luna",
};

describe("LLM settings", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    vi.mocked(getSession).mockResolvedValue({
      authenticated: true,
      user: { email: "person@example.com" },
    });
    vi.mocked(getLLMSettings).mockResolvedValue(configured);
    vi.mocked(updateLLMSettings).mockResolvedValue({
      ...configured,
      revision: 3,
      key_suffix: "next",
    });
    vi.mocked(validateLLMCredential).mockResolvedValue({
      ...configured,
      validation_status: "valid",
      validated_revision: 2,
    });
    vi.mocked(deleteLLMSettings).mockResolvedValue(undefined);
  });

  it("saves a password-type key, never echoes it, and clears the field", async () => {
    const user = userEvent.setup();
    render(<SettingsPage />);

    const input = await screen.findByLabelText("OpenAI API key");
    expect(input).toHaveAttribute("type", "password");
    await user.type(input, "sk-test-next");
    await user.click(screen.getByRole("button", { name: "Save API key" }));

    await waitFor(() =>
      expect(updateLLMSettings).toHaveBeenCalledWith({ api_key: "sk-test-next" }),
    );
    expect(input).toHaveValue("");
    expect(screen.queryByDisplayValue("sk-test-next")).not.toBeInTheDocument();
    expect(await screen.findByText(/ending in next/)).toBeVisible();
  });

  it("warns before the one-call validation and reports its sanitized state", async () => {
    const user = userEvent.setup();
    render(<SettingsPage />);

    expect(await screen.findByText(/may create one small provider charge/i)).toBeVisible();
    await user.click(screen.getByRole("button", { name: "Validate key" }));

    await waitFor(() => expect(validateLLMCredential).toHaveBeenCalledTimes(1));
    expect(await screen.findByText("Valid")).toBeVisible();
  });
});
