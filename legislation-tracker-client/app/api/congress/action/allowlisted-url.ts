interface AllowedUrlPolicy {
  addCongressApiKey: boolean;
  pathPrefixes: string[];
}

const ALLOWED_URLS: Record<string, AllowedUrlPolicy> = {
  "api.congress.gov": {
    addCongressApiKey: true,
    pathPrefixes: ["/v3/"],
  },
  "clerk.house.gov": {
    addCongressApiKey: false,
    pathPrefixes: ["/evs/"],
  },
};

export function resolveAllowedCongressActionUrl(
  rawUrl: string,
  congressApiKey: string | undefined,
): URL | null {
  let url: URL;
  try {
    url = new URL(rawUrl);
  } catch {
    return null;
  }

  if (url.protocol !== "https:") {
    return null;
  }

  const policy = ALLOWED_URLS[url.hostname.toLowerCase()];
  if (!policy) {
    return null;
  }

  if (!policy.pathPrefixes.some((prefix) => url.pathname.startsWith(prefix))) {
    return null;
  }

  if (policy.addCongressApiKey) {
    url.searchParams.delete("api_key");
    const apiKey = congressApiKey?.trim();
    if (apiKey) {
      url.searchParams.set("api_key", apiKey);
    }
  }

  return url;
}

