import type { ComponentProps } from "react";

export function SearchInput({ type = "search", ...props }: ComponentProps<"input">) {
  return <input {...props} type={type} data-search-input />;
}

export function Dropdown(props: ComponentProps<"select">) {
  return <select {...props} data-dropdown />;
}
