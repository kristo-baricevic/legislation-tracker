import { render, screen } from "@testing-library/react";
import { it, expect } from "vitest";
import userEvent from "@testing-library/user-event";
import { ReaderExplanation } from "@/app/bills/[id]/reader-explanation";
import { SourcePopover } from "@/app/bills/[id]/source-popover";

it("shows the whole explanation and puts supporting notes in a numbered annotation, never a disclosure", async () => {
  const user = userEvent.setup();
  const text = "Agencies may collect fees. However, this permission applies only when the applicant qualifies under the requirements in this section and the agency has completed the required review. The agency must publish its decision and explain how it applied the eligibility rules before it can collect any payment from that applicant.";
  const { container } = render(<ReaderExplanation kind="line_item" itemId="1" original={text} heading="Fees" details={<p>Source section 4</p>}
    renderCitation={notes => <SourcePopover number={1}>{notes}</SourcePopover>} />);
  expect(container.querySelector("details")).toBeNull();
  expect(screen.getByText(/Agencies may collect fees/)).toBeVisible();
  expect(screen.getByText(/However, this permission/)).toBeVisible();
  expect(screen.queryByText("Source section 4")).not.toBeInTheDocument();
  await user.click(screen.getByRole("button", { name: "Source 1" }));
  expect(screen.getByText("Source section 4")).toBeVisible();
});
