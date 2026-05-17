export type ReviewStatus = "accepted" | "rejected" | "needs_more_investigation";

export interface ReviewPayload {
  status: ReviewStatus;
  primaryInteractionMode?: string | null;
  difficulty?: string | null;
  tags?: Record<string, string[]>;
  note?: string;
  approvedForExport?: boolean;
  blockReason?: string | null;
}

export interface ImportPayload {
  runDir: string;
}
