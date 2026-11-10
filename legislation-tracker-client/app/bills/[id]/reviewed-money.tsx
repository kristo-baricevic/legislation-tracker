"use client";

import { useState } from 'react';
import type { ReaderEnhancementResult } from '@/lib/api';
import { Evidence } from './reader-explanation';

export function ReviewedMoney({ result }: { result: ReaderEnhancementResult }) {
  const [action, setAction] = useState('');
  const [year, setYear] = useState('');
  const [page, setPage] = useState(1);
  const all = result.source_review?.financial_items ?? [];
  const rows = all.filter(item => (!action || item.label === action) && (!year || item.fiscal_years.includes(Number(year))));
  const pages = Math.max(1, Math.ceil(rows.length / 10));
  const current = Math.min(page, pages);
  const years = [...new Set(all.flatMap(item => item.fiscal_years))].sort();
  return <section className="mb-6 rounded-lg border border-slate-300 bg-white shadow-sm">
    <header className="border-b border-slate-200 bg-slate-50 p-4"><h2 className="text-xl font-semibold">Money in this bill</h2></header>
    <div className="p-4">
      <div className="mb-4 flex flex-wrap gap-3">
        <label className="text-sm font-semibold">Financial action<select className="ml-2 rounded border border-slate-300 bg-white px-3 py-2" value={action} onChange={e => { setAction(e.target.value); setPage(1); }}>
          <option value="">All actions</option>{[...new Set(all.map(item => item.label))].sort().map(label => <option key={label}>{label}</option>)}
        </select></label>
        {years.length > 0 && <label className="text-sm font-semibold">Fiscal year<select className="ml-2 rounded border border-slate-300 bg-white px-3 py-2" value={year} onChange={e => { setYear(e.target.value); setPage(1); }}>
          <option value="">All years</option>{years.map(value => <option key={value}>{value}</option>)}
        </select></label>}
      </div>
      {!rows.length && <p>No financial provisions match these filters.</p>}
      <ol className="divide-y divide-slate-200">{rows.slice((current - 1) * 10, current * 10).map((item, index) => <li key={`${current}-${index}`} className="grid gap-3 py-5 md:grid-cols-[12rem_minmax(0,1fr)]">
        <div><span className="text-sm font-semibold text-slate-600">{item.label}</span><p className="mt-2 font-semibold">{item.amount_display}</p></div>
        <p className="leading-7">{item.text}<Evidence number={(current - 1) * 10 + index + 1} sources={item.cited_sources} documentId={result.identity.document_id} /></p>
      </li>)}</ol>
      {pages > 1 && <nav aria-label="Financial provision pages" className="mt-5 flex items-center justify-center gap-4">
        <button disabled={current === 1} onClick={() => setPage(current - 1)} className="rounded border px-3 py-2 disabled:opacity-40">Prev</button>
        <span>Page {current} of {pages}</span><button disabled={current === pages} onClick={() => setPage(current + 1)} className="rounded border px-3 py-2 disabled:opacity-40">Next</button>
      </nav>}
    </div>
  </section>;
}
