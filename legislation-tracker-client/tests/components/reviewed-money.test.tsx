import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { expect, it } from 'vitest';
import { ReviewedMoney } from '@/app/bills/[id]/reviewed-money';
import type { ReaderEnhancementResult } from '@/lib/api';

it('renders discovered amounts independently of NLP and filters and paginates them', async () => {
  const result: ReaderEnhancementResult = { schema_version: '1.4', identity: { contract_id: 1, contract_hash: 'hash', document_id: 19587, document_content_hash: 'text' }, summary: [], explanations: [],
    source_review: { reviewed_sources: ['src_0001'], additional_changes: [], financial_items: Array.from({ length: 11 }, (_, i) => ({ label: i === 10 ? 'Housing grants' : 'Tax credit', amount_display: i === 10 ? '$100–200 million' : '$85 per ton', text: `Provision ${i}`, fiscal_years: [2027], cited_sources: [{ source_ref: 'src_0001', label: 'Cited source', section_label: 'Sec. 107', quoted_text: 'shall be not less than $100,000,000', start_char: 20, end_char: 58 }] })) } };
  render(<ReviewedMoney result={result} />);
  expect(screen.getAllByText('$85 per ton')).toHaveLength(10);
  expect(screen.queryByText('Amount not extracted')).not.toBeInTheDocument();
  await userEvent.click(screen.getByRole('button', { name: 'Next' }));
  expect(screen.getByText('$100–200 million')).toBeVisible();
  await userEvent.selectOptions(screen.getByLabelText('Financial action'), 'Housing grants');
  expect(screen.getByText('Provision 10')).toBeVisible();
  expect(screen.queryByRole('button', { name: 'Next' })).not.toBeInTheDocument();
  await userEvent.click(screen.getByRole('button', { name: 'Source 1' }));
  expect(screen.getByRole('link', { name: 'Read bill text' })).toHaveAttribute('href', '/documents/19587?start=20&end=58');
});
