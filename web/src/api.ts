import type {
  CandidateCreateInput,
  CandidateCreated,
  CandidateSearchRequest,
  CandidateSearchResponse,
  JobCreate,
  JobMatchBatch,
  JobMatch,
  JobMatchCreate,
  JobVersion,
  JobVersionRequirementsUpdate,
  ResumeActivateRequest,
  ResumeDetail,
  ResumeFactsSaveRequest,
  ResumeLibraryResponse,
  ResumeReviewDetail,
  ResumeReviewQueueResponse,
  ResumeScore,
  ResumeScoreCreate,
  ResumeScoreOverride,
  ResumeSummary,
  ResumeSummaryManualCreate,
  ResumeUploadResponse,
  RecruitingAgentTurn,
  RecruitingAgentTurnInput,
  SavedFilter,
  SavedFilterCreate,
  ScoreTemplate,
  ScoreTemplateCreate,
} from "./types";

export * from "./types";

export interface ApiClientOptions {
  /** Defaults to the same-origin FastAPI prefix, /v1. */
  baseUrl?: string;
}

export class ApiError extends Error {
  readonly status: number;
  readonly payload: unknown;

  constructor(status: number, message: string, payload: unknown) {
    super(message);
    this.name = "ApiError";
    this.status = status;
    this.payload = payload;
  }
}

export function isApiError(error: unknown): error is ApiError {
  return error instanceof ApiError;
}

function normalizeBaseUrl(baseUrl: string | undefined): string {
  const normalized = (baseUrl?.trim() || "/v1").replace(/\/+$/, "");
  return normalized || "/v1";
}

function endpoint(baseUrl: string, path: string): string {
  return `${baseUrl}${path.startsWith("/") ? path : `/${path}`}`;
}

function resourcePath(value: string): string {
  return encodeURIComponent(value);
}

