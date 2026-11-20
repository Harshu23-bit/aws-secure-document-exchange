const RETURN_TO_KEY = "cloudsecure.auth.returnTo";

export function getSafeReturnPath(value: unknown): string | null {
  if (typeof value !== "string") {
    return null;
  }

  const hasControlCharacters = Array.from(value).some((character) => {
    const code = character.charCodeAt(0);
    return code <= 0x1f || code === 0x7f;
  });

  if (
    !value.startsWith("/") ||
    value.startsWith("//") ||
    value.includes("\\") ||
    hasControlCharacters
  ) {
    return null;
  }

  try {
    const url = new URL(value, window.location.origin);

    if (
      url.origin !== window.location.origin ||
      url.username ||
      url.password
    ) {
      return null;
    }

    return `${url.pathname}${url.search}${url.hash}`;
  } catch {
    return null;
  }
}

export function saveReturnTo(value: unknown): void {
  try {
    const safePath = getSafeReturnPath(value);

    if (safePath) {
      sessionStorage.setItem(RETURN_TO_KEY, safePath);
    } else {
      sessionStorage.removeItem(RETURN_TO_KEY);
    }
  } catch {
    // Authentication must remain usable if browser storage is unavailable.
  }
}

export function consumeReturnTo(): string {
  try {
    const value = sessionStorage.getItem(RETURN_TO_KEY);

    sessionStorage.removeItem(RETURN_TO_KEY);

    return getSafeReturnPath(value) ?? "/";
  } catch {
    return "/";
  }
}
