"use client";

import { useParams } from "next/navigation";
import { DocumentReader } from "./document-reader";

export default function DocumentPage() {
  const { id } = useParams<{ id: string }>();
  return <DocumentReader key={id} documentId={id} />;
}