function isPlainObject(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

async function responsePayload(response: Response): Promise<unknown> {
  const contentType = response.headers.get("content-type") || "";
  if (contentType.includes("application/json")) {
    try {
      return await response.json();
    } catch {
      return null;
    }
  }

  try {
    return await response.text();
  } catch {
    return null;
  }
}

function errorMessage(status: number, payload: unknown): string {
  if (isPlainObject(payload) && typeof payload.detail === "string") {
    return payload.detail;
  }
  if (typeof payload === "string" && payload.trim()) {
    return payload;
  }
  return `Request failed with status ${status}`;
}

interface JsonRequestOptions extends Omit<RequestInit, "body"> {
  body?: unknown;
}

export interface ResumePdfObjectUrl {
  url: string;
  revoke: () => void;
}

export interface AuthSession {
  authenticated: boolean;
  login_required: boolean;
}

/** A typed same-origin client authenticated exclusively by the session cookie. */
export function createApiClient(options: ApiClientOptions = {}) {
  const baseUrl = normalizeBaseUrl(options.baseUrl);

  function headers(initial?: HeadersInit): Headers {
    return new Headers(initial);
  }

  async function request<T>(path: string, init: JsonRequestOptions = {}): Promise<T> {
    const { body, headers: initialHeaders, ...requestInit } = init;
    const requestHeaders = headers(initialHeaders);
    let requestBody: BodyInit | undefined;

    if (body !== undefined) {
      requestHeaders.set("Content-Type", "application/json");
      requestBody = JSON.stringify(body);
    }
    requestHeaders.set("Accept", "application/json");

    const response = await fetch(endpoint(baseUrl, path), {
      ...requestInit,
      headers: requestHeaders,
      body: requestBody,
      credentials: "same-origin",
    });
    if (!response.ok) {
      const payload = await responsePayload(response);
      throw new ApiError(response.status, errorMessage(response.status, payload), payload);
    }
    if (response.status === 204) {
      return undefined as T;
    }
    return (await responsePayload(response)) as T;
  }

  async function requestForm<T>(path: string, formData: FormData, init: Omit<RequestInit, "body"> = {}): Promise<T> {
    const requestHeaders = headers(init.headers);
    requestHeaders.set("Accept", "application/json");
    const response = await fetch(endpoint(baseUrl, path), {
      ...init,
      headers: requestHeaders,
      body: formData,
      credentials: "same-origin",
    });
    if (!response.ok) {
      const payload = await responsePayload(response);
      throw new ApiError(response.status, errorMessage(response.status, payload), payload);
    }
    return (await responsePayload(response)) as T;
  }

  async function requestBlob(path: string, init: Omit<RequestInit, "body"> = {}): Promise<Blob> {
    const response = await fetch(endpoint(baseUrl, path), {
      ...init,
      headers: headers(init.headers),
      credentials: "same-origin",
    });
    if (!response.ok) {
      const payload = await responsePayload(response);
      throw new ApiError(response.status, errorMessage(response.status, payload), payload);
    }
    return response.blob();
  }

  function originalPdfUrl(resumeId: string): string {
    return endpoint(baseUrl, `/resumes/${resourcePath(resumeId)}/original-file`);
  }

  return {
    /** Exposed for links only; protected production previews should use getPdfBlob. */
    originalPdfUrl,

    getAuthSession(): Promise<AuthSession> {
      return request<AuthSession>("/auth/session");
    },

    login(password: string): Promise<AuthSession> {
      return request<AuthSession>("/auth/login", {
        method: "POST",
        body: { password },
      });
    },

    logout(): Promise<void> {
      return request<void>("/auth/logout", { method: "POST" });
    },

    runRecruitingAgentTurn(input: RecruitingAgentTurnInput): Promise<RecruitingAgentTurn> {
      return request<RecruitingAgentTurn>("/recruiting-agent/turns", {
        method: "POST",
        body: input,
      });
    },

    async health(): Promise<{ status: string }> {
      const response = await fetch(baseUrl === "/v1" ? "/health" : `${baseUrl.replace(/\/v1$/, "")}/health`, {
        headers: headers(),
      });
      if (!response.ok) {
        const payload = await responsePayload(response);
        throw new ApiError(response.status, errorMessage(response.status, payload), payload);
      }
      return (await responsePayload(response)) as { status: string };
    },

    createCandidate(input: CandidateCreateInput = {}): Promise<CandidateCreated> {
      return request<CandidateCreated>("/candidates", { method: "POST", body: input });
    },

    uploadResume(
      file: File,
      options: { idempotencyKey?: string | null } = {},
    ): Promise<ResumeUploadResponse> {
      const formData = new FormData();
      formData.set("file", file);
      const idempotencyKey = options.idempotencyKey?.trim();
      const requestHeaders = new Headers();
      if (idempotencyKey) requestHeaders.set("Idempotency-Key", idempotencyKey);
      return requestForm<ResumeUploadResponse>("/resumes/upload", formData, {
        method: "POST",
        headers: requestHeaders,
      });
    },

    uploadResumeForCandidate(candidateId: string, file: File): Promise<ResumeUploadResponse> {
      const formData = new FormData();
      formData.set("file", file);
      return requestForm<ResumeUploadResponse>(
        `/candidates/${resourcePath(candidateId)}/resumes`,
        formData,
        { method: "POST" },
      );
    },

    getResume(resumeId: string): Promise<ResumeDetail> {
      return request<ResumeDetail>(`/resumes/${resourcePath(resumeId)}`);
    },

    getReview(resumeId: string): Promise<ResumeReviewDetail> {
      return request<ResumeReviewDetail>(`/resumes/${resourcePath(resumeId)}/review`);
    },

    listReviewQueue(page = 1, pageSize = 25): Promise<ResumeReviewQueueResponse> {
      const query = new URLSearchParams({ page: String(page), page_size: String(pageSize) });
      return request<ResumeReviewQueueResponse>(`/resumes/review-queue?${query.toString()}`);
    },

    /** Fetches the protected original PDF through the authenticated session. */
    getPdfBlob(resumeId: string): Promise<Blob> {
      return requestBlob(`/resumes/${resourcePath(resumeId)}/original-file`);
    },

    async getPdfObjectUrl(resumeId: string): Promise<ResumePdfObjectUrl> {
      const url = URL.createObjectURL(await requestBlob(`/resumes/${resourcePath(resumeId)}/original-file`));
      return { url, revoke: () => URL.revokeObjectURL(url) };
    },

    extractFacts(resumeId: string): Promise<ResumeDetail> {
      return request<ResumeDetail>(`/resumes/${resourcePath(resumeId)}/extract-facts`, { method: "POST" });
    },

    /** Queue a durable AI re-extraction. The server worker owns the model call. */
    queueAiExtraction(resumeId: string): Promise<ResumeDetail> {
      return request<ResumeDetail>(`/resumes/${resourcePath(resumeId)}/queue-ai-extraction`, { method: "POST" });
    },

    saveFacts(resumeId: string, input: ResumeFactsSaveRequest): Promise<ResumeDetail> {
      return request<ResumeDetail>(`/resumes/${resourcePath(resumeId)}/facts`, {
        method: "PUT",
        body: input,
      });
    },

    activateResume(resumeId: string, input: ResumeActivateRequest = {}): Promise<ResumeDetail> {
      return request<ResumeDetail>(`/resumes/${resourcePath(resumeId)}/activate`, {
        method: "POST",
        body: input,
      });
    },

    searchCandidates(input: CandidateSearchRequest = {}): Promise<CandidateSearchResponse> {
      return request<CandidateSearchResponse>("/candidates/search", { method: "POST", body: input });
    },

    listResumeLibrary(page = 1, pageSize = 50): Promise<ResumeLibraryResponse> {
      const query = new URLSearchParams({ page: String(page), page_size: String(pageSize) });
      return request<ResumeLibraryResponse>(`/resume-library?${query.toString()}`);
    },

    listSavedFilters(): Promise<SavedFilter[]> {
      return request<SavedFilter[]>("/saved-filters");
    },

    createSavedFilter(input: SavedFilterCreate): Promise<SavedFilter> {
      return request<SavedFilter>("/saved-filters", { method: "POST", body: input });
    },

    deleteSavedFilter(savedFilterId: string): Promise<void> {
      return request<void>(`/saved-filters/${resourcePath(savedFilterId)}`, { method: "DELETE" });
    },

    listScoreTemplates(): Promise<ScoreTemplate[]> {
      return request<ScoreTemplate[]>("/score-templates");
    },

    createScoreTemplate(input: ScoreTemplateCreate): Promise<ScoreTemplate> {
      return request<ScoreTemplate>("/score-templates", { method: "POST", body: input });
    },

    createScore(resumeId: string, input: ResumeScoreCreate): Promise<ResumeScore> {
      return request<ResumeScore>(`/resumes/${resourcePath(resumeId)}/scores`, {
        method: "POST",
        body: input,
      });
    },

    getScore(scoreId: string): Promise<ResumeScore> {
      return request<ResumeScore>(`/resume-scores/${resourcePath(scoreId)}`);
    },

    listScores(resumeId: string): Promise<ResumeScore[]> {
      return request<ResumeScore[]>(`/resumes/${resourcePath(resumeId)}/scores`);
    },

    overrideScoreDimension(scoreId: string, dimensionKey: string, input: ResumeScoreOverride): Promise<ResumeScore> {
      return request<ResumeScore>(
        `/resume-scores/${resourcePath(scoreId)}/dimensions/${resourcePath(dimensionKey)}/override`,
        { method: "POST", body: input },
      );
    },

    generateSummary(resumeId: string): Promise<ResumeSummary> {
      return request<ResumeSummary>(`/resumes/${resourcePath(resumeId)}/summaries`, { method: "POST" });
    },

    getSummary(summaryId: string): Promise<ResumeSummary> {
      return request<ResumeSummary>(`/resume-summaries/${resourcePath(summaryId)}`);
    },

    listSummaries(resumeId: string): Promise<ResumeSummary[]> {
      return request<ResumeSummary[]>(`/resumes/${resourcePath(resumeId)}/summaries`);
    },

    createManualSummaryVersion(summaryId: string, input: ResumeSummaryManualCreate): Promise<ResumeSummary> {
      return request<ResumeSummary>(`/resume-summaries/${resourcePath(summaryId)}/manual-versions`, {
        method: "POST",
        body: input,
      });
    },

    createJob(input: JobCreate): Promise<JobVersion> {
      return request<JobVersion>("/jobs", { method: "POST", body: input });
    },

    createJobVersion(jobId: string, input: JobCreate): Promise<JobVersion> {
      return request<JobVersion>(`/jobs/${resourcePath(jobId)}/versions`, { method: "POST", body: input });
    },

    listJobVersions(jobId: string): Promise<JobVersion[]> {
      return request<JobVersion[]>(`/jobs/${resourcePath(jobId)}/versions`);
    },

    getJobVersion(jobVersionId: string): Promise<JobVersion> {
      return request<JobVersion>(`/job-versions/${resourcePath(jobVersionId)}`);
    },

    extractJobRequirements(jobVersionId: string): Promise<JobVersion> {
      return request<JobVersion>(`/job-versions/${resourcePath(jobVersionId)}/extract`, { method: "POST" });
    },

    updateJobRequirements(jobVersionId: string, input: JobVersionRequirementsUpdate): Promise<JobVersion> {
      return request<JobVersion>(`/job-versions/${resourcePath(jobVersionId)}/requirements`, {
        method: "PUT",
        body: input,
      });
    },

    confirmJobVersion(jobVersionId: string): Promise<JobVersion> {
      return request<JobVersion>(`/job-versions/${resourcePath(jobVersionId)}/confirm`, { method: "POST" });
    },

    enqueueAllJobMatches(jobVersionId: string): Promise<JobMatchBatch> {
      return request<JobMatchBatch>(`/job-versions/${resourcePath(jobVersionId)}/match-all`, { method: "POST" });
    },

    getJobMatchBatch(batchId: string): Promise<JobMatchBatch> {
      return request<JobMatchBatch>(`/job-match-batches/${resourcePath(batchId)}`);
    },

    runJobMatch(resumeId: string, input: JobMatchCreate): Promise<JobMatch> {
      return request<JobMatch>(`/resumes/${resourcePath(resumeId)}/job-matches`, {
        method: "POST",
        body: input,
      });
    },

    getJobMatch(matchId: string): Promise<JobMatch> {
      return request<JobMatch>(`/job-matches/${resourcePath(matchId)}`);
    },

    getLatestConfirmedJobVersion(): Promise<JobVersion> {
      return request<JobVersion>("/jobs/latest-confirmed-version");
    },

    listConfirmedJobVersions(): Promise<JobVersion[]> {
      return request<JobVersion[]>("/jobs/confirmed-versions");
    },

    listJobMatches(resumeId: string): Promise<JobMatch[]> {
      return request<JobMatch[]>(`/resumes/${resourcePath(resumeId)}/job-matches`);
    },

    listJobVersionMatches(jobVersionId: string): Promise<JobMatch[]> {
      return request<JobMatch[]>(`/job-versions/${resourcePath(jobVersionId)}/matches`);
    },
  };
}

/** The application singleton. It defaults to same-origin `/v1`. */
export const api = createApiClient();

/**
 * A direct endpoint URL for the original PDF. It intentionally contains no
 * admin token; use api.getPdfBlob() for an authenticated in-app preview.
 */
export function getOriginalPdfUrl(resumeId: string): string {
  return api.originalPdfUrl(resumeId);
}
