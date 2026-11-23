import type { ReactNode } from "react";
import { explanationParagraphs, readerChecklist } from "@/lib/reader-copy";

/** The same reader layout in previews and full pages; never clips a condition. */
export default function ReaderText({ text, citation }: { text: string; citation?: ReactNode }) {
  const checklist = readerChecklist(text);
  if (checklist) return <div className="space-y-3 leading-7">
    <p>{checklist.intro}{citation}</p>
    <ul className="list-disc space-y-3 pl-5">{checklist.items.map((item, index) => <li key={index}>{item}</li>)}</ul>
  </div>;
  const paragraphs = explanationParagraphs(text);
  return <div className="space-y-3 leading-7">{paragraphs.map((paragraph, index) => <p key={index}>{paragraph}{index === paragraphs.length - 1 && citation}</p>)}</div>;
}
