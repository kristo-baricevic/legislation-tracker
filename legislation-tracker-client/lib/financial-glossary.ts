import type { FinancialAction } from "./contracts";

/** App-owned plain-language definitions, not interpretations of individual bills.
 * Budget terminology reference: https://www.cbo.gov/publication/57660
 * Rescissions: https://www.cbo.gov/publication/59209
 * Other entries describe this app's extraction categories.
 */
export const financialGlossary = {
  fee: { label: "Application or processing fee", definition: "A charge for applying for something or receiving a service." },
  surcharge: { label: "Surcharge", definition: "An extra charge added to an existing fee or payment." },
  penalty: { label: "Fine or penalty", definition: "Money someone may have to pay for breaking a rule or failing to meet a requirement." },
  fee_exemption: { label: "Fee exemption", definition: "A rule that lets certain people or organizations avoid paying a fee." },
  account_rule: { label: "Account and availability rule", definition: "A rule about where money is held, when it is available, or how it can be used." },
  appropriation: { label: "Appropriation", definition: "Legal permission for the government to use funding for a stated purpose. It does not mean the money has already been spent." },
  authorization: { label: "Authorization", definition: "Permission for a program or funding level. A separate funding law may still be needed before money can be spent." },
  allocation: { label: "Allocation", definition: "A rule dividing money among programs, places, or groups." },
  transfer: { label: "Transfer", definition: "Moving money from one government account or program to another. This does not necessarily add new funding." },
  rescission: { label: "Rescission", definition: "Canceling previously approved funding that has not yet been committed." },
  reduction: { label: "Reduction", definition: "Lowering an amount of funding, a payment, or a charge." },
  cancellation: { label: "Cancellation", definition: "Ending a specified funding amount or financial obligation. The bill explains what is canceled." },
  set_aside: { label: "Set-aside", definition: "Money reserved for a specific purpose or group. The bill says whether reserving it is required or optional." },
  limitation: { label: "Limitation", definition: "A cap or restriction on how much money can be used, or how it can be used." },
  other_explicit: { label: "Other explicit financial provision", definition: "A stated money-related rule that does not fit one of the more specific categories." },
  source_rule: { label: "Financial rule (see full wording)", definition: "A money-related rule whose full meaning has not been reliably extracted. Check the cited bill text." },
} satisfies Record<FinancialAction, { label: string; definition: string }>;
