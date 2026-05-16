// Centralized fetch wrapper for the SPA.
//
// The backend speaks two error shapes:
//   * legacy `{ "detail": "..." }` for the auth-disabled deployment;
//   * RFC 7807 `application/problem+json` for the auth-enabled deployment.
// `stashFetch` normalises both into typed throws so callers can `catch` on
// `ProblemError` / `ConcurrentEditError` without parsing media types
// themselves. A 401 unloads the page through `/auth/login?next=...` —
// individual components don't try to recover from it.

export interface Problem {
  type: string;
  title: string;
  status: number;
  detail?: string;
  instance?: string;
  [extra: string]: unknown;
}

export class HttpError extends Error {
  constructor(public status: number, message: string) {
    super(message);
  }
}

export class ProblemError extends Error {
  constructor(public problem: Problem) {
    super(problem.detail ?? problem.title);
  }
}

export class ConcurrentEditError extends ProblemError {
  // Set when the server reports its current ETag in the 412 body. Used by
  // the editor to offer a discard-and-reload flow.
  readonly currentEtag: string | null;
  constructor(problem: Problem) {
    super(problem);
    const e = problem['current_etag'];
    this.currentEtag = typeof e === 'string' ? e : null;
  }
}

export interface StashFetchOptions extends RequestInit {
  // When true (default), a 401 redirects the browser to /auth/login.
  // Set to false in code paths that want to handle the response themselves
  // — e.g. the startup `/auth/me` probe needs to inspect the status.
  redirectOn401?: boolean;
}

export async function stashFetch(
  input: string,
  init: StashFetchOptions = {}
): Promise<Response> {
  const { redirectOn401 = true, ...rest } = init;
  const res = await fetch(input, {
    ...rest,
    credentials: 'same-origin',
  });

  if (res.status === 401 && redirectOn401) {
    const next = window.location.pathname + window.location.search;
    window.location.assign(`/auth/login?next=${encodeURIComponent(next)}`);
    throw new HttpError(401, 'redirecting to login');
  }

  if (!res.ok) {
    const contentType = res.headers.get('Content-Type') ?? '';
    if (contentType.startsWith('application/problem+json')) {
      const problem = (await res.json()) as Problem;
      if (res.status === 412) {
        throw new ConcurrentEditError(problem);
      }
      throw new ProblemError(problem);
    }
  }

  return res;
}
